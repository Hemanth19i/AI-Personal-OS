"""SQLite storage layer for AI Personal OS.

The single owner of the SQLite database and the only module that writes SQL
(ADR-006, ADR-009, Design Doc §A2/§A4). Every other layer goes through the
``SQLiteStorage`` API and never touches the database directly.

Phase 1 creates the ``files`` table (T1.1) — the per-file record that anchors
the ingestion state machine — and the ``chunks`` table (T2.4). It exposes
minimal typed data-access methods to read/write both. Entity/edge tables and
the rest of the file lifecycle arrive in later milestones.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from aipos.chunking import Chunk

logger = logging.getLogger(__name__)

# Canonical database filename. Callers compose it against the data directory
# (Design Doc §A4) when the first consumer wires storage in (Milestone 1).
DATABASE_FILENAME = "aipos.db"

# Phase 1 uses a single workspace; workspace_id defaults to this until
# multi-workspace support arrives (frozen decision, PRD/Design Doc).
DEFAULT_WORKSPACE_ID = "default"


class FileStatus(StrEnum):
    """States a file moves through in the ingestion lifecycle (Design Doc §A5).

    pending → parsing → ocr* → chunking → embedding → extracting → verifying
    → ready, with failed reachable from any step (ocr applies only to scanned
    PDFs). Values are the strings persisted in the files.status column.
    """

    PENDING = "pending"
    PARSING = "parsing"
    OCR = "ocr"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    EXTRACTING = "extracting"
    VERIFYING = "verifying"
    READY = "ready"
    FAILED = "failed"


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

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY,
    file_id     INTEGER NOT NULL REFERENCES files(id),
    chunk_index INTEGER NOT NULL,
    text        TEXT NOT NULL,
    page        INTEGER,
    position    INTEGER,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass(frozen=True)
class ChunkRecord:
    """A persisted chunk: its database id plus its ordering index and text."""

    id: int
    index: int
    text: str


@dataclass(frozen=True)
class FileRecord:
    """A row from the ``files`` table (Design Doc §A3)."""

    id: int
    workspace_id: str
    path: str
    hash: str
    status: FileStatus
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
        connection.execute("PRAGMA foreign_keys = ON")  # enforce chunks -> files
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
        status: FileStatus = FileStatus.PENDING,
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

    def update_status(
        self, file_id: int, status: FileStatus, *, error: str | None = None
    ) -> None:
        """Set a file's lifecycle status and refresh ``updated_at``.

        ``error`` records a failure reason (typically with ``FileStatus.FAILED``)
        and is cleared on any status change that does not supply one. Transition
        legality is not enforced here — storage persists state; the pipeline
        owns ordering (see T2.1 notes).
        """
        connection = self._require_connection()
        connection.execute(
            "UPDATE files SET status = ?, error = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (status, error, file_id),
        )
        connection.commit()

    def add_chunks(self, file_id: int, chunks: Iterable[Chunk]) -> None:
        """Persist a file's chunks. Page/position are deferred (left NULL)."""
        connection = self._require_connection()
        connection.executemany(
            "INSERT INTO chunks (file_id, chunk_index, text) VALUES (?, ?, ?)",
            [(file_id, chunk.index, chunk.text) for chunk in chunks],
        )
        connection.commit()

    def get_chunks(self, file_id: int) -> list[Chunk]:
        """Return a file's chunks ordered by chunk index."""
        connection = self._require_connection()
        rows = connection.execute(
            "SELECT chunk_index, text FROM chunks WHERE file_id = ? "
            "ORDER BY chunk_index",
            (file_id,),
        ).fetchall()
        return [Chunk(index=row["chunk_index"], text=row["text"]) for row in rows]

    def get_chunk_records(self, file_id: int) -> list[ChunkRecord]:
        """Return a file's chunks with their database ids, ordered by index."""
        connection = self._require_connection()
        rows = connection.execute(
            "SELECT id, chunk_index, text FROM chunks WHERE file_id = ? "
            "ORDER BY chunk_index",
            (file_id,),
        ).fetchall()
        return [
            ChunkRecord(id=row["id"], index=row["chunk_index"], text=row["text"])
            for row in rows
        ]

    def get_chunks_by_ids(self, chunk_ids: list[int]) -> list[ChunkRecord]:
        """Return chunk records for the given ids; unmatched ids are omitted.

        A read-only lookup used by the retrieval read-path (T3.1) to hydrate
        chunk text for vector-search hits. Order is unspecified — callers that
        need a ranking (e.g. by search distance) reorder by id themselves. An
        empty ``chunk_ids`` list returns no rows without touching the database.
        """
        if not chunk_ids:
            return []
        connection = self._require_connection()
        placeholders = ",".join("?" for _ in chunk_ids)
        rows = connection.execute(
            f"SELECT id, chunk_index, text FROM chunks WHERE id IN ({placeholders})",
            tuple(chunk_ids),
        ).fetchall()
        return [
            ChunkRecord(id=row["id"], index=row["chunk_index"], text=row["text"])
            for row in rows
        ]

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
        status=FileStatus(row["status"]),
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
