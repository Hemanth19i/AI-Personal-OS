"""Intent routing for AI Personal OS (T4.4).

Cheap, offline heuristics that pick a retrieval strategy for a question *before*
any retrieval runs (ADR-007; Design Doc §A6): short/factual lookups take the
cheaper SEMANTIC path, relationship questions take the GRAPH path, and anything
ambiguous defaults to the richer GRAPH path ("when unsure, take the richer
path"). Query-only and pure — no storage, no embeddings, no LLM — so a wrong
route can never corrupt data, only pick a slightly cheaper or richer path.

Phase 1 exposes only the two *executable* strategies (SEMANTIC, GRAPH). The
frozen taxonomy's Keyword/Simple/Hybrid need engines Phase 1 never built, so
they are deferred rather than logged as if they ran — the router never names a
path that would not really execute. ``route`` returns a ``RoutingDecision``
carrying the chosen strategy plus a short human ``reason``; today only the
strategy changes behaviour and the whole decision is logged, but the reason is
the seed of the Milestone 5 reasoning trace, captured now at almost no cost.
Callers depend on the ``IntentRouter`` protocol, consistent with the rest of the
read path, so a learned router (Phase 2) can drop in later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Strategy(StrEnum):
    """A retrieval strategy the router can select.

    Only the strategies Phase 1 can actually execute are represented: SEMANTIC
    (vector retrieval, no graph work) and GRAPH (vector + graph expansion). The
    frozen Keyword/Simple/Hybrid strategies are deferred until their engines
    exist, so the router never names a path that would not really run.
    """

    SEMANTIC = "semantic"
    GRAPH = "graph"


@dataclass(frozen=True)
class RoutingDecision:
    """The router's choice: the strategy plus a short human-readable reason.

    Only ``strategy`` changes behaviour in T4.4; ``reason`` is logged now and
    becomes part of the explainability reasoning trace in Milestone 5.
    """

    strategy: Strategy
    reason: str


@runtime_checkable
class IntentRouter(Protocol):
    """Chooses a retrieval strategy for a question."""

    def route(self, query: str) -> RoutingDecision:
        ...


# Words that signal a relationship/comparison question -> the GRAPH path. Matched
# as whole words (case-insensitive) so "related" fires but "correlated" does not.
_RELATIONSHIP_WORDS = frozenset({
    "relate", "relates", "related", "relationship", "relationships",
    "between", "connect", "connects", "connected", "connection", "connections",
    "link", "links", "linked", "associate", "associated", "association",
    "compare", "compared", "comparison", "versus", "vs", "difference",
    "differences", "interact", "interacts", "interaction",
})

# Leading words that signal a simple factual/summary lookup -> the SEMANTIC path.
_SIMPLE_LEADS = frozenset({
    "who", "what", "whats", "when", "where", "which", "whose",
    "define", "definition", "summarize", "summary", "list", "explain",
    "describe", "tldr",
})

# A query no longer than this (in words), with no relationship signal and no
# factual lead, is treated as a short keyword-style lookup -> SEMANTIC.
_SHORT_QUERY_MAX_WORDS = 4

_WORD = re.compile(r"[a-z]+")


class HeuristicIntentRouter:
    """Rule-based intent router (ADR-007's v1 heuristic router).

    Priority: a relationship keyword routes to GRAPH; otherwise a leading
    factual/summary word or a short query routes to SEMANTIC; anything else is
    ambiguous and defaults to the richer GRAPH path. Deterministic and
    case-insensitive.
    """

    def route(self, query: str) -> RoutingDecision:
        if not query.strip():
            return RoutingDecision(Strategy.SEMANTIC, "empty query")

        words = set(_WORD.findall(query.lower()))

        relationship_hit = _RELATIONSHIP_WORDS & words
        if relationship_hit:
            keyword = sorted(relationship_hit)[0]
            return RoutingDecision(Strategy.GRAPH, f"relationship keyword: {keyword!r}")

        lead = _leading_word(query)
        if lead in _SIMPLE_LEADS:
            return RoutingDecision(Strategy.SEMANTIC, f"factual/summary query: {lead!r}")

        if len(query.split()) <= _SHORT_QUERY_MAX_WORDS:
            return RoutingDecision(Strategy.SEMANTIC, "short keyword-style query")

        return RoutingDecision(
            Strategy.GRAPH, "no simple-query signal; defaulting to richer graph path"
        )


def _leading_word(query: str) -> str:
    """Return the first word of ``query`` reduced to lowercase letters, or ''."""
    match = re.match(r"\s*([A-Za-z']+)", query)
    if match is None:
        return ""
    return re.sub(r"[^a-z]", "", match.group(1).lower())
