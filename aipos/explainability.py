"""Explainability for AI Personal OS (T5.1, T5.2).

The ``Explanation`` — a structured, deterministic record of the *observable*
pipeline decisions behind an answer (ADR-013): which strategy the router chose
and why, how many chunks were retrieved, whether graph expansion ran, how many
candidates the reranker returned, whether the LLM was consulted and grounded,
and how many citations resulted. It describes how evidence was *combined*, not
the language model's internal cognition — no chain-of-thought, nothing inferred,
nothing hallucinated. Every field is copied from a value the read path already
computed.

It is the outward-facing explainability object for the whole milestone. The T5.2
qualitative ``confidence`` is now one of its fields, derived by an injected
``ConfidenceCalculator`` from the same observable facts (never model output);
any later graph-path / evidence-verification metadata joins it here without a
rename or refactor.

Construction lives in ``AnswerService`` (the one component that observes the
entire read path); rendering lives in the CLI. This module owns neither — it is
a pure data model plus the injectable ``Clock`` and ``ConfidenceCalculator``, so
the single non-deterministic field (``timestamp``) stays testable and the
scoring rules stay swappable, mirroring the ``LLM`` / ``Retriever`` / ``Embedder``
dependency-injection style. Imports nothing from ``aipos`` (leaf).
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
class Explanation:
    """Observable, deterministic record of how an answer was produced (T5.1/T5.2).

    All fields but ``timestamp`` are exact observations of the read path.
    ``strategy``/``reason`` come from the router's ``RoutingDecision``;
    ``graph_expanded`` reflects whether the graph path ran (distinct from
    ``graph_relation_count`` being zero); ``reranked_count`` is how many
    candidates survived reranking (a reorder today, not a cutoff);
    ``llm_consulted`` is false on the no-context short-circuit. ``confidence``
    (T5.2) is a deterministic qualitative level derived solely from the other
    observable facts.
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
