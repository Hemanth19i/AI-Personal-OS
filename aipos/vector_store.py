"""Vector storage for AI Personal OS (LanceDB).

Stores chunk embeddings in a local LanceDB table keyed by ``chunk_id`` and
serves nearest-neighbour search over them. This is the *only* module that
touches LanceDB — both the write path (``add``, T2.6) and the read path
(``search``, T3.1) live here so the boundary stays in one place (ADR-015,
Design Doc §A4/§A6). No embedding generation, no SQL, no SQLite. Callers depend
on the ``VectorStore`` protocol so tests can inject a fake instead of requiring
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
    """Persists (chunk_id, embedding) pairs and searches over them."""

    def add(self, items: Iterable[tuple[int, Vector]]) -> None:
        ...

    def search(self, query: Vector, k: int) -> list[tuple[int, float]]:
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

    def search(self, query: Vector, k: int) -> list[tuple[int, float]]:
        """Return the ``k`` nearest chunk vectors as (chunk_id, distance) pairs.

        Ordered nearest-first (ascending distance). Read-only: it opens the
        table and queries it, never creating or mutating anything. Returns an
        empty list before anything has been indexed (no table yet). Raises
        ValueError if ``k`` is not positive.
        """
        if k <= 0:
            raise ValueError("k must be positive")
        database = self._require_db()
        listing = database.list_tables()
        existing = getattr(listing, "tables", listing)
        if _TABLE_NAME not in existing:
            return []
        # .to_list() returns plain dicts with the stored columns plus LanceDB's
        # computed _distance; it needs no pandas/pylance (unlike to_pandas()).
        rows = database.open_table(_TABLE_NAME).search(list(query)).limit(k).to_list()
        return [(row["chunk_id"], row["_distance"]) for row in rows]

    def _require_db(self):
        if self._db is None:
            raise RuntimeError("Vector store is not connected; call connect() first")
        return self._db
