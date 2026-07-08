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

from dataclasses import dataclass

from aipos.retrieval import DEFAULT_TOP_K, RetrievalResult, SemanticRetriever
from aipos.storage import GraphRelation, SQLiteStorage


@dataclass(frozen=True)
class ExpandedRetrievalResult:
    """Semantic chunks plus the graph context expanded from them (T4.3).

    ``chunks`` are the citable, rerankable vector hits (unchanged). ``graph_context``
    is supplementary relationship context only — it is never reranked and never
    becomes a citation source.
    """

    chunks: list[RetrievalResult]
    graph_context: list[GraphRelation]


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
