"""Behaviour tests for grounded prompt construction (T3.3)."""

import unittest

from aipos.prompt_builder import USED_CHUNKS_HEADER, build_prompt
from aipos.retrieval import RetrievalResult


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


if __name__ == "__main__":
    unittest.main()
