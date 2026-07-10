"""Workspace export & import for AI Personal OS (T6.3).

Orchestrates backup/export/restore (Build Plan T6.3, PRD §6.15, Design Doc
§A10) by combining two things the codebase already owns safely: a consistent
copy of the SQLite database (via ``storage.backup_to`` — sqlite3's own online
backup API, T6.3) and a plain filesystem copy of the LanceDB vector directory.
This module never imports ``lancedb`` — the vector directory is copied as raw
files, never through the LanceDB client, so "LanceDB API only inside
vector_store.py" holds: nothing here calls into LanceDB at all.

The export bundle contains exactly two things — the SQLite database
(files/chunks/entities/edges) and the vector directory. Nothing else: memory,
settings, and preferences have no tables yet (T6.3 architecture analysis), and
Phase 1 has exactly one workspace (``DEFAULT_WORKSPACE_ID``), so there is no
per-workspace filtering to do — exporting "the" workspace today means
exporting the whole local database and vector directory as they stand.

Manual only: no scheduling, no automatic snapshots, no encryption, no
multi-workspace support — all explicitly out of scope for this ticket. Pure
standard library (``pathlib``, ``shutil``, ``zipfile``, ``tempfile``) — no new
dependencies. Plain functions with explicit parameters, matching this
codebase's existing coordinator style (``ingest.py``); no globals, no
singletons, synchronous throughout.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import zipfile
from pathlib import Path

from aipos.storage import DEFAULT_WORKSPACE_ID, SQLiteStorage

logger = logging.getLogger(__name__)

# Archive layout: the database at the archive root, the vector directory's
# contents under this prefix. Both names are internal to this module.
_DB_MEMBER = "aipos.db"
_VECTORS_DIRNAME = "vectors"


def export_workspace(
    workspace_id: str,
    storage: SQLiteStorage,
    vector_store_dir: Path,
    destination: Path,
) -> None:
    """Export ``workspace_id``'s data to a single ``.zip`` archive at ``destination``.

    Phase 1 has exactly one workspace; any other ``workspace_id`` raises
    ``ValueError``. ``storage`` must already be connected (its live database
    is copied via ``backup_to``, which works safely even while the app is
    actively writing). ``destination``'s parent directory is created if
    needed; an existing file at ``destination`` is overwritten.
    """
    if workspace_id != DEFAULT_WORKSPACE_ID:
        raise ValueError(
            f"Unknown workspace {workspace_id!r}; Phase 1 only has "
            f"{DEFAULT_WORKSPACE_ID!r}"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_db = Path(tmp) / _DB_MEMBER
        storage.backup_to(tmp_db)

        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(tmp_db, _DB_MEMBER)
            if vector_store_dir.exists():
                for file_path in sorted(vector_store_dir.rglob("*")):
                    if file_path.is_file():
                        relative = file_path.relative_to(vector_store_dir).as_posix()
                        archive.write(file_path, f"{_VECTORS_DIRNAME}/{relative}")

    logger.info("Exported workspace %r to %s", workspace_id, destination)


def import_workspace(source: Path, db_path: Path, vector_store_dir: Path) -> None:
    """Restore a workspace archive from ``source`` into ``db_path``/``vector_store_dir``.

    Refuses (raises ``RuntimeError``) if the target already has data — import
    must never silently overwrite an existing installation. "Non-empty" means
    ``db_path`` already exists, or ``vector_store_dir`` already exists and is
    non-empty. Raises ``ValueError`` if ``source`` is not a valid workspace
    archive (missing the database member).
    """
    if db_path.exists():
        raise RuntimeError(f"Refusing to import: database already exists at {db_path}")
    if vector_store_dir.exists() and any(vector_store_dir.iterdir()):
        raise RuntimeError(
            f"Refusing to import: vector directory already has data at {vector_store_dir}"
        )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(source, "r") as archive:
            archive.extractall(tmp_path)

        extracted_db = tmp_path / _DB_MEMBER
        if not extracted_db.exists():
            raise ValueError(
                f"{source} is not a valid workspace archive (missing {_DB_MEMBER!r})"
            )

        db_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(extracted_db, db_path)

        vector_store_dir.mkdir(parents=True, exist_ok=True)
        extracted_vectors = tmp_path / _VECTORS_DIRNAME
        if extracted_vectors.exists():
            shutil.copytree(extracted_vectors, vector_store_dir, dirs_exist_ok=True)

    logger.info("Imported workspace from %s into %s", source, db_path.parent)
