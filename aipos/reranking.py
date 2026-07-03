"""Reranking for AI Personal OS.

The reranker stage of the read path (Design Doc §A5/§A6): it takes the candidate
chunks produced by ``aipos.retrieval`` and reorders them by relevance to the
query before they reach the context builder (T3.3). Ranking only — no retrieval,
no LLM, no answer generation, no prompt construction, no citations, no metadata
filtering, no caching, no GraphRAG.

Pure and side-effect free: a reranker is a function of ``(query, results)`` and
touches no storage engine, so SQL stays in ``storage.py`` and LanceDB in
``vector_store.py`` by construction. Callers depend on the ``Reranker`` protocol
(dependency injection, consistent with Embedder / VectorStore / OcrEngine), so
the frozen "local cross-encoder" (PRD §9) — or a later LLM reranker — can drop
in as a new implementation without changing retrieval or its callers.
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from aipos.retrieval import RetrievalResult

# Word-ish tokens: runs of ASCII letters/digits, compared case-insensitively.
_TOKEN = re.compile(r"[a-z0-9]+")


@runtime_checkable
class Reranker(Protocol):
    """Reorders retrieved candidates by relevance to the query.

    Implementations return a new list containing the same ``RetrievalResult``
    objects in a (possibly) different order. They must not mutate the input.
    """

    def rerank(
        self, query: str, results: list[RetrievalResult]
    ) -> list[RetrievalResult]:
        ...


class LexicalReranker:
    """Reorders candidates by lexical overlap between the query and each chunk.

    A dependency-free, deterministic stand-in for the frozen local cross-encoder
    (PRD §9). Each candidate is scored by how many distinct query terms its text
    contains (query-term coverage); the highest coverage comes first. The sort is
    stable, so candidates that tie — and the whole list when the query has no
    usable terms — keep their incoming (vector-similarity) order. This lets the
    reranked order visibly differ from raw vector order (Build Plan T3.2) without
    an LLM or a model download, and a real ``CrossEncoderReranker`` can replace it
    behind the ``Reranker`` protocol.

    The candidates' ``score`` (the vector distance from retrieval) is preserved
    unchanged — this stage reorders, it does not rescore.
    """

    def rerank(
        self, query: str, results: list[RetrievalResult]
    ) -> list[RetrievalResult]:
        query_terms = _tokenize(query)
        if not query_terms or not results:
            return list(results)  # nothing to reorder by; keep incoming order
        # Stable, descending by overlap: ties retain the input (vector) order.
        return sorted(
            results,
            key=lambda result: _overlap(query_terms, result.text),
            reverse=True,
        )


def _tokenize(text: str) -> set[str]:
    """Return the set of distinct lowercased word tokens in ``text``."""
    return set(_TOKEN.findall(text.lower()))


def _overlap(query_terms: set[str], text: str) -> int:
    """Count how many distinct query terms appear in ``text``."""
    return len(query_terms & _tokenize(text))
