"""Behaviour tests for the heuristic intent router (T4.4)."""

import unittest

from aipos.intent import HeuristicIntentRouter, IntentRouter, RoutingDecision, Strategy


class HeuristicIntentRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = HeuristicIntentRouter()

    def _strategy(self, query: str) -> Strategy:
        return self.router.route(query).strategy

    def test_satisfies_protocol(self) -> None:
        self.assertIsInstance(self.router, IntentRouter)

    def test_returns_routing_decision_with_nonempty_reason(self) -> None:
        decision = self.router.route("How is A related to B?")
        self.assertIsInstance(decision, RoutingDecision)
        self.assertIs(decision.strategy, Strategy.GRAPH)
        self.assertTrue(decision.reason)

    # --- the four canonical examples from the ticket ---

    def test_who_created_is_semantic(self) -> None:
        self.assertIs(self._strategy("Who created Kubernetes?"), Strategy.SEMANTIC)

    def test_summarize_is_semantic(self) -> None:
        self.assertIs(self._strategy("Summarize Zero Trust."), Strategy.SEMANTIC)

    def test_related_to_is_graph(self) -> None:
        self.assertIs(
            self._strategy("How is Keycloak related to OAuth?"), Strategy.GRAPH
        )

    def test_relationship_between_is_graph(self) -> None:
        self.assertIs(
            self._strategy(
                "Explain the relationship between ZTNA, Keycloak and OAuth."
            ),
            Strategy.GRAPH,
        )

    # --- heuristic coverage ---

    def test_relationship_keywords_route_to_graph(self) -> None:
        for query in [
            "How does A connect to B?",
            "Compare A and B",
            "A versus B",
            "What is the difference between A and B?",
            "How are A and B linked?",
        ]:
            self.assertIs(self._strategy(query), Strategy.GRAPH, query)

    def test_factual_leads_route_to_semantic(self) -> None:
        for query in [
            "What is OAuth?",
            "Define zero trust",
            "When was Kubernetes released?",
            "List the pillars of ZTNA",
        ]:
            self.assertIs(self._strategy(query), Strategy.SEMANTIC, query)

    def test_short_keyword_query_is_semantic(self) -> None:
        self.assertIs(self._strategy("Kubernetes creator"), Strategy.SEMANTIC)

    def test_ambiguous_long_query_defaults_to_graph(self) -> None:
        query = "Tell me everything about the security posture of the platform design"
        self.assertIs(self._strategy(query), Strategy.GRAPH)

    def test_relationship_keyword_outranks_factual_lead(self) -> None:
        # Starts with a factual lead ("what") but asks about a relationship.
        self.assertIs(
            self._strategy("What is the relationship between A and B?"), Strategy.GRAPH
        )

    def test_matching_is_case_insensitive(self) -> None:
        self.assertIs(self._strategy("HOW IS A RELATED TO B"), Strategy.GRAPH)

    def test_whole_word_matching_avoids_substring_false_positive(self) -> None:
        # "correlated" contains "related" as a substring but is not the keyword,
        # so this stays on the cheap semantic path (short query).
        self.assertIs(self._strategy("correlated failures"), Strategy.SEMANTIC)

    def test_empty_query_is_semantic(self) -> None:
        self.assertIs(self._strategy("   "), Strategy.SEMANTIC)

    def test_reason_names_the_relationship_keyword(self) -> None:
        decision = self.router.route("How does A connect to B?")
        self.assertIn("connect", decision.reason)


if __name__ == "__main__":
    unittest.main()
