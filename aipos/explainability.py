"""Explainability for AI Personal OS (T5.1, T5.2, T5.3).

The ``Explanation`` — a structured, deterministic record of the *observable*
pipeline decisions behind an answer (ADR-013): which strategy the router chose
and why, how many chunks were retrieved, whether graph expansion ran, how many
candidates the reranker returned, whether the LLM was consulted and grounded,
and how many citations resulted. It describes how evidence was *combined*, not
the language model's internal cognition — no chain-of-thought, nothing inferred,
nothing hallucinated. Every field is copied from a value the read path already
computed.

It is the outward-facing explainability object for the whole milestone. The T5.2
qualitative ``confidence`` is one of its fields, derived by an injected
``ConfidenceCalculator`` from the same observable facts (never model output).
T5.3 adds ``evidence`` — a structural *citation-integrity* check, not semantic
entailment: it verifies the answer is grounded, citations exist, every cited
chunk id was actually retrieved, and cited chunk text is non-empty. It never
judges whether a citation truly proves the answer's claim (that would require
an LLM call, embeddings, or similarity — explicitly out of scope) and it never
influences ``confidence``, which remains exactly the T5.2 output.

Construction lives in ``AnswerService`` (the one component that observes the
entire read path); rendering lives in the CLI. This module owns neither — it is
a pure data model plus the injectable ``Clock``, ``ConfidenceCalculator``, and
``EvidenceVerifier``, so the single non-deterministic field (``timestamp``)
stays testable and the scoring/verification rules stay swappable, mirroring the
``LLM`` / ``Retriever`` / ``Embedder`` dependency-injection style. Imports
nothing from ``aipos`` (leaf).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Supplies the current time, injectable so timestamps are testable."""

    def now(self) -> datetime:
        ...


class SystemClock:
    """Default clock: the real wall clock in UTC."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class Confidence(StrEnum):
    """Qualitative confidence in an answer, derived from pipeline facts (T5.2).

    Deliberately qualitative (ADR-012) — never a probability or model
    self-report. ``NONE`` is the honest level for the no-answer path (no chunks
    retrieved, LLM never consulted), distinct from ``LOW`` (an answer was
    produced but is weakly supported).
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


@dataclass(frozen=True)
class CitedChunk:
    """A chunk id/text pair for one citation, passed to the ``EvidenceVerifier``.

    A minimal, storage/retrieval-agnostic carrier — ``explainability.py`` stays
    a leaf and cannot import ``RetrievalResult`` from ``aipos.retrieval``.
    ``AnswerService`` builds these from the chunks it already retrieved and cited.
    """

    chunk_id: int
    text: str


@dataclass(frozen=True)
class EvidenceVerification:
    """Structural citation-integrity result (T5.3) — NOT semantic entailment.

    Verifies only that the evidence *chain* is structurally sound: the answer
    is grounded, at least one citation exists, and every cited chunk id was
    among the retrieved chunks with non-empty text. It never judges whether a
    citation actually *proves* the answer's claim.
    """

    verified: bool
    reason: str
    verified_citations: int
    total_citations: int


@dataclass(frozen=True)
class Explanation:
    """Observable, deterministic record of how an answer was produced (T5.1-T5.3).

    All fields but ``timestamp`` are exact observations of the read path.
    ``strategy``/``reason`` come from the router's ``RoutingDecision``;
    ``graph_expanded`` reflects whether the graph path ran (distinct from
    ``graph_relation_count`` being zero); ``reranked_count`` is how many
    candidates survived reranking (a reorder today, not a cutoff);
    ``llm_consulted`` is false on the no-context short-circuit. ``confidence``
    (T5.2) is a deterministic qualitative level derived solely from the other
    observable facts. ``evidence`` (T5.3) is a parallel, independent structural
    verification of the citations — it does not influence ``confidence``.
    """

    timestamp: str  # UTC ISO-8601, from the injected Clock at construction
    strategy: str  # "semantic" | "graph"
    reason: str
    retrieved_count: int
    graph_expanded: bool
    graph_relation_count: int
    reranked_count: int
    llm_consulted: bool
    grounded: bool
    citation_count: int
    confidence: Confidence
    evidence: EvidenceVerification


@runtime_checkable
class ConfidenceCalculator(Protocol):
    """Derives a qualitative ``Confidence`` from observable pipeline facts.

    Injected into ``AnswerService`` (constructor DI) so a future calibrated or
    learned scorer can drop in behind this contract without touching answer
    generation. Implementations must depend ONLY on the execution facts passed
    here — never on model wording, embeddings, prompt/answer text, similarity,
    probabilities, self-evaluation, or another model call.
    """

    def assess(
        self,
        *,
        llm_consulted: bool,
        grounded: bool,
        citation_count: int,
        graph_relation_count: int,
        retrieved_count: int,
        reranked_count: int,
    ) -> Confidence:
        ...


class RuleBasedConfidenceCalculator:
    """Deterministic, rule-based confidence (T5.2, ADR-012 qualitative).

    A fixed decision cascade over observable facts — no weighting, no scoring,
    no hidden heuristics:

    - LLM never consulted (no chunks)            -> NONE
    - answer produced but not grounded           -> LOW
    - grounded but no usable citation            -> LOW
    - grounded, >= 2 citations AND graph support -> HIGH
    - otherwise (grounded, weaker support)       -> MEDIUM
    """

    def assess(
        self,
        *,
        llm_consulted: bool,
        grounded: bool,
        citation_count: int,
        graph_relation_count: int,
        retrieved_count: int,
        reranked_count: int,
    ) -> Confidence:
        if not llm_consulted:
            return Confidence.NONE
        if not grounded:
            return Confidence.LOW
        if citation_count == 0:
            return Confidence.LOW
        if citation_count >= 2 and graph_relation_count >= 1:
            return Confidence.HIGH
        return Confidence.MEDIUM


@runtime_checkable
class EvidenceVerifier(Protocol):
    """Verifies the structural integrity of an answer's citation chain (T5.3).

    Injected into ``AnswerService`` (constructor DI), following exactly the
    ``ConfidenceCalculator`` pattern, so a future verifier can drop in behind
    this contract without touching answer generation. Implementations must
    depend ONLY on the facts passed here — never on model wording, embeddings,
    prompt/answer text, similarity, probabilities, or another model call. This
    is structural citation verification, not semantic entailment: it answers
    "is every citation real and traceable?", never "does this citation prove
    the answer?".
    """

    def verify(
        self,
        *,
        grounded: bool,
        retrieved_chunk_ids: frozenset[int],
        cited_chunks: list[CitedChunk],
    ) -> EvidenceVerification:
        ...


class RuleBasedEvidenceVerifier:
    """Deterministic, rule-based structural citation verification (T5.3).

    A fixed decision cascade over observable facts — no weighting, no scoring,
    no hidden heuristics, no semantic entailment:

    - answer not grounded                          -> not verified
    - grounded but zero citations                  -> not verified
    - any citation ids a chunk outside retrieval    -> not verified
    - any cited chunk has empty/whitespace text     -> not verified
    - otherwise (every citation traces cleanly)     -> verified

    ``verified_citations`` always counts the cited chunks that individually
    resolve to a retrieved, non-empty chunk, independent of which branch fired.

    Deliberately does not deduplicate ``cited_chunks`` — "no additional
    heuristics" means this verifier counts exactly what it is given. In
    practice ``AnswerService`` already de-duplicates repeated citations (e.g. a
    model citing chunk 2 three times) before building ``cited_chunks``, via the
    existing T3.3 ``_valid_positions`` step, so a repeated citation reaches this
    verifier only once.
    """

    def verify(
        self,
        *,
        grounded: bool,
        retrieved_chunk_ids: frozenset[int],
        cited_chunks: list[CitedChunk],
    ) -> EvidenceVerification:
        total = len(cited_chunks)
        verified_citations = sum(
            1
            for chunk in cited_chunks
            if chunk.chunk_id in retrieved_chunk_ids and chunk.text.strip()
        )
        if not grounded:
            return EvidenceVerification(
                False, "answer is not grounded", verified_citations, total
            )
        if total == 0:
            return EvidenceVerification(False, "no citations", verified_citations, total)
        if any(chunk.chunk_id not in retrieved_chunk_ids for chunk in cited_chunks):
            return EvidenceVerification(
                False,
                "citation references a chunk not present in retrieval",
                verified_citations,
                total,
            )
        if any(not chunk.text.strip() for chunk in cited_chunks):
            return EvidenceVerification(
                False, "a cited chunk has empty text", verified_citations, total
            )
        return EvidenceVerification(
            True,
            f"all {total} cited chunk(s) are structurally valid",
            verified_citations,
            total,
        )
