"""Answer generation for AI Personal OS (T3.3).

Answer generation only: it takes the graph-aware retriever's result and turns it
into a grounded, cited answer (Design Doc §A6):

    (chunks + graph context) -> rerank chunks -> build grounded prompt -> LLM
        -> citation build -> AnswerResult

Retrieval orchestration lives upstream behind the ``Retriever`` protocol — the
intent-routed ``RoutedRetriever`` (T4.4) over ``GraphRetriever`` (T4.3) — so this
module stays responsible for answer generation, not retrieval. A synchronous
direct call (ADR-004). It owns no storage engine and writes no SQL or vectors —
SQL stays in ``storage.py`` and LanceDB in ``vector_store.py``; this module only
reads through their typed APIs. Dependencies are injected so tests run with fakes
(no Ollama, no LanceDB).

Reranking and citations remain chunk-only. Graph context enriches the prompt as
supporting context but is never reranked and never becomes a citation source
(T4.3). Every answer now carries an ``Explanation`` (T5.1) — a deterministic
record of the observable pipeline decisions (strategy, counts, grounding),
built here because this is the one component that observes the whole read path.
Its qualitative ``confidence`` (T5.2) and structural ``evidence`` verification
(T5.3) are both derived here from the same observed facts, by injected
collaborators — never from model output. The detailed graph_path of the frozen
``AnswerResult`` (Design Doc §A7) remains a later-ticket field on that same
``Explanation``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from aipos.explainability import (
    CitedChunk,
    Clock,
    ConfidenceCalculator,
    EvidenceVerifier,
    Explanation,
    RuleBasedConfidenceCalculator,
    RuleBasedEvidenceVerifier,
    SystemClock,
)
from aipos.graph_retrieval import RetrievalExecution, Retriever
from aipos.intent import Strategy
from aipos.llm import LLM
from aipos.prompt_builder import USED_CHUNKS_HEADER, build_prompt
from aipos.reranking import Reranker
from aipos.retrieval import DEFAULT_TOP_K, RetrievalResult
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
    """The answer payload: prose answer, sources, grounding, and its explanation.

    ``explanation`` (T5.1) records the observable pipeline decisions behind the
    answer; the frozen §A7 fields (qualitative confidence, detailed graph_path)
    join it in later tickets.
    """

    answer: str
    sources: list[Source]
    grounded: bool
    explanation: Explanation


class AnswerService:
    """Answers a question from the local corpus, grounded and cited."""

    def __init__(
        self,
        retriever: Retriever,
        reranker: Reranker,
        llm: LLM,
        storage: SQLiteStorage,
        *,
        clock: Clock | None = None,
        confidence: ConfidenceCalculator | None = None,
        verifier: EvidenceVerifier | None = None,
    ) -> None:
        self._retriever = retriever
        self._reranker = reranker
        self._llm = llm
        self._storage = storage
        self._clock = clock if clock is not None else SystemClock()
        self._confidence = (
            confidence if confidence is not None else RuleBasedConfidenceCalculator()
        )
        self._verifier = verifier if verifier is not None else RuleBasedEvidenceVerifier()

    def answer(self, question: str, *, k: int = DEFAULT_TOP_K) -> AnswerResult:
        """Retrieve (with graph expansion), rerank, and generate a cited answer.

        Returns a not-grounded result with no sources — without calling the LLM —
        when no chunks are retrieved. Otherwise the LLM answers from the reranked
        chunks, enriched by graph context; grounding and sources come from the
        ``USED_CHUNKS`` footer. Reranking and citations are chunk-only; the graph
        context is supporting prompt context, never reranked or cited. Every path
        attaches an ``Explanation`` of the observable pipeline decisions (T5.1).
        """
        execution = self._retriever.retrieve(question, k=k)
        chunks = self._reranker.rerank(question, execution.result.chunks)
        if not chunks:
            explanation = self._explain(
                execution, chunks=chunks, cited=[], reranked_count=0,
                llm_consulted=False, grounded=False, citation_count=0,
            )
            return AnswerResult(
                answer=_NO_CONTEXT_ANSWER, sources=[], grounded=False,
                explanation=explanation,
            )

        prompt = build_prompt(question, chunks, execution.result.graph_context)
        raw = self._llm.generate(prompt)

        answer_text, positions = _parse_footer(raw)
        cited = _valid_positions(positions, len(chunks))
        if not cited:
            # USED_CHUNKS: NONE, or a missing/malformed/out-of-range footer.
            explanation = self._explain(
                execution, chunks=chunks, cited=cited, reranked_count=len(chunks),
                llm_consulted=True, grounded=False, citation_count=0,
            )
            return AnswerResult(
                answer=answer_text, sources=[], grounded=False,
                explanation=explanation,
            )

        sources = self._build_sources(cited, chunks)
        explanation = self._explain(
            execution, chunks=chunks, cited=cited, reranked_count=len(chunks),
            llm_consulted=True, grounded=True, citation_count=len(sources),
        )
        return AnswerResult(
            answer=answer_text, sources=sources, grounded=True,
            explanation=explanation,
        )

    def _explain(
        self,
        execution: RetrievalExecution,
        *,
        chunks: list[RetrievalResult],
        cited: list[int],
        reranked_count: int,
        llm_consulted: bool,
        grounded: bool,
        citation_count: int,
    ) -> Explanation:
        """Assemble the Explanation from observed read-path facts (T5.1-T5.3).

        Confidence (T5.2) is derived by the injected ``ConfidenceCalculator``
        from observable facts — never from model output. Evidence (T5.3) is a
        parallel, independent structural check of the citation chain built from
        ``chunks`` (the retrieved/reranked candidates) and ``cited`` (their
        1-based cited positions) — it never influences confidence.
        """
        routing = execution.routing
        result = execution.result
        retrieved_count = len(result.chunks)
        graph_relation_count = len(result.graph_context)
        confidence = self._confidence.assess(
            llm_consulted=llm_consulted,
            grounded=grounded,
            citation_count=citation_count,
            graph_relation_count=graph_relation_count,
            retrieved_count=retrieved_count,
            reranked_count=reranked_count,
        )
        evidence = self._verifier.verify(
            grounded=grounded,
            retrieved_chunk_ids=frozenset(chunk.chunk_id for chunk in chunks),
            cited_chunks=[
                CitedChunk(chunk_id=chunks[position - 1].chunk_id, text=chunks[position - 1].text)
                for position in cited
            ],
        )
        return Explanation(
            timestamp=self._clock.now().isoformat(),
            strategy=routing.strategy.value,
            reason=routing.reason,
            retrieved_count=retrieved_count,
            graph_expanded=routing.strategy is Strategy.GRAPH,
            graph_relation_count=graph_relation_count,
            reranked_count=reranked_count,
            llm_consulted=llm_consulted,
            grounded=grounded,
            citation_count=citation_count,
            confidence=confidence,
            evidence=evidence,
        )

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
