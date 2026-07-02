"""In-memory vector stores for tests (no LanceDB required)."""

from __future__ import annotations

from collections.abc import Iterable


class RecordingVectorStore:
    """Records writes, and returns preset search hits while recording queries.

    ``search_results`` is a canned, nearest-first list of (chunk_id, distance)
    pairs; ``search`` records each (query_vector, k) it is asked and returns at
    most ``k`` of them — enough to drive retrieval tests without LanceDB.
    """

    def __init__(
        self, search_results: Iterable[tuple[int, float]] | None = None
    ) -> None:
        self.added: list[tuple[int, list[float]]] = []
        self.searched: list[tuple[list[float], int]] = []
        self._search_results = list(search_results or [])

    def add(self, items: Iterable[tuple[int, list[float]]]) -> None:
        self.added.extend((chunk_id, list(vector)) for chunk_id, vector in items)

    def search(self, query: list[float], k: int) -> list[tuple[int, float]]:
        self.searched.append((list(query), k))
        return self._search_results[:k]


class FailingVectorStore:
    """Always raises, to exercise the write- and read-path failure paths."""

    def add(self, items: Iterable[tuple[int, list[float]]]) -> None:
        raise RuntimeError("vector store unavailable")

    def search(self, query: list[float], k: int) -> list[tuple[int, float]]:
        raise RuntimeError("vector store unavailable")
