"""Behaviour tests for the embedding module.

Ollama is not available in this environment, so the determinism/distinctness
properties (which the real nomic-embed backend also satisfies) are verified
against a hermetic reference embedder; OllamaEmbedder is checked only for
protocol conformance, not for live embedding.
"""

import unittest

from aipos.embedding import Embedder, OllamaEmbedder
from tests.embedder_fakes import DeterministicEmbedder


class EmbedderContractTests(unittest.TestCase):
    def test_ollama_embedder_satisfies_protocol(self) -> None:
        self.assertIsInstance(OllamaEmbedder("nomic-embed-text"), Embedder)

    def test_reference_embedder_satisfies_protocol(self) -> None:
        self.assertIsInstance(DeterministicEmbedder(), Embedder)

    def test_identical_text_is_deterministic(self) -> None:
        first, second = DeterministicEmbedder().embed(["same text", "same text"])
        self.assertEqual(first, second)

    def test_different_text_produces_different_embeddings(self) -> None:
        alpha, beta = DeterministicEmbedder().embed(["alpha", "beta"])
        self.assertNotEqual(alpha, beta)

    def test_returns_one_vector_per_text_in_order(self) -> None:
        embedder = DeterministicEmbedder()
        vectors = embedder.embed(["a", "b", "c"])
        self.assertEqual(len(vectors), 3)
        self.assertEqual(
            vectors,
            [embedder.embed(["a"])[0], embedder.embed(["b"])[0], embedder.embed(["c"])[0]],
        )


if __name__ == "__main__":
    unittest.main()
