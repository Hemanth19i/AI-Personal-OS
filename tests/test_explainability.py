"""Behaviour tests for the Explanation model and Clock (T5.1)."""

import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

from aipos.explainability import Clock, Explanation, SystemClock


class SystemClockTests(unittest.TestCase):
    def test_satisfies_clock_protocol(self) -> None:
        self.assertIsInstance(SystemClock(), Clock)

    def test_now_is_timezone_aware_utc(self) -> None:
        now = SystemClock().now()
        self.assertIsNotNone(now.tzinfo)
        self.assertEqual(now.utcoffset(), timedelta(0))

    def test_now_isoformat_round_trips(self) -> None:
        stamp = SystemClock().now().isoformat()
        parsed = datetime.fromisoformat(stamp)
        self.assertIsNotNone(parsed.tzinfo)


class ExplanationTests(unittest.TestCase):
    def _make(self) -> Explanation:
        return Explanation(
            timestamp="2026-01-02T03:04:05+00:00",
            strategy="graph",
            reason="relationship keyword: 'related'",
            retrieved_count=5,
            graph_expanded=True,
            graph_relation_count=3,
            reranked_count=5,
            llm_consulted=True,
            grounded=True,
            citation_count=2,
        )

    def test_stores_fields_verbatim(self) -> None:
        exp = self._make()
        self.assertEqual(exp.strategy, "graph")
        self.assertEqual(exp.reason, "relationship keyword: 'related'")
        self.assertEqual(exp.retrieved_count, 5)
        self.assertTrue(exp.graph_expanded)
        self.assertEqual(exp.graph_relation_count, 3)
        self.assertEqual(exp.citation_count, 2)

    def test_is_immutable(self) -> None:
        exp = self._make()
        with self.assertRaises(FrozenInstanceError):
            exp.grounded = False  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
