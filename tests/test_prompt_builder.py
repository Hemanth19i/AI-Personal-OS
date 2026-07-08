"""Behaviour tests for grounded prompt construction (T3.3)."""

import unittest

from aipos.prompt_builder import USED_CHUNKS_HEADER, build_prompt
from aipos.retrieval import RetrievalResult
from aipos.storage import GraphRelation


def _result(chunk_id: int, text: str) -> RetrievalResult:
    return RetrievalResult(chunk_id=chunk_id, text=text, score=0.0)


class BuildPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.chunks = [_result(10, "alpha fact"), _result(20, "beta fact")]

    def test_numbers_chunks_from_one(self) -> None:
        prompt = build_prompt("q?", self.chunks)
        self.assertIn("[1] alpha fact", prompt)
        self.assertIn("[2] beta fact", prompt)

    def test_includes_grounding_instructions(self) -> None:
        prompt = build_prompt("q?", self.chunks).lower()
        self.assertIn("only", prompt)
        self.assertIn("never use outside knowledge", prompt)
        self.assertIn("don't know", prompt)

    def test_includes_used_chunks_contract(self) -> None:
        prompt = build_prompt("q?", self.chunks)
        self.assertIn(USED_CHUNKS_HEADER, prompt)
        self.assertIn("NONE", prompt)

    def test_includes_the_question(self) -> None:
        self.assertIn("What is alpha?", build_prompt("What is alpha?", self.chunks))

    def test_is_deterministic(self) -> None:
        self.assertEqual(
            build_prompt("q?", self.chunks), build_prompt("q?", self.chunks)
        )

    def test_empty_chunks_still_builds(self) -> None:
        prompt = build_prompt("q?", [])
        self.assertIn("(no context)", prompt)
        self.assertIn(USED_CHUNKS_HEADER, prompt)

    # --- graph context (T4.3) ---

    def test_no_graph_context_is_backward_compatible(self) -> None:
        # Absent or empty graph context yields the exact pre-T4.3 prompt.
        base = build_prompt("q?", self.chunks)
        self.assertEqual(build_prompt("q?", self.chunks, None), base)
        self.assertEqual(build_prompt("q?", self.chunks, []), base)

    def test_graph_context_renders_relationship_facts(self) -> None:
        gc = [
            GraphRelation("ZTNA", "protects", "Network", 3),
            GraphRelation("Alice", "mentions", "ZTNA", 1),
        ]
        prompt = build_prompt("q?", self.chunks, gc)
        self.assertIn("- ZTNA protects Network", prompt)
        self.assertIn("- Alice mentions ZTNA", prompt)

    def test_graph_lines_are_not_numbered_citation_chunks(self) -> None:
        # Graph facts are bullets, keeping the numbered citation space to chunks.
        gc = [GraphRelation("ZTNA", "protects", "Network", 3)]
        prompt = build_prompt("q?", self.chunks, gc)
        self.assertIn("[1] alpha fact", prompt)  # chunks still numbered
        self.assertNotIn("[3] ZTNA", prompt)  # graph fact is not a numbered chunk


if __name__ == "__main__":
    unittest.main()
