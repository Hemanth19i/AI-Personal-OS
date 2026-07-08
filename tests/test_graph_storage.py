"""Behaviour tests for knowledge-graph persistence in SQLiteStorage (T4.2)."""

import tempfile
import unittest
from pathlib import Path

from aipos.extraction import Entity, Relationship
from aipos.storage import DEFAULT_WORKSPACE_ID, EdgeRecord, EntityRecord, SQLiteStorage


class GraphStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self._tmp.name) / "aipos.db")
        self.storage.connect()

    def tearDown(self) -> None:
        self.storage.close()
        self._tmp.cleanup()

    def _entity_count(self, workspace_id: str = DEFAULT_WORKSPACE_ID) -> int:
        return self.storage._require_connection().execute(
            "SELECT count(*) FROM entities WHERE workspace_id = ?", (workspace_id,)
        ).fetchone()[0]

    # --- entity persistence & identity ---

    def test_entity_is_persisted_and_found_by_name(self) -> None:
        self.storage.add_graph([Entity("Alice", "person")], [])
        found = self.storage.get_entity_by_name("Alice")
        self.assertIsNotNone(found)
        self.assertEqual((found.name, found.type), ("Alice", "person"))

    def test_duplicate_entity_same_identity_is_deduped(self) -> None:
        self.storage.add_graph(
            [Entity("Alice", "person"), Entity("Alice", "person")], []
        )
        self.assertEqual(self._entity_count(), 1)

    def test_reingesting_same_entity_is_idempotent(self) -> None:
        self.storage.add_graph([Entity("Alice", "person")], [])
        first = self.storage.get_entity_by_name("Alice")
        self.storage.add_graph([Entity("Alice", "person")], [])
        second = self.storage.get_entity_by_name("Alice")
        self.assertEqual(self._entity_count(), 1)
        self.assertEqual(first.id, second.id)  # identity is stable across calls

    def test_same_name_different_type_are_distinct_entities(self) -> None:
        self.storage.add_graph(
            [Entity("Mercury", "planet"), Entity("Mercury", "element")], []
        )
        self.assertEqual(self._entity_count(), 2)

    def test_get_entity_by_name_prefers_lowest_id_when_ambiguous(self) -> None:
        self.storage.add_graph(
            [Entity("Mercury", "planet"), Entity("Mercury", "element")], []
        )
        found = self.storage.get_entity_by_name("Mercury")
        self.assertEqual(found.type, "planet")  # first inserted (lowest id)

    def test_get_entity_by_name_unknown_returns_none(self) -> None:
        self.assertIsNone(self.storage.get_entity_by_name("Nobody"))

    def test_entities_are_workspace_scoped(self) -> None:
        self.storage.add_graph([Entity("Alice", "person")], [], workspace_id="w2")
        self.assertIsNone(self.storage.get_entity_by_name("Alice"))  # default ws
        found = self.storage.get_entity_by_name("Alice", workspace_id="w2")
        self.assertIsNotNone(found)

    # --- edge persistence, id resolution & weight ---

    def test_edge_persisted_with_resolved_entity_ids(self) -> None:
        self.storage.add_graph(
            [Entity("Alice", "person"), Entity("ZTNA", "concept")],
            [Relationship("Alice", "ZTNA", "mentions")],
        )
        alice = self.storage.get_entity_by_name("Alice")
        ztna = self.storage.get_entity_by_name("ZTNA")
        edges = self.storage.get_edges()
        self.assertEqual(len(edges), 1)
        self.assertEqual(
            (edges[0].source_entity_id, edges[0].target_entity_id, edges[0].relation),
            (alice.id, ztna.id, "mentions"),
        )

    def test_edge_weight_counts_triple_occurrences(self) -> None:
        # The same triple extracted from three chunks -> one edge, weight 3.
        entities = [Entity("Alice", "person"), Entity("ZTNA", "concept")]
        triple = Relationship("Alice", "ZTNA", "mentions")
        self.storage.add_graph(entities, [triple, triple, triple])
        edges = self.storage.get_edges()
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].weight, 3)

    def test_identical_edge_across_files_is_one_row_with_summed_weight(self) -> None:
        # The same relationship extracted from three files (4 + 3 + 7 chunks)
        # collapses into ONE workspace edge whose weight is the total (14).
        entities = [Entity("ZTNA", "concept"), Entity("Network", "concept")]
        triple = Relationship("ZTNA", "Network", "protects")
        self.storage.add_graph(entities, [triple] * 4)  # file A
        self.storage.add_graph(entities, [triple] * 3)  # file B
        self.storage.add_graph(entities, [triple] * 7)  # file C
        edges = self.storage.get_edges()
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].weight, 14)

    def test_edge_upsert_keeps_a_stable_single_row(self) -> None:
        entities = [Entity("ZTNA", "concept"), Entity("Network", "concept")]
        triple = Relationship("ZTNA", "Network", "protects")
        self.storage.add_graph(entities, [triple])
        first = self.storage.get_edges()
        self.storage.add_graph(entities, [triple])
        second = self.storage.get_edges()
        self.assertEqual(len(second), 1)
        self.assertEqual(first[0].id, second[0].id)  # same row, updated in place
        self.assertEqual(second[0].weight, 2)

    def test_distinct_relations_between_same_pair_are_separate_edges(self) -> None:
        entities = [Entity("Alice", "person"), Entity("ZTNA", "concept")]
        self.storage.add_graph(
            entities,
            [Relationship("Alice", "ZTNA", "mentions"),
             Relationship("Alice", "ZTNA", "authored")],
        )
        relations = sorted(edge.relation for edge in self.storage.get_edges())
        self.assertEqual(relations, ["authored", "mentions"])

    def test_edge_with_unresolvable_endpoint_is_skipped(self) -> None:
        # "Ghost" was never persisted as an entity -> the edge is dropped.
        self.storage.add_graph(
            [Entity("Alice", "person")],
            [Relationship("Alice", "Ghost", "mentions")],
        )
        self.assertEqual(self.storage.get_edges(), [])

    def test_edge_with_both_endpoints_missing_is_skipped(self) -> None:
        self.storage.add_graph([], [Relationship("A", "B", "relates_to")])
        self.assertEqual(self.storage.get_edges(), [])

    def test_endpoint_resolution_prefers_lowest_id_for_ambiguous_name(self) -> None:
        self.storage.add_graph(
            [Entity("Mercury", "planet"), Entity("Mercury", "element"),
             Entity("Sun", "star")],
            [Relationship("Mercury", "Sun", "orbits")],
        )
        planet = self.storage.get_entity_by_name("Mercury")  # lowest id
        edge = self.storage.get_edges()[0]
        self.assertEqual(edge.source_entity_id, planet.id)

    # --- get_neighbors (the T4.2 done-when) ---

    def test_get_neighbors_returns_connected_entities_both_directions(self) -> None:
        self.storage.add_graph(
            [Entity("Alice", "person"), Entity("ZTNA", "concept")],
            [Relationship("Alice", "ZTNA", "mentions")],
        )
        alice = self.storage.get_entity_by_name("Alice")
        ztna = self.storage.get_entity_by_name("ZTNA")
        self.assertEqual(
            [n.id for n in self.storage.get_neighbors(alice.id)], [ztna.id]
        )
        self.assertEqual(
            [n.id for n in self.storage.get_neighbors(ztna.id)], [alice.id]
        )  # incoming edge also counts

    def test_get_neighbors_dedupes_multiple_edges_to_same_entity(self) -> None:
        self.storage.add_graph(
            [Entity("Alice", "person"), Entity("ZTNA", "concept")],
            [Relationship("Alice", "ZTNA", "mentions"),
             Relationship("Alice", "ZTNA", "authored")],
        )
        alice = self.storage.get_entity_by_name("Alice")
        neighbors = self.storage.get_neighbors(alice.id)
        self.assertEqual(len(neighbors), 1)  # ZTNA once, despite two edges

    def test_get_neighbors_of_isolated_entity_is_empty(self) -> None:
        self.storage.add_graph([Entity("Lonely", "concept")], [])
        lonely = self.storage.get_entity_by_name("Lonely")
        self.assertEqual(self.storage.get_neighbors(lonely.id), [])

    def test_get_neighbors_of_unknown_entity_is_empty(self) -> None:
        self.assertEqual(self.storage.get_neighbors(999999), [])

    def test_neighbors_are_workspace_scoped(self) -> None:
        self.storage.add_graph(
            [Entity("Alice", "person"), Entity("ZTNA", "concept")],
            [Relationship("Alice", "ZTNA", "mentions")],
            workspace_id="w2",
        )
        alice = self.storage.get_entity_by_name("Alice", workspace_id="w2")
        # Neighbours queried in the default workspace see no w2 edges.
        self.assertEqual(self.storage.get_neighbors(alice.id), [])
        self.assertEqual(
            len(self.storage.get_neighbors(alice.id, workspace_id="w2")), 1
        )

    # --- edge cases ---

    def test_add_graph_empty_is_a_noop(self) -> None:
        self.storage.add_graph([], [])
        self.assertEqual(self._entity_count(), 0)
        self.assertEqual(self.storage.get_edges(), [])

    def test_returned_records_have_expected_types(self) -> None:
        self.storage.add_graph(
            [Entity("Alice", "person"), Entity("ZTNA", "concept")],
            [Relationship("Alice", "ZTNA", "mentions")],
        )
        self.assertIsInstance(self.storage.get_entity_by_name("Alice"), EntityRecord)
        self.assertIsInstance(self.storage.get_edges()[0], EdgeRecord)

    # --- find_entities_in_text (T4.3) ---

    def test_find_entities_in_text_matches_whole_words_case_insensitively(self) -> None:
        self.storage.add_graph(
            [Entity("ZTNA", "concept"), Entity("Network", "concept")], []
        )
        found = {
            e.name
            for e in self.storage.find_entities_in_text(
                "The ztna design protects the Network layer"
            )
        }
        self.assertEqual(found, {"ZTNA", "Network"})

    def test_find_entities_in_text_avoids_substring_false_positives(self) -> None:
        self.storage.add_graph([Entity("AI", "concept")], [])
        self.assertEqual(self.storage.find_entities_in_text("a first aid kit"), [])

    def test_find_entities_in_text_blank_returns_empty(self) -> None:
        self.storage.add_graph([Entity("ZTNA", "concept")], [])
        self.assertEqual(self.storage.find_entities_in_text("   \n "), [])

    def test_find_entities_in_text_is_workspace_scoped(self) -> None:
        self.storage.add_graph([Entity("ZTNA", "concept")], [], workspace_id="w2")
        self.assertEqual(self.storage.find_entities_in_text("ZTNA"), [])
        self.assertTrue(self.storage.find_entities_in_text("ZTNA", workspace_id="w2"))

    # --- get_graph_context (T4.3) ---

    def test_get_graph_context_returns_named_triples_with_weight(self) -> None:
        self.storage.add_graph(
            [Entity("ZTNA", "concept"), Entity("Network", "concept")],
            [Relationship("ZTNA", "Network", "protects")],
        )
        ztna = self.storage.get_entity_by_name("ZTNA")
        ctx = self.storage.get_graph_context([ztna.id])
        self.assertEqual(len(ctx), 1)
        self.assertEqual(
            (ctx[0].source, ctx[0].relation, ctx[0].target, ctx[0].weight),
            ("ZTNA", "protects", "Network", 1),
        )

    def test_get_graph_context_includes_incoming_and_outgoing_edges(self) -> None:
        self.storage.add_graph(
            [Entity("A", "c"), Entity("B", "c"), Entity("C", "c")],
            [Relationship("A", "B", "x"), Relationship("C", "A", "y")],
        )
        a = self.storage.get_entity_by_name("A")
        triples = {
            (r.source, r.relation, r.target)
            for r in self.storage.get_graph_context([a.id])
        }
        self.assertEqual(triples, {("A", "x", "B"), ("C", "y", "A")})

    def test_get_graph_context_empty_ids_returns_empty(self) -> None:
        self.assertEqual(self.storage.get_graph_context([]), [])

    def test_get_graph_context_isolated_entity_returns_empty(self) -> None:
        self.storage.add_graph([Entity("Lonely", "concept")], [])
        lonely = self.storage.get_entity_by_name("Lonely")
        self.assertEqual(self.storage.get_graph_context([lonely.id]), [])

    def test_get_graph_context_is_workspace_scoped(self) -> None:
        self.storage.add_graph(
            [Entity("A", "c"), Entity("B", "c")],
            [Relationship("A", "B", "x")],
            workspace_id="w2",
        )
        a = self.storage.get_entity_by_name("A", workspace_id="w2")
        self.assertEqual(self.storage.get_graph_context([a.id]), [])  # default ws
        self.assertTrue(self.storage.get_graph_context([a.id], workspace_id="w2"))


if __name__ == "__main__":
    unittest.main()
