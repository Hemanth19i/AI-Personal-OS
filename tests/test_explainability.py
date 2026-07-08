"""Behaviour tests for the Explanation model, Clock, and Confidence (T5.1/T5.2)."""

import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

from aipos.explainability import (
    Clock,
    Confidence,
    ConfidenceCalculator,
    Explanation,
    RuleBasedConfidenceCalculator,
    SystemClock,
)


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
            confidence=Confidence.HIGH,
        )

    def test_stores_fields_verbatim(self) -> None:
        exp = self._make()
        self.assertEqual(exp.strategy, "graph")
        self.assertEqual(exp.reason, "relationship keyword: 'related'")
        self.assertEqual(exp.retrieved_count, 5)
        self.assertTrue(exp.graph_expanded)
        self.assertEqual(exp.graph_relation_count, 3)
        self.assertEqual(exp.citation_count, 2)
        self.assertIs(exp.confidence, Confidence.HIGH)

    def test_is_immutable(self) -> None:
        exp = self._make()
        with self.assertRaises(FrozenInstanceError):
            exp.grounded = False  # type: ignore[misc]


class RuleBasedConfidenceCalculatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calc = RuleBasedConfidenceCalculator()

    def _assess(self, **overrides) -> Confidence:
        facts = dict(
            llm_consulted=True,
            grounded=True,
            citation_count=1,
            graph_relation_count=0,
            retrieved_count=3,
            reranked_count=3,
        )
        facts.update(overrides)
        return self.calc.assess(**facts)

    def test_satisfies_protocol(self) -> None:
        self.assertIsInstance(self.calc, ConfidenceCalculator)

    def test_enum_values(self) -> None:
        self.assertEqual(
            [Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW, Confidence.NONE],
            ["high", "medium", "low", "none"],
        )

    # --- the rule cascade (exact truth table) ---

    def test_llm_not_consulted_is_none(self) -> None:
        # NONE regardless of the other facts.
        self.assertIs(
            self._assess(llm_consulted=False, grounded=False, citation_count=0), Confidence.NONE
        )

    def test_not_grounded_is_low(self) -> None:
        self.assertIs(self._assess(grounded=False, citation_count=0), Confidence.LOW)

    def test_grounded_but_no_citation_is_low(self) -> None:
        self.assertIs(self._assess(grounded=True, citation_count=0), Confidence.LOW)

    def test_grounded_two_citations_with_graph_is_high(self) -> None:
        self.assertIs(
            self._assess(citation_count=2, graph_relation_count=1), Confidence.HIGH
        )

    def test_grounded_two_citations_without_graph_is_medium(self) -> None:
        # HIGH requires graph support; without it, several citations -> MEDIUM.
        self.assertIs(
            self._assess(citation_count=3, graph_relation_count=0), Confidence.MEDIUM
        )

    def test_grounded_single_citation_with_graph_is_medium(self) -> None:
        # HIGH requires >= 2 citations; a single citation stays MEDIUM.
        self.assertIs(
            self._assess(citation_count=1, graph_relation_count=5), Confidence.MEDIUM
        )

    def test_grounded_single_citation_no_graph_is_medium(self) -> None:
        self.assertIs(
            self._assess(citation_count=1, graph_relation_count=0), Confidence.MEDIUM
        )

    def test_is_deterministic(self) -> None:
        facts = dict(
            llm_consulted=True, grounded=True, citation_count=2,
            graph_relation_count=1, retrieved_count=5, reranked_count=5,
        )
        self.assertIs(self.calc.assess(**facts), self.calc.assess(**facts))

    def test_ignores_retrieved_and_reranked_counts_for_the_verdict(self) -> None:
        # The current rules do not branch on these; changing them must not move
        # the verdict off HIGH.
        base = dict(citation_count=2, graph_relation_count=1)
        self.assertIs(self._assess(**base, retrieved_count=2, reranked_count=2), Confidence.HIGH)
        self.assertIs(self._assess(**base, retrieved_count=99, reranked_count=99), Confidence.HIGH)


if __name__ == "__main__":
    unittest.main()
