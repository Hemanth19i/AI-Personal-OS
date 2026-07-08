"""Graph-aware retrieval for AI Personal OS (T4.3).

The first GraphRAG capability. Two collaborators live here:

- ``GraphExpander`` — the graph *strategy* (Design Doc §A6's "Graph" path:
  entity match → graph context). Given the semantically-retrieved chunks, it
  asks storage which known entities those chunks mention and pulls the
  relationships incident to them, returning them as context. Pure graph
  concern: no embeddings, no vector search, no reranking, no answer generation.

- ``GraphRetriever`` — the read-path *orchestrator*. It composes the injected
  ``SemanticRetriever`` (unchanged, still semantic-only) with the
  ``GraphExpander`` and returns an ``ExpandedRetrievalResult`` = chunks + graph
  context. This keeps retrieval orchestration out of ``AnswerService`` (which
  returns to being answer-generation only) and leaves room for T4.4's intent
  router and later keyword/hybrid strategies to slot in here.

Read-only and offline. It owns no storage engine — all SQL stays in
``storage.py`` (``find_entities_in_text`` / ``get_graph_context``); this module
only composes those typed APIs. Dependencies are injected, consistent with the
rest of the read path, so tests can supply fakes.

Scope is strictly T4.3: graph output is *context* (relationship triples), never
extra chunks (there is no chunk↔entity provenance in the frozen schema) and it
is never reranked or cited — chunk citations are unchanged. No intent routing,
no hybrid/graph ranking (those are later milestones).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from aipos.intent import IntentRouter, RoutingDecision, Strategy
from aipos.retrieval import DEFAULT_TOP_K, RetrievalResult, SemanticRetriever
from aipos.storage import GraphRelation, SQLiteStorage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExpandedRetrievalResult:
    """Semantic chunks plus the graph context expanded from them (T4.3).

    ``chunks`` are the citable, rerankable vector hits (unchanged). ``graph_context``
    is supplementary relationship context only — it is never reranked and never
    becomes a citation source. This stays a pure retrieval DTO: routing metadata
    lives on ``RetrievalExecution``, not here.
    """

    chunks: list[RetrievalResult]
    graph_context: list[GraphRelation]


@dataclass(frozen=True)
class RetrievalExecution:
    """A completed routed retrieval: the routing decision plus its result (T5.1).

    ``RoutedRetriever`` returns this so ``AnswerService`` can see *how* retrieval
    was routed (for the ``Explanation``) without routing metadata leaking into
    the retrieval DTO. Later read-path metadata (latency, timings, evidence)
    hangs off this wrapper, keeping ``ExpandedRetrievalResult`` a pure result.
    """

    routing: RoutingDecision
    result: ExpandedRetrievalResult


@runtime_checkable
class Retriever(Protocol):
    """Produces a ``RetrievalExecution`` for a query — answer generation's contract.

    The read-path contract that ``AnswerService`` depends on: retrieve, and
    report how retrieval was routed. ``RoutedRetriever`` satisfies it; future
    routed retrievers can slot in without touching answer generation.
    ``GraphRetriever``/``SemanticRetriever`` are the inner *strategies* (they
    return raw results) that a routed retriever composes — they are not this
    protocol.
    """

    def retrieve(self, query: str, *, k: int = DEFAULT_TOP_K) -> RetrievalExecution:
        ...


class GraphExpander:
    """Expands retrieved chunks into graph context (the §A6 Graph strategy).

    Composes storage's graph read APIs: it finds which known entities the
    retrieved chunk text mentions, then returns the relationships incident to
    those entities. Owns no SQL; read-only.
    """

    def __init__(self, storage: SQLiteStorage) -> None:
        self._storage = storage

    def expand(self, chunks: list[RetrievalResult]) -> list[GraphRelation]:
        """Return graph relationships for the entities mentioned in ``chunks``.

        Entity matching runs once over the combined chunk text (not per chunk),
        so it is a single storage call regardless of chunk count. Returns an
        empty list when there are no chunks, the chunks mention no known entity,
        or the graph is empty — leaving the answer path identical to pre-T4.3
        behaviour in those cases.
        """
        combined_text = "\n".join(chunk.text for chunk in chunks)
        if not combined_text.strip():
            return []
        entities = self._storage.find_entities_in_text(combined_text)
        if not entities:
            return []
        return self._storage.get_graph_context([entity.id for entity in entities])


class GraphRetriever:
    """Read-path orchestrator: semantic retrieval + graph expansion (T4.3).

    Runs the injected semantic retriever, then expands the resulting chunks into
    graph context, returning both as an ``ExpandedRetrievalResult``. Answer
    generation (rerank → prompt → LLM → citation) stays in ``AnswerService``.
    """

    def __init__(self, retriever: SemanticRetriever, expander: GraphExpander) -> None:
        self._retriever = retriever
        self._expander = expander

    def retrieve(self, query: str, *, k: int = DEFAULT_TOP_K) -> ExpandedRetrievalResult:
        """Retrieve top-``k`` chunks and the graph context expanded from them."""
        chunks = self._retriever.retrieve(query, k=k)
        graph_context = self._expander.expand(chunks)
        return ExpandedRetrievalResult(chunks=chunks, graph_context=graph_context)


class RoutedRetriever:
    """Read-path entry point: routes each query to a retrieval strategy (T4.4).

    Consults the injected ``IntentRouter`` and dispatches (the strategy pattern):
    the GRAPH strategy delegates to the graph-aware retriever (vector + graph
    expansion); the SEMANTIC strategy runs vector retrieval only and returns
    empty graph context, so simple lookups skip the graph work entirely and are
    visibly faster (Build Plan T4.4). It returns a ``RetrievalExecution`` pairing
    the routing decision with the result, so ``AnswerService`` can build the
    ``Explanation`` (T5.1) from observable facts. The decision is also logged.
    ``GraphRetriever`` is used unchanged (an inner strategy); this class is the
    one that satisfies the ``Retriever`` protocol ahead of ``AnswerService``.
    """

    def __init__(
        self,
        router: IntentRouter,
        semantic: SemanticRetriever,
        graph: GraphRetriever,
    ) -> None:
        self._router = router
        self._semantic = semantic
        self._graph = graph

    def retrieve(self, query: str, *, k: int = DEFAULT_TOP_K) -> RetrievalExecution:
        """Route ``query`` to a strategy and retrieve accordingly.

        SEMANTIC returns vector hits with no graph context; GRAPH delegates to
        the graph-aware retriever. Either way the routing decision is logged and
        returned alongside the result.
        """
        decision = self._router.route(query)
        logger.info(
            "IntentRouter:\nstrategy=%s\nreason=%s\nquery=%r",
            decision.strategy.name,
            decision.reason,
            query,
        )
        if decision.strategy is Strategy.GRAPH:
            result = self._graph.retrieve(query, k=k)
        else:
            result = ExpandedRetrievalResult(
                chunks=self._semantic.retrieve(query, k=k), graph_context=[]
            )
        return RetrievalExecution(routing=decision, result=result)
