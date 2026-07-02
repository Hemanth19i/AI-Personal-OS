"""In-memory vector stores for tests (no LanceDB required)."""

from __future__ import annotations

from collections.abc import Iterable


class RecordingVectorStore:
    """Records each (chunk_id, vector) pair it is asked to persist."""

    def __init__(self) -> None:
        self.added: list[tuple[int, list[float]]] = []

    def add(self, items: Iterable[tuple[int, list[float]]]) -> None:
        self.added.extend((chunk_id, list(vector)) for chunk_id, vector in items)


class FailingVectorStore:
    """Always raises, to exercise the vector-persistence failure path."""

    def add(self, items: Iterable[tuple[int, list[float]]]) -> None:
        raise RuntimeError("vector store unavailable")
