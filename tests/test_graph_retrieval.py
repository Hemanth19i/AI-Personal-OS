"""Behaviour tests for graph-aware retrieval (T4.3).

GraphExpander is exercised against a real temp SQLiteStorage (seeded via
add_graph); GraphRetriever is exercised with lightweight fakes for the semantic
retriever and the expander, to assert composition without Ollama/LanceDB.
"""

import tempfile
import unittest
from pathlib import Path

from aipos.extraction import Entity, Relationship
from aipos.graph_retrieval import ExpandedRetrievalResult, GraphExpander, GraphRetriever
from aipos.retrieval import DEFAULT_TOP_K, RetrievalResult
from aipos.storage import GraphRelation, SQLiteStorage


def _chunk(text: str, chunk_id: int = 1) -> RetrievalResult:
    return RetrievalResult(chunk_id=chunk_id, text=text, score=0.0)


class GraphExpanderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self._tmp.name) / "aipos.db")
        self.storage.connect()
        self.expander = GraphExpander(self.storage)

    def tearDown(self) -> None:
        self.storage.close()
        self._tmp.cleanup()

    def _seed(self) -> None:
        self.storage.add_graph(
            [Entity("ZTNA", "concept"), Entity("Network", "concept"), Entity("Alice", "person")],
            [Relationship("ZTNA", "Network", "protects"), Relationship("Alice", "ZTNA", "mentions")],
        )

    def test_expands_relationships_of_mentioned_entity(self) -> None:
        self._seed()
        ctx = self.expander.expand([_chunk("The ZTNA design is described here.")])
        triples = {(r.source, r.relation, r.target) for r in ctx}
        self.assertIn(("ZTNA", "protects", "Network"), triples)
        self.assertIn(("Alice", "mentions", "ZTNA"), triples)  # incoming edge too

    def test_returns_graphrelations_with_weight(self) -> None:
        self._seed()
        ctx = self.expander.expand([_chunk("ZTNA")])
        self.assertTrue(ctx)
        self.assertTrue(all(isinstance(r, GraphRelation) for r in ctx))
        protects = next(r for r in ctx if r.relation == "protects")
        self.assertEqual(protects.weight, 1)

    def test_no_matching_entity_returns_empty(self) -> None:
        self._seed()
        self.assertEqual(
            self.expander.expand([_chunk("an unrelated passage about cooking")]), []
        )

    def test_empty_chunk_list_returns_empty(self) -> None:
        self._seed()
        self.assertEqual(self.expander.expand([]), [])

    def test_empty_graph_returns_empty(self) -> None:
        self.assertEqual(self.expander.expand([_chunk("ZTNA and Network")]), [])

    def test_matching_is_whole_word_case_insensitive(self) -> None:
        self.storage.add_graph(
            [Entity("AI", "concept"), Entity("ML", "concept")],
            [Relationship("AI", "ML", "relates_to")],
        )
        self.assertEqual(self.expander.expand([_chunk("a first aid kit")]), [])  # no 'AI'
        ctx = self.expander.expand([_chunk("ai and ml are related fields")])
        self.assertTrue(ctx)

    def test_matches_over_combined_text_of_all_chunks(self) -> None:
        self._seed()
        # Endpoints split across two chunks; matching over the combined text
        # still surfaces the edge connecting them.
        ctx = self.expander.expand([_chunk("Alice took notes", 1), _chunk("about the Network", 2)])
        triples = {(r.source, r.relation, r.target) for r in ctx}
        self.assertIn(("Alice", "mentions", "ZTNA"), triples)
        self.assertIn(("ZTNA", "protects", "Network"), triples)


class _FakeSemantic:
    """Records (query, k) and returns canned chunks (duck-types SemanticRetriever)."""

    def __init__(self, chunks: list[RetrievalResult]) -> None:
        self._chunks = chunks
        self.calls: list[tuple[str, int]] = []

    def retrieve(self, query: str, *, k: int) -> list[RetrievalResult]:
        self.calls.append((query, k))
        return list(self._chunks)


class _StaticExpander:
    """Returns fixed graph context and records the chunks it was handed."""

    def __init__(self, context: list[GraphRelation]) -> None:
        self._context = context
        self.seen: list[list[RetrievalResult]] = []

    def expand(self, chunks: list[RetrievalResult]) -> list[GraphRelation]:
        self.seen.append(chunks)
        return list(self._context)


class GraphRetrieverTests(unittest.TestCase):
    def test_composes_semantic_hits_and_graph_context(self) -> None:
        chunks = [_chunk("ZTNA", 5)]
        context = [GraphRelation("ZTNA", "protects", "Network", 2)]
        semantic = _FakeSemantic(chunks)
        expander = _StaticExpander(context)
        result = GraphRetriever(semantic, expander).retrieve("how do they relate?", k=3)
        self.assertIsInstance(result, ExpandedRetrievalResult)
        self.assertEqual(result.chunks, chunks)
        self.assertEqual(result.graph_context, context)
        self.assertEqual(semantic.calls, [("how do they relate?", 3)])
        self.assertEqual(expander.seen, [chunks])  # expander saw the retrieved chunks

    def test_default_k_is_forwarded(self) -> None:
        semantic = _FakeSemantic([])
        GraphRetriever(semantic, _StaticExpander([])).retrieve("q")
        self.assertEqual(semantic.calls[0][1], DEFAULT_TOP_K)

    def test_no_hits_yields_empty_expansion(self) -> None:
        semantic = _FakeSemantic([])
        expander = _StaticExpander([])
        result = GraphRetriever(semantic, expander).retrieve("q")
        self.assertEqual(result.chunks, [])
        self.assertEqual(result.graph_context, [])


if __name__ == "__main__":
    unittest.main()
