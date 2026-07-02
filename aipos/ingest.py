"""File registration for AI Personal OS.

Coordinates the SHA-256 utility and the storage layer to register a completed
file (Build Plan T1.4). Neither the hashing utility nor the storage layer knows
about the other; this application-level function ties them together and owns the
"skip if the hash is already registered" decision.

Called for each file that has passed the write-completion guard.
"""

from __future__ import annotations

import logging
from pathlib import Path

from aipos.hashing import sha256_file
from aipos.storage import FileRecord, SQLiteStorage

logger = logging.getLogger(__name__)


def register_file(path: Path, storage: SQLiteStorage) -> FileRecord | None:
    """Register a completed file by its content hash.

    Computes the file's SHA-256. If a file with that hash is already registered,
    the file is skipped and None is returned. Otherwise a new row is inserted
    with status 'pending' and the created record is returned.
    """
    file_hash = sha256_file(path)
    existing = storage.get_file_by_hash(file_hash)
    if existing is not None:
        logger.info("Already registered (hash seen); skipping: %s", path)
        return None
    file_id = storage.add_file(path=str(path), file_hash=file_hash)
    logger.info("Registered file id=%d: %s", file_id, path)
    return storage.get_file(file_id)
