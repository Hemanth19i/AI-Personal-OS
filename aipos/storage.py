"""SQLite storage layer for AI Personal OS.

The single owner of the SQLite database and the only module that writes SQL
(ADR-006, ADR-009, Design Doc §A2/§A4). Every other layer goes through the
``SQLiteStorage`` API and never touches the database directly.

Phase 1 (Build Plan T1.1) creates the ``files`` table — the per-file record
that anchors the ingestion state machine — and exposes minimal typed
data-access methods to insert and read rows. Chunk/entity/edge tables and the
rest of the file lifecycle arrive in later milestones.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Canonical database filename. Callers compose it against the data directory
# (Design Doc §A4) when the first consumer wires storage in (Milestone 1).
DATABASE_FILENAME = "aipos.db"

# Phase 1 uses a single workspace; workspace_id defaults to this until
# multi-workspace support arrives (frozen decision, PRD/Design Doc).
DEFAULT_WORKSPACE_ID = "default"

# Initial state of a file in the ingestion lifecycle (Design Doc §A5).
_INITIAL_STATUS = "pending"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    path         TEXT NOT NULL,
    hash         TEXT NOT NULL,
    status       TEXT NOT NULL,
    error        TEXT,
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass(frozen=True)
class FileRecord:
    """A row from the ``files`` table (Design Doc §A3)."""

    id: int
    workspace_id: str
    path: str
    hash: str
    status: str
    error: str | None
    created_at: str
    updated_at: str


class SQLiteStorage:
    """Owns the SQLite connection and all SQL for AI Personal OS.

    Named for its engine so it reads clearly alongside the other Phase 1
    storage engines added in later milestones (LanceDB at T2.4, Kùzu at T4.2).
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._connection: sqlite3.Connection | None = None

    def connect(self) -> None:
        """Open the database connection and ensure the schema exists."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the connection is opened on the main thread
        # but used from watchdog's dispatch thread during ingestion. watchdog
        # serializes callbacks, so access is single-threaded at any moment.
        connection = sqlite3.connect(self._db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.executescript(_SCHEMA)
        connection.commit()
        self._connection = connection
        logger.debug("Storage connected at %s", self._db_path)

    def close(self) -> None:
        """Close the database connection, if open."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> SQLiteStorage:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def add_file(
        self,
        *,
        path: str,
        file_hash: str,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
        status: str = _INITIAL_STATUS,
        error: str | None = None,
    ) -> int:
        """Insert a file row and return its new id."""
        connection = self._require_connection()
        cursor = connection.execute(
            "INSERT INTO files (workspace_id, path, hash, status, error) "
            "VALUES (?, ?, ?, ?, ?)",
            (workspace_id, path, file_hash, status, error),
        )
        connection.commit()
        return int(cursor.lastrowid)

    def get_file(self, file_id: int) -> FileRecord | None:
        """Return the file row with the given id, or None if it does not exist."""
        connection = self._require_connection()
        row = connection.execute(
            "SELECT id, workspace_id, path, hash, status, error, "
            "created_at, updated_at FROM files WHERE id = ?",
            (file_id,),
        ).fetchone()
        return _to_record(row) if row is not None else None

    def get_file_by_hash(self, file_hash: str) -> FileRecord | None:
        """Return a registered file with the given hash, or None if unseen."""
        connection = self._require_connection()
        row = connection.execute(
            "SELECT id, workspace_id, path, hash, status, error, "
            "created_at, updated_at FROM files WHERE hash = ? LIMIT 1",
            (file_hash,),
        ).fetchone()
        return _to_record(row) if row is not None else None

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("Storage is not connected; call connect() first")
        return self._connection


def _to_record(row: sqlite3.Row) -> FileRecord:
    return FileRecord(
        id=row["id"],
        workspace_id=row["workspace_id"],
        path=row["path"],
        hash=row["hash"],
        status=row["status"],
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
