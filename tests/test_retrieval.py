"""Behaviour tests for semantic retrieval (T3.1).

Retrieval is exercised through its real dependency-injection surface: a real
temp SQLiteStorage seeded with chunks, a recording embedder, and a fake vector
store returning canned nearest-first hits. No Ollama or LanceDB required.
"""

import tempfile
import unittest
from pathlib import Path

from aipos.chunking import Chunk
from aipos.retrieval import DEFAULT_TOP_K, RetrievalResult, SemanticRetriever
from aipos.storage import SQLiteStorage
from tests.embedder_fakes import FailingEmbedder, RecordingEmbedder
from tests.vector_store_fakes import FailingVectorStore, RecordingVectorStore


class SemanticRetrieverTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self._tmp.name) / "aipos.db")
        self.storage.connect()
        self.file_id = self.storage.add_file(path="/doc.pdf", file_hash="h")
        self.storage.add_chunks(
            self.file_id, [Chunk(0, "alpha text"), Chunk(1, "beta text"), Chunk(2, "gamma text")]
        )
        self.records = self.storage.get_chunk_records(self.file_id)
        self.embedder = RecordingEmbedder()

    def tearDown(self) -> None:
        self.storage.close()
        self._tmp.cleanup()

    def _retriever(self, hits) -> SemanticRetriever:
        self.vectors = RecordingVectorStore(search_results=hits)
        return SemanticRetriever(self.embedder, self.vectors, self.storage)

    def test_returns_chunks_in_search_rank_order(self) -> None:
        ids = [r.id for r in self.records]
        # canned order: gamma (nearest), alpha, beta
        retriever = self._retriever([(ids[2], 0.1), (ids[0], 0.4), (ids[1], 0.9)])
        results = retriever.retrieve("query", k=3)
        self.assertEqual([r.chunk_id for r in results], [ids[2], ids[0], ids[1]])
        self.assertEqual([r.text for r in results], ["gamma text", "alpha text", "beta text"])
        self.assertEqual([r.score for r in results], [0.1, 0.4, 0.9])
        self.assertIsInstance(results[0], RetrievalResult)

    def test_query_is_embedded_exactly_once(self) -> None:
        retriever = self._retriever([(self.records[0].id, 0.2)])
        retriever.retrieve("what is alpha?")
        self.assertEqual(self.embedder.calls, [["what is alpha?"]])

    def test_k_is_propagated_to_search(self) -> None:
        retriever = self._retriever([(self.records[0].id, 0.2)])
        retriever.retrieve("query", k=2)
        self.assertEqual(self.vectors.searched[0][1], 2)

    def test_default_k_is_module_default(self) -> None:
        retriever = self._retriever([(self.records[0].id, 0.2)])
        retriever.retrieve("query")
        self.assertEqual(self.vectors.searched[0][1], DEFAULT_TOP_K)

    def test_empty_store_returns_empty(self) -> None:
        retriever = self._retriever([])  # no hits
        self.assertEqual(retriever.retrieve("query"), [])

    def test_blank_query_returns_empty_and_skips_backends(self) -> None:
        retriever = self._retriever([(self.records[0].id, 0.2)])
        self.assertEqual(retriever.retrieve("   "), [])
        self.assertEqual(self.embedder.calls, [])  # never embedded
        self.assertEqual(self.vectors.searched, [])  # never searched

    def test_unknown_chunk_id_is_skipped(self) -> None:
        retriever = self._retriever([(self.records[0].id, 0.2), (999999, 0.3)])
        results = retriever.retrieve("query", k=2)
        self.assertEqual([r.chunk_id for r in results], [self.records[0].id])

    def test_nonpositive_k_raises_before_embedding(self) -> None:
        retriever = self._retriever([(self.records[0].id, 0.2)])
        for bad in (0, -3):
            with self.assertRaises(ValueError):
                retriever.retrieve("query", k=bad)
        self.assertEqual(self.embedder.calls, [])  # failed fast, no work done

    def test_search_failure_propagates(self) -> None:
        retriever = SemanticRetriever(self.embedder, FailingVectorStore(), self.storage)
        with self.assertRaises(RuntimeError):
            retriever.retrieve("query")

    def test_embedding_failure_propagates(self) -> None:
        retriever = SemanticRetriever(FailingEmbedder(), RecordingVectorStore(), self.storage)
        with self.assertRaises(RuntimeError):
            retriever.retrieve("query")

    def test_retrieval_mutates_nothing(self) -> None:
        retriever = self._retriever([(self.records[0].id, 0.2)])
        before = len(self.storage.get_chunk_records(self.file_id))
        retriever.retrieve("query")
        after = len(self.storage.get_chunk_records(self.file_id))
        self.assertEqual(before, after)  # storage unchanged
        self.assertEqual(self.vectors.added, [])  # no writes to the vector store


if __name__ == "__main__":
    unittest.main()
