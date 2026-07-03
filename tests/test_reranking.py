"""Behaviour tests for the reranker (T3.2)."""

import unittest

from aipos.reranking import LexicalReranker, Reranker
from aipos.retrieval import RetrievalResult


def _result(chunk_id: int, text: str, score: float) -> RetrievalResult:
    return RetrievalResult(chunk_id=chunk_id, text=text, score=score)


class LexicalRerankerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reranker = LexicalReranker()

    def test_conforms_to_protocol(self) -> None:
        self.assertIsInstance(self.reranker, Reranker)

    def test_reorders_by_query_term_coverage(self) -> None:
        # Incoming (vector) order is deliberately not the coverage order.
        # Coverage = number of DISTINCT query terms present in the text.
        results = [
            _result(2, "an unrelated cooking recipe", 0.10),          # covers 0
            _result(1, "notes about the database", 0.20),             # covers 1: database
            _result(4, "query optimizer internals", 0.30),            # covers 2: query, optimizer
            _result(3, "the query optimizer tunes each database", 0.40),  # covers 3
        ]
        reranked = self.reranker.rerank("database query optimizer", results)
        self.assertEqual([r.chunk_id for r in reranked], [3, 4, 1, 2])
        # differs from the incoming vector order (Build Plan T3.2 done-definition)
        self.assertNotEqual(
            [r.chunk_id for r in reranked], [r.chunk_id for r in results]
        )

    def test_preserves_scores_and_objects(self) -> None:
        results = [_result(1, "alpha", 0.2), _result(2, "beta query", 0.7)]
        reranked = self.reranker.rerank("query", results)
        self.assertEqual({r.chunk_id: r.score for r in reranked}, {1: 0.2, 2: 0.7})
        # same objects, just reordered (reordering, not rescoring)
        self.assertCountEqual([id(r) for r in reranked], [id(r) for r in results])

    def test_ties_preserve_incoming_order(self) -> None:
        # None of these contain the query term -> all overlap 0 -> stable order.
        results = [_result(1, "aaa", 0.1), _result(2, "bbb", 0.2), _result(3, "ccc", 0.3)]
        reranked = self.reranker.rerank("zzz", results)
        self.assertEqual([r.chunk_id for r in reranked], [1, 2, 3])

    def test_equal_overlap_keeps_vector_order(self) -> None:
        # Both cover the single query term equally -> keep incoming order.
        results = [_result(5, "query one", 0.1), _result(6, "query two", 0.2)]
        reranked = self.reranker.rerank("query", results)
        self.assertEqual([r.chunk_id for r in reranked], [5, 6])

    def test_blank_query_keeps_order(self) -> None:
        results = [_result(1, "a", 0.1), _result(2, "b", 0.2)]
        self.assertEqual(
            [r.chunk_id for r in self.reranker.rerank("   ", results)], [1, 2]
        )

    def test_empty_results_returns_empty(self) -> None:
        self.assertEqual(self.reranker.rerank("anything", []), [])

    def test_does_not_mutate_input_list(self) -> None:
        results = [_result(1, "cold weather", 0.1), _result(2, "hot query", 0.2)]
        original_order = list(results)
        self.reranker.rerank("query", results)
        self.assertEqual(results, original_order)  # input list untouched

    def test_is_case_insensitive(self) -> None:
        results = [_result(1, "no match here", 0.1), _result(2, "DataBase QUERY", 0.2)]
        reranked = self.reranker.rerank("database query", results)
        self.assertEqual(reranked[0].chunk_id, 2)

    def test_is_deterministic(self) -> None:
        results = [_result(1, "query a", 0.1), _result(2, "query b query", 0.2)]
        first = self.reranker.rerank("query", results)
        second = self.reranker.rerank("query", results)
        self.assertEqual([r.chunk_id for r in first], [r.chunk_id for r in second])


if __name__ == "__main__":
    unittest.main()
