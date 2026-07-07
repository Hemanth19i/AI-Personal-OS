"""Unit tests for entity & relationship extraction (T4.1)."""

import unittest

from aipos.extraction import (
    Entity,
    EntityExtractor,
    ExtractionResult,
    LLMEntityExtractor,
    Relationship,
)
from tests.extractor_fakes import FailingExtractor, RecordingExtractor
from tests.llm_fakes import FailingLLM, FakeLLM


class ProtocolConformanceTests(unittest.TestCase):
    def test_llm_extractor_satisfies_protocol(self) -> None:
        extractor = LLMEntityExtractor(FakeLLM("{}"))
        self.assertIsInstance(extractor, EntityExtractor)

    def test_fakes_satisfy_protocol(self) -> None:
        # The test doubles must be substitutable wherever the protocol is used.
        self.assertIsInstance(RecordingExtractor(), EntityExtractor)
        self.assertIsInstance(FailingExtractor(), EntityExtractor)


class LLMEntityExtractorTests(unittest.TestCase):
    def _extract(self, response: str, text: str = "some text") -> ExtractionResult:
        return LLMEntityExtractor(FakeLLM(response)).extract(text)

    def test_parses_entities_and_relationships(self) -> None:
        response = (
            '{"entities": [{"name": "Alice", "type": "person"}, '
            '{"name": "ZTNA", "type": "concept"}], '
            '"relationships": [{"source": "Alice", "target": "ZTNA", '
            '"relation": "mentions"}]}'
        )
        result = self._extract(response)
        self.assertEqual(
            result.entities,
            [Entity("Alice", "person"), Entity("ZTNA", "concept")],
        )
        self.assertEqual(
            result.relationships,
            [Relationship("Alice", "ZTNA", "mentions")],
        )

    def test_extracts_json_embedded_in_prose_and_fences(self) -> None:
        # Local models often wrap JSON in commentary or ``` fences.
        response = (
            "Sure! Here is the graph:\n```json\n"
            '{"entities": [{"name": "Bob", "type": "person"}], '
            '"relationships": []}\n```\nHope that helps.'
        )
        result = self._extract(response)
        self.assertEqual(result.entities, [Entity("Bob", "person")])
        self.assertEqual(result.relationships, [])

    def test_missing_type_defaults_to_unknown(self) -> None:
        result = self._extract('{"entities": [{"name": "Carol"}], "relationships": []}')
        self.assertEqual(result.entities, [Entity("Carol", "unknown")])

    def test_names_and_types_are_trimmed(self) -> None:
        result = self._extract(
            '{"entities": [{"name": "  Dave  ", "type": " person "}], '
            '"relationships": []}'
        )
        self.assertEqual(result.entities, [Entity("Dave", "person")])

    def test_duplicate_entities_are_collapsed_preserving_order(self) -> None:
        response = (
            '{"entities": ['
            '{"name": "Alice", "type": "person"}, '
            '{"name": "ZTNA", "type": "concept"}, '
            '{"name": "Alice", "type": "person"}], '
            '"relationships": []}'
        )
        result = self._extract(response)
        self.assertEqual(
            result.entities,
            [Entity("Alice", "person"), Entity("ZTNA", "concept")],
        )

    def test_same_name_different_type_is_not_a_duplicate(self) -> None:
        response = (
            '{"entities": ['
            '{"name": "Mercury", "type": "planet"}, '
            '{"name": "Mercury", "type": "element"}], '
            '"relationships": []}'
        )
        result = self._extract(response)
        self.assertEqual(
            result.entities,
            [Entity("Mercury", "planet"), Entity("Mercury", "element")],
        )

    def test_duplicate_relationships_are_collapsed(self) -> None:
        response = (
            '{"entities": [], "relationships": ['
            '{"source": "A", "target": "B", "relation": "relates_to"}, '
            '{"source": "A", "target": "B", "relation": "relates_to"}]}'
        )
        result = self._extract(response)
        self.assertEqual(
            result.relationships, [Relationship("A", "B", "relates_to")]
        )

    def test_malformed_entities_are_skipped_not_fatal(self) -> None:
        # A non-dict entry, a nameless entry, and a non-string name are dropped;
        # the one valid entity survives.
        response = (
            '{"entities": ['
            '"not-an-object", '
            '{"type": "person"}, '
            '{"name": 123}, '
            '{"name": "Eve", "type": "person"}], '
            '"relationships": []}'
        )
        result = self._extract(response)
        self.assertEqual(result.entities, [Entity("Eve", "person")])

    def test_incomplete_relationships_are_skipped(self) -> None:
        response = (
            '{"entities": [], "relationships": ['
            '{"source": "A", "relation": "mentions"}, '
            '{"source": "A", "target": "B"}, '
            '{"source": "A", "target": "B", "relation": "mentions"}]}'
        )
        result = self._extract(response)
        self.assertEqual(
            result.relationships, [Relationship("A", "B", "mentions")]
        )

    def test_non_json_response_yields_empty_result(self) -> None:
        result = self._extract("I could not find any entities, sorry.")
        self.assertEqual(result, ExtractionResult([], []))

    def test_invalid_json_object_yields_empty_result(self) -> None:
        # Looks like JSON (has braces) but is not valid.
        result = self._extract('{"entities": [ {name: Alice} ] ')
        self.assertEqual(result, ExtractionResult([], []))

    def test_json_array_not_object_yields_empty_result(self) -> None:
        result = self._extract('[{"name": "Alice"}]')
        self.assertEqual(result, ExtractionResult([], []))

    def test_wrong_types_for_lists_yield_empty(self) -> None:
        result = self._extract('{"entities": "nope", "relationships": 5}')
        self.assertEqual(result, ExtractionResult([], []))

    def test_explicitly_empty_graph(self) -> None:
        result = self._extract('{"entities": [], "relationships": []}')
        self.assertEqual(result, ExtractionResult([], []))

    def test_blank_text_returns_empty_without_calling_llm(self) -> None:
        llm = FakeLLM('{"entities": [{"name": "X", "type": "y"}]}')
        result = LLMEntityExtractor(llm).extract("   \n\t ")
        self.assertEqual(result, ExtractionResult([], []))
        self.assertEqual(llm.prompts, [])  # LLM never consulted for empty input

    def test_prompt_includes_the_document_text(self) -> None:
        llm = FakeLLM('{"entities": [], "relationships": []}')
        LLMEntityExtractor(llm).extract("the quick brown fox")
        self.assertEqual(len(llm.prompts), 1)
        self.assertIn("the quick brown fox", llm.prompts[0])

    def test_backend_failure_propagates(self) -> None:
        # A backend outage surfaces to the coordinator (which records a file
        # failure) — unlike malformed output, which is swallowed.
        with self.assertRaises(RuntimeError):
            LLMEntityExtractor(FailingLLM()).extract("some text")


class FakeExtractorTests(unittest.TestCase):
    def test_recording_extractor_records_and_returns(self) -> None:
        result = ExtractionResult([Entity("A", "concept")], [])
        extractor = RecordingExtractor(result)
        returned = extractor.extract("hello")
        self.assertIs(returned, result)
        self.assertEqual(extractor.calls, ["hello"])

    def test_recording_extractor_defaults_to_empty(self) -> None:
        self.assertEqual(RecordingExtractor().extract("x"), ExtractionResult([], []))

    def test_failing_extractor_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            FailingExtractor().extract("x")


if __name__ == "__main__":
    unittest.main()
