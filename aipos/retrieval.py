"""Semantic retrieval for AI Personal OS.

The query-path counterpart to ``aipos.ingest``: given a natural-language query,
embed it, find the nearest chunk vectors, and return the matching chunks in
ranked order. This is the *Semantic* retrieval strategy only (PRD §6.7) — no
keyword/graph/hybrid search, no metadata filtering, no reranking, no answer
generation, no prompt construction, no citations. A synchronous direct call
(ADR-004): there is no event bus on this path.

Read-only by construction: retrieval never mutates SQLite or LanceDB. It owns no
storage engine — it composes the injected ``Embedder``, ``VectorStore`` (search)
and ``SQLiteStorage`` (chunk-text hydration), so SQL stays in ``storage.py`` and
LanceDB stays in ``vector_store.py``. Dependencies are injected, consistent with
the Embedder / VectorStore / OcrEngine pattern, so tests can supply fakes.
"""

from __future__ import annotations

from dataclasses import dataclass

from aipos.embedding import Embedder
from aipos.storage import SQLiteStorage
from aipos.vector_store import VectorStore

# Default number of chunks returned when the caller does not specify k.
DEFAULT_TOP_K = 5


@dataclass(frozen=True)
class RetrievalResult:
    """One retrieved chunk: its id, text, and similarity score.

    Intentionally minimal and stable. ``score`` is the vector-search distance
    (lower is nearer). File/page/source-location and citation fields are
    deliberately absent — those belong to answer generation (T3.3), not
    retrieval.
    """

    chunk_id: int
    text: str
    score: float


class SemanticRetriever:
    """Semantic (vector) retrieval strategy.

    Embeds the query, searches the vector store for the nearest chunk vectors,
    and hydrates their text from storage, preserving the vector-search ranking.
    """

    def __init__(
        self,
        embedder: Embedder,
        vector_store: VectorStore,
        storage: SQLiteStorage,
    ) -> None:
        self._embedder = embedder
        self._vector_store = vector_store
        self._storage = storage

    def retrieve(self, query: str, *, k: int = DEFAULT_TOP_K) -> list[RetrievalResult]:
        """Return up to ``k`` chunks most semantically similar to ``query``.

        Results are ordered nearest-first. Returns an empty list when the query
        has no non-whitespace content or the store holds no matching vectors.
        Raises ValueError if ``k`` is not positive.
        """
        if k <= 0:
            raise ValueError("k must be positive")
        if not query.strip():
            return []

        query_vector = self._embedder.embed([query])[0]
        hits = self._vector_store.search(query_vector, k)  # (chunk_id, distance), nearest-first
        if not hits:
            return []

        records = self._storage.get_chunks_by_ids([chunk_id for chunk_id, _ in hits])
        text_by_id = {record.id: record.text for record in records}

        results: list[RetrievalResult] = []
        for chunk_id, distance in hits:
            text = text_by_id.get(chunk_id)
            if text is None:
                continue  # a vector with no matching chunk row — skip defensively
            results.append(RetrievalResult(chunk_id=chunk_id, text=text, score=distance))
        return results
