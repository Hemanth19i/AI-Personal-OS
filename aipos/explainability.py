"""Explainability for AI Personal OS (T5.1).

The ``Explanation`` — a structured, deterministic record of the *observable*
pipeline decisions behind an answer (ADR-013): which strategy the router chose
and why, how many chunks were retrieved, whether graph expansion ran, how many
candidates the reranker returned, whether the LLM was consulted and grounded,
and how many citations resulted. It describes how evidence was *combined*, not
the language model's internal cognition — no chain-of-thought, nothing inferred,
nothing hallucinated. Every field is copied from a value the read path already
computed.

It is the outward-facing explainability object for the whole milestone: the T5.2
qualitative ``confidence`` and any later graph-path / evidence-verification
metadata become additional fields here without forcing a rename or refactor.

Construction lives in ``AnswerService`` (the one component that observes the
entire read path); rendering lives in the CLI. This module owns neither — it is
a pure data model plus an injectable ``Clock`` so the single non-deterministic
field (``timestamp``) stays testable, mirroring the ``LLM`` / ``Retriever`` /
``Embedder`` dependency-injection style. Imports nothing from ``aipos`` (leaf).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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


@dataclass(frozen=True)
class Explanation:
    """Observable, deterministic record of how an answer was produced (T5.1).

    All fields but ``timestamp`` are exact observations of the read path.
    ``strategy``/``reason`` come from the router's ``RoutingDecision``;
    ``graph_expanded`` reflects whether the graph path ran (distinct from
    ``graph_relation_count`` being zero); ``reranked_count`` is how many
    candidates survived reranking (a reorder today, not a cutoff);
    ``llm_consulted`` is false on the no-context short-circuit.
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
