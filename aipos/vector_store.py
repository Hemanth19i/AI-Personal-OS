"""Vector persistence for AI Personal OS (LanceDB).

Stores chunk embeddings in a local LanceDB table keyed by ``chunk_id``.
Persistence only — no embedding generation, no SQL, no SQLite, and no
retrieval/search (ADR-015, Design Doc §A4). Callers depend on the
``VectorStore`` protocol so tests can inject a fake instead of requiring
LanceDB; ``lancedb`` is imported lazily so the module loads without it.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol, runtime_checkable

Vector = list[float]

# LanceDB keeps its tables under this directory inside the data directory.
VECTOR_STORE_DIRNAME = "vectors"
_TABLE_NAME = "chunk_vectors"


@runtime_checkable
class VectorStore(Protocol):
    """Persists (chunk_id, embedding) pairs."""

    def add(self, items: Iterable[tuple[int, Vector]]) -> None:
        ...


class LanceVectorStore:
    """VectorStore backed by a local LanceDB table (chunk_id -> vector)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._db = None

    def connect(self) -> None:
        """Open (creating on first use) the local LanceDB database."""
        import lancedb

        self._path.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(self._path))

    def add(self, items: Iterable[tuple[int, Vector]]) -> None:
        """Persist (chunk_id, vector) pairs. An empty batch is a no-op."""
        rows = [
            {"chunk_id": chunk_id, "vector": list(vector)} for chunk_id, vector in items
        ]
        if not rows:
            return
        database = self._require_db()
        # list_tables() returns a response object (.tables) in recent LanceDB and
        # a plain list in older versions; handle both.
        listing = database.list_tables()
        existing = getattr(listing, "tables", listing)
        if _TABLE_NAME in existing:
            database.open_table(_TABLE_NAME).add(rows)
        else:
            database.create_table(_TABLE_NAME, data=rows)

    def _require_db(self):
        if self._db is None:
            raise RuntimeError("Vector store is not connected; call connect() first")
        return self._db
