"""Behaviour tests for answer generation (T3.3).

Exercised through the real DI surface: a fake retriever + passthrough reranker +
FakeLLM + a real temp SQLiteStorage (so citation file lookup runs for real). No
Ollama, no LanceDB.
"""

import tempfile
import unittest
from pathlib import Path

from aipos.answering import AnswerService, Source
from aipos.chunking import Chunk
from aipos.retrieval import RetrievalResult
from aipos.storage import SQLiteStorage
from tests.llm_fakes import FailingLLM, FakeLLM


class _FakeRetriever:
    """Returns canned results and records the (question, k) it was asked."""

    def __init__(self, results: list[RetrievalResult]) -> None:
        self._results = results
        self.calls: list[tuple[str, int]] = []

    def retrieve(self, query: str, *, k: int) -> list[RetrievalResult]:
        self.calls.append((query, k))
        return list(self._results)


class _PassthroughReranker:
    """Returns candidates unchanged, so citation positions are predictable."""

    def rerank(self, query: str, results: list[RetrievalResult]) -> list[RetrievalResult]:
        return list(results)


class AnswerServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self._tmp.name) / "aipos.db")
        self.storage.connect()
        self.file_id = self.storage.add_file(path="/docs/a.pdf", file_hash="h")
        self.storage.add_chunks(
            self.file_id, [Chunk(0, "alpha text"), Chunk(1, "beta text"), Chunk(2, "gamma text")]
        )
        self.records = self.storage.get_chunk_records(self.file_id)
        self.results = [
            RetrievalResult(chunk_id=r.id, text=r.text, score=0.1 * i)
            for i, r in enumerate(self.records)
        ]
        self.reranker = _PassthroughReranker()

    def tearDown(self) -> None:
        self.storage.close()
        self._tmp.cleanup()

    def _service(self, llm, results=None) -> AnswerService:
        retriever = _FakeRetriever(results if results is not None else self.results)
        self._retriever = retriever
        return AnswerService(retriever, self.reranker, llm, self.storage)

    def test_grounded_answer_with_cited_sources(self) -> None:
        llm = FakeLLM("The answer is alpha and gamma.\nUSED_CHUNKS:\n1,3")
        result = self._service(llm).answer("what?")
        self.assertTrue(result.grounded)
        self.assertEqual(result.answer, "The answer is alpha and gamma.")  # footer stripped
        self.assertEqual([s.chunk_id for s in result.sources], [self.records[0].id, self.records[2].id])
        self.assertTrue(all(s.file == "/docs/a.pdf" for s in result.sources))
        self.assertIsInstance(result.sources[0], Source)
        self.assertIn("alpha text", result.sources[0].snippet)

    def test_none_footer_is_not_grounded(self) -> None:
        llm = FakeLLM("I don't know.\nUSED_CHUNKS:\nNONE")
        result = self._service(llm).answer("what?")
        self.assertFalse(result.grounded)
        self.assertEqual(result.sources, [])
        self.assertEqual(result.answer, "I don't know.")

    def test_missing_footer_is_not_grounded(self) -> None:
        llm = FakeLLM("A confident answer with no footer at all.")
        result = self._service(llm).answer("what?")
        self.assertFalse(result.grounded)
        self.assertEqual(result.sources, [])
        self.assertEqual(result.answer, "A confident answer with no footer at all.")

    def test_out_of_range_footer_is_not_grounded(self) -> None:
        llm = FakeLLM("Answer.\nUSED_CHUNKS:\n9,42")  # only 3 chunks exist
        result = self._service(llm).answer("what?")
        self.assertFalse(result.grounded)
        self.assertEqual(result.sources, [])

    def test_empty_retrieval_short_circuits_without_llm(self) -> None:
        llm = FakeLLM("should never be called")
        result = self._service(llm, results=[]).answer("what?")
        self.assertFalse(result.grounded)
        self.assertEqual(result.sources, [])
        self.assertEqual(llm.prompts, [])  # LLM was never consulted

    def test_prompt_contains_context_and_grounding(self) -> None:
        llm = FakeLLM("x\nUSED_CHUNKS:\n1")
        self._service(llm).answer("what is alpha?")
        prompt = llm.prompts[0]
        self.assertIn("alpha text", prompt)
        self.assertIn("what is alpha?", prompt)
        self.assertIn("USED_CHUNKS:", prompt)

    def test_duplicate_and_reordered_citations_dedupe_in_cited_order(self) -> None:
        llm = FakeLLM("Answer.\nUSED_CHUNKS:\n3,1,3")
        result = self._service(llm).answer("what?")
        self.assertEqual([s.chunk_id for s in result.sources], [self.records[2].id, self.records[0].id])

    def test_llm_failure_propagates(self) -> None:
        with self.assertRaises(RuntimeError):
            self._service(FailingLLM()).answer("what?")

    def test_answering_mutates_nothing(self) -> None:
        before = len(self.storage.get_chunk_records(self.file_id))
        self._service(FakeLLM("a\nUSED_CHUNKS:\n1")).answer("what?")
        self.assertEqual(len(self.storage.get_chunk_records(self.file_id)), before)

    def test_k_is_forwarded_to_retriever(self) -> None:
        service = self._service(FakeLLM("a\nUSED_CHUNKS:\n1"))
        service.answer("what?", k=7)
        self.assertEqual(self._retriever.calls[0][1], 7)


if __name__ == "__main__":
    unittest.main()
