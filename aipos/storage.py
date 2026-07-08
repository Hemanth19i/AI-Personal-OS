"""SQLite storage layer for AI Personal OS.

The single owner of the SQLite database and the only module that writes SQL
(ADR-006, ADR-009, Design Doc §A2/§A4). Every other layer goes through the
``SQLiteStorage`` API and never touches the database directly.

Phase 1 creates the ``files`` table (T1.1) — the per-file record that anchors
the ingestion state machine — the ``chunks`` table (T2.4), and the
``entities``/``edges`` knowledge-graph tables (T4.2). It exposes minimal typed
data-access methods to read/write them. The Phase 1 graph is SQLite-backed
(Kùzu was considered and deferred, Design Doc §A4/§9): entities/edges are plain
SQLite tables here, so all graph SQL stays in this single owner.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from aipos.chunking import Chunk
from aipos.extraction import Entity, Relationship

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

CREATE TABLE IF NOT EXISTS entities (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    name         TEXT NOT NULL,
    type         TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (workspace_id, name, type)
);

CREATE TABLE IF NOT EXISTS edges (
    id               INTEGER PRIMARY KEY,
    workspace_id     TEXT NOT NULL,
    source_entity_id INTEGER NOT NULL REFERENCES entities(id),
    target_entity_id INTEGER NOT NULL REFERENCES entities(id),
    relation         TEXT NOT NULL,
    weight           INTEGER NOT NULL DEFAULT 1,
    UNIQUE (workspace_id, source_entity_id, target_entity_id, relation)
);
"""


@dataclass(frozen=True)
class ChunkRecord:
    """A persisted chunk: its database id plus its ordering index and text."""

    id: int
    index: int
    text: str


@dataclass(frozen=True)
class ChunkSource:
    """A chunk's citation origin: its id and the path of the file it came from."""

    chunk_id: int
    file_path: str


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


@dataclass(frozen=True)
class EntityRecord:
    """A node from the ``entities`` table (Design Doc §A4)."""

    id: int
    workspace_id: str
    name: str
    type: str


@dataclass(frozen=True)
class EdgeRecord:
    """An edge from the ``edges`` table (Design Doc §A4).

    There is one edge per (source, target, relation) in a workspace; ``weight``
    accumulates how many chunks — across every file in the workspace — produced
    that identical triple, i.e. the relationship's workspace-level strength.
    """

    id: int
    source_entity_id: int
    target_entity_id: int
    relation: str
    weight: int


@dataclass(frozen=True)
class GraphRelation:
    """A graph edge as human-readable context: endpoint *names*, relation, weight.

    The read-model returned by ``get_graph_context`` for the graph-aware read
    path (T4.3). Endpoint ids are already resolved to names here so callers
    never touch entity rows; today it carries direct 1-hop relationships, and
    the shape leaves room to later grow (multi-hop, filtered, ranked) without
    changing callers.
    """

    source: str
    relation: str
    target: str
    weight: int


class SQLiteStorage:
    """Owns the SQLite connection and all SQL for AI Personal OS.

    Named for its engine so it reads clearly alongside the other Phase 1
    storage engine (LanceDB at T2.4); the T4.2 knowledge graph is SQLite-backed
    and therefore lives here too, rather than in a separate engine module.
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

    def get_chunk_sources(self, chunk_ids: list[int]) -> list[ChunkSource]:
        """Return (chunk_id, file_path) for the given ids; unmatched ids omitted.

        A read-only join of ``chunks`` to ``files`` used by the answer read-path
        (T3.3) to resolve which source file each cited chunk came from. Order is
        unspecified — callers reorder as needed. An empty list returns no rows
        without touching the database.
        """
        if not chunk_ids:
            return []
        connection = self._require_connection()
        placeholders = ",".join("?" for _ in chunk_ids)
        rows = connection.execute(
            "SELECT c.id AS chunk_id, f.path AS file_path "
            "FROM chunks c JOIN files f ON c.file_id = f.id "
            f"WHERE c.id IN ({placeholders})",
            tuple(chunk_ids),
        ).fetchall()
        return [
            ChunkSource(chunk_id=row["chunk_id"], file_path=row["file_path"])
            for row in rows
        ]

    def add_graph(
        self,
        entities: Iterable[Entity],
        relationships: Iterable[Relationship],
        *,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> None:
        """Persist a file's extracted entities and relationships (T4.2, §A4).

        Entities are upserted on their (workspace_id, name, type) identity with
        ``INSERT OR IGNORE`` — the UNIQUE constraint makes re-inserting the same
        entity a no-op, so identity is deterministic and safe for concurrent
        workers. Relationships are aggregated by their (source, target,
        relation) triple into an occurrence ``weight`` (how many chunks the
        triple appeared in); their endpoint names are resolved to entity ids.
        An edge whose endpoints do not resolve to persisted entities is skipped
        — entities are never fabricated (frozen schema, no provenance).

        Edges are likewise upserted on their (workspace_id, source, target,
        relation) identity: a repeated relationship — across chunks or across
        files — collapses into a single workspace edge whose weight accumulates
        (``weight = weight + excluded.weight``), so the graph holds one edge per
        relationship with a workspace-level strength. One commit, mirroring the
        other write methods.
        """
        connection = self._require_connection()
        connection.executemany(
            "INSERT OR IGNORE INTO entities (workspace_id, name, type) "
            "VALUES (?, ?, ?)",
            [(workspace_id, entity.name, entity.type) for entity in entities],
        )

        weights: dict[tuple[str, str, str], int] = {}
        for relationship in relationships:
            key = (relationship.source, relationship.target, relationship.relation)
            weights[key] = weights.get(key, 0) + 1

        endpoint_names = {
            name for (source, target, _) in weights for name in (source, target)
        }
        id_by_name = self._resolve_entity_ids(connection, workspace_id, endpoint_names)

        edge_rows = []
        for (source, target, relation), weight in weights.items():
            source_id = id_by_name.get(source)
            target_id = id_by_name.get(target)
            if source_id is None or target_id is None:
                continue  # unresolved endpoint — skip; never fabricate an entity
            edge_rows.append((workspace_id, source_id, target_id, relation, weight))
        if edge_rows:
            connection.executemany(
                "INSERT INTO edges (workspace_id, source_entity_id, "
                "target_entity_id, relation, weight) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (workspace_id, source_entity_id, target_entity_id, "
                "relation) DO UPDATE SET weight = weight + excluded.weight",
                edge_rows,
            )
        connection.commit()

    def get_entity_by_name(
        self, name: str, *, workspace_id: str = DEFAULT_WORKSPACE_ID
    ) -> EntityRecord | None:
        """Return the entity named ``name`` in the workspace, or None.

        When several entities share a name (same name, different type), the
        earliest-created one (lowest id) is returned, keeping resolution
        deterministic. Used to look up the "entity X" whose neighbours a caller
        wants (T4.2 done-when). Read-only.
        """
        connection = self._require_connection()
        row = connection.execute(
            "SELECT id, workspace_id, name, type FROM entities "
            "WHERE workspace_id = ? AND name = ? ORDER BY id LIMIT 1",
            (workspace_id, name),
        ).fetchone()
        return _to_entity(row) if row is not None else None

    def get_neighbors(
        self, entity_id: int, *, workspace_id: str = DEFAULT_WORKSPACE_ID
    ) -> list[EntityRecord]:
        """Return the entities directly connected to ``entity_id`` by any edge.

        Neighbours reached by an outgoing or an incoming edge are both included,
        de-duplicated and ordered by id. Returns an empty list for an unknown or
        isolated entity. Read-only.
        """
        connection = self._require_connection()
        rows = connection.execute(
            "SELECT DISTINCT e.id, e.workspace_id, e.name, e.type FROM entities e "
            "JOIN edges g ON "
            "((g.source_entity_id = ? AND g.target_entity_id = e.id) OR "
            " (g.target_entity_id = ? AND g.source_entity_id = e.id)) "
            "WHERE g.workspace_id = ? ORDER BY e.id",
            (entity_id, entity_id, workspace_id),
        ).fetchall()
        return [_to_entity(row) for row in rows]

    def get_edges(self, *, workspace_id: str = DEFAULT_WORKSPACE_ID) -> list[EdgeRecord]:
        """Return all edges in the workspace, ordered by id. Read-only."""
        connection = self._require_connection()
        rows = connection.execute(
            "SELECT id, source_entity_id, target_entity_id, relation, weight "
            "FROM edges WHERE workspace_id = ? ORDER BY id",
            (workspace_id,),
        ).fetchall()
        return [_to_edge(row) for row in rows]

    def find_entities_in_text(
        self, text: str, *, workspace_id: str = DEFAULT_WORKSPACE_ID
    ) -> list[EntityRecord]:
        """Return the workspace entities whose name occurs in ``text``.

        A higher-level read API for the graph-aware read path (T4.3): the caller
        asks "which known entities does this text mention?" and storage decides
        how to answer. Matching is whole-word and case-insensitive, so ``ZTNA``
        matches ``ztna`` but not the ``AI`` inside ``aid``. Today it scans the
        workspace's entities; it can become index-backed later without any
        caller change. Read-only; returns ``[]`` for blank text or no matches.
        """
        if not text.strip():
            return []
        connection = self._require_connection()
        rows = connection.execute(
            "SELECT id, workspace_id, name, type FROM entities "
            "WHERE workspace_id = ? ORDER BY id",
            (workspace_id,),
        ).fetchall()
        return [_to_entity(row) for row in rows if _name_in_text(row["name"], text)]

    def get_graph_context(
        self, entity_ids: list[int], *, workspace_id: str = DEFAULT_WORKSPACE_ID
    ) -> list[GraphRelation]:
        """Return the relationships incident to ``entity_ids`` as named triples.

        The graph-context read API for T4.3: for the given entities, return the
        edges touching them (as source or target) with endpoint ids already
        resolved to names, ordered deterministically by edge id. Today this is
        direct 1-hop relationships; the contract lets storage later grow to
        multi-hop / filtered / ranked context without changing callers. Read-only;
        ``[]`` for an empty id list.
        """
        if not entity_ids:
            return []
        connection = self._require_connection()
        placeholders = ",".join("?" for _ in entity_ids)
        rows = connection.execute(
            "SELECT s.name AS source, g.relation AS relation, t.name AS target, "
            "g.weight AS weight FROM edges g "
            "JOIN entities s ON g.source_entity_id = s.id "
            "JOIN entities t ON g.target_entity_id = t.id "
            f"WHERE g.workspace_id = ? AND (g.source_entity_id IN ({placeholders}) "
            f"OR g.target_entity_id IN ({placeholders})) ORDER BY g.id",
            (workspace_id, *entity_ids, *entity_ids),
        ).fetchall()
        return [
            GraphRelation(
                source=row["source"],
                relation=row["relation"],
                target=row["target"],
                weight=row["weight"],
            )
            for row in rows
        ]

    def _resolve_entity_ids(
        self, connection: sqlite3.Connection, workspace_id: str, names: set[str]
    ) -> dict[str, int]:
        """Map each entity name to its id (lowest id when a name repeats)."""
        if not names:
            return {}
        name_list = list(names)
        placeholders = ",".join("?" for _ in name_list)
        rows = connection.execute(
            f"SELECT name, MIN(id) AS id FROM entities "
            f"WHERE workspace_id = ? AND name IN ({placeholders}) GROUP BY name",
            (workspace_id, *name_list),
        ).fetchall()
        return {row["name"]: row["id"] for row in rows}

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


def _name_in_text(name: str, text: str) -> bool:
    """Whether ``name`` occurs as a whole word in ``text`` (case-insensitive).

    Word boundaries avoid spurious substring hits (``AI`` must not match inside
    ``aid``); ``re.escape`` keeps names with regex metacharacters literal.
    """
    name = name.strip()
    if not name:
        return False
    return re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE) is not None


def _to_entity(row: sqlite3.Row) -> EntityRecord:
    return EntityRecord(
        id=row["id"],
        workspace_id=row["workspace_id"],
        name=row["name"],
        type=row["type"],
    )


def _to_edge(row: sqlite3.Row) -> EdgeRecord:
    return EdgeRecord(
        id=row["id"],
        source_entity_id=row["source_entity_id"],
        target_entity_id=row["target_entity_id"],
        relation=row["relation"],
        weight=row["weight"],
    )
