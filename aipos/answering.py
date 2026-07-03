"""Answer generation for AI Personal OS (T3.3).

The top-level read-path orchestrator: it composes the injected semantic
retriever, reranker, prompt builder, LLM, and storage into the frozen pipeline
(Design Doc §A6):

    retrieve -> rerank -> build grounded prompt -> LLM -> citation build -> AnswerResult

A synchronous direct call (ADR-004). It owns no storage engine and writes no SQL
or vectors — SQL stays in ``storage.py`` and LanceDB in ``vector_store.py``; this
module only reads through their typed APIs. Dependencies are injected so tests
run with fakes (no Ollama, no LanceDB).

Scope is the T3.3 subset of the frozen ``AnswerResult`` (Design Doc §A7):
``answer`` + ``sources`` + ``grounded``. Confidence, reasoning_path, graph_path,
and strategy_used belong to later milestones and are intentionally absent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from aipos.llm import LLM
from aipos.prompt_builder import USED_CHUNKS_HEADER, build_prompt
from aipos.reranking import Reranker
from aipos.retrieval import DEFAULT_TOP_K, RetrievalResult, SemanticRetriever
from aipos.storage import SQLiteStorage

# Characters of chunk text kept as a citation snippet.
_SNIPPET_LEN = 200

# Answer returned when no context is available and the LLM is not consulted.
_NO_CONTEXT_ANSWER = "I don't know based on the available documents."


@dataclass(frozen=True)
class Source:
    """A cited chunk: its id, the file it came from, and a short snippet."""

    chunk_id: int
    file: str
    snippet: str


@dataclass(frozen=True)
class AnswerResult:
    """The T3.3 answer payload: the prose answer, its sources, and grounding."""

    answer: str
    sources: list[Source]
    grounded: bool


class AnswerService:
    """Answers a question from the local corpus, grounded and cited."""

    def __init__(
        self,
        retriever: SemanticRetriever,
        reranker: Reranker,
        llm: LLM,
        storage: SQLiteStorage,
    ) -> None:
        self._retriever = retriever
        self._reranker = reranker
        self._llm = llm
        self._storage = storage

    def answer(self, question: str, *, k: int = DEFAULT_TOP_K) -> AnswerResult:
        """Retrieve, rerank, and generate a grounded, cited answer.

        Returns a not-grounded result with no sources — without calling the LLM —
        when nothing relevant is retrieved. Otherwise the LLM answers strictly
        from the reranked chunks; grounding and sources come from the
        ``USED_CHUNKS`` footer.
        """
        retrieved = self._retriever.retrieve(question, k=k)
        chunks = self._reranker.rerank(question, retrieved)
        if not chunks:
            return AnswerResult(answer=_NO_CONTEXT_ANSWER, sources=[], grounded=False)

        prompt = build_prompt(question, chunks)
        raw = self._llm.generate(prompt)

        answer_text, positions = _parse_footer(raw)
        cited = _valid_positions(positions, len(chunks))
        if not cited:
            # USED_CHUNKS: NONE, or a missing/malformed/out-of-range footer.
            return AnswerResult(answer=answer_text, sources=[], grounded=False)

        sources = self._build_sources(cited, chunks)
        return AnswerResult(answer=answer_text, sources=sources, grounded=True)

    def _build_sources(
        self, positions: list[int], chunks: list[RetrievalResult]
    ) -> list[Source]:
        cited_chunks = [chunks[p - 1] for p in positions]  # 1-based -> 0-based
        file_by_id = {
            src.chunk_id: src.file_path
            for src in self._storage.get_chunk_sources(
                [chunk.chunk_id for chunk in cited_chunks]
            )
        }
        sources: list[Source] = []
        for chunk in cited_chunks:
            file_path = file_by_id.get(chunk.chunk_id)
            if file_path is None:
                continue  # cited chunk has no resolvable file — skip defensively
            sources.append(
                Source(
                    chunk_id=chunk.chunk_id,
                    file=file_path,
                    snippet=_snippet(chunk.text),
                )
            )
        return sources


def _parse_footer(response: str) -> tuple[str, list[int]]:
    """Split an LLM response into (answer_without_footer, cited_positions).

    Reads the last ``USED_CHUNKS`` footer. ``NONE`` or a missing/unparseable
    footer yields no positions. The footer marker is stripped from the answer.
    """
    header_index = response.rfind(USED_CHUNKS_HEADER)
    if header_index == -1:
        return response.strip(), []  # no footer at all

    answer_text = response[:header_index].strip()
    footer = response[header_index + len(USED_CHUNKS_HEADER):]
    if re.search(r"\bNONE\b", footer, flags=re.IGNORECASE):
        return answer_text, []
    positions = [int(n) for n in re.findall(r"\d+", footer)]
    return answer_text, positions


def _valid_positions(positions: list[int], count: int) -> list[int]:
    """Keep in-range (1..count) positions, de-duplicated, order preserved."""
    seen: set[int] = set()
    valid: list[int] = []
    for position in positions:
        if 1 <= position <= count and position not in seen:
            seen.add(position)
            valid.append(position)
    return valid


def _snippet(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= _SNIPPET_LEN:
        return collapsed
    return collapsed[:_SNIPPET_LEN].rstrip() + "…"
