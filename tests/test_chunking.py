"""Behaviour tests for text chunking."""

import unittest

from aipos.chunking import Chunk, chunk_text


class ChunkTextTests(unittest.TestCase):
    def test_small_text_is_single_chunk(self) -> None:
        chunks = chunk_text("hello world", chunk_size=100, overlap=10)
        self.assertEqual(chunks, [Chunk(index=0, text="hello world")])

    def test_large_text_splits_into_multiple_chunks(self) -> None:
        text = "abcdefghij" * 10  # 100 chars
        chunks = chunk_text(text, chunk_size=30, overlap=5)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c.text) <= 30 for c in chunks))
        # every chunk is non-empty
        self.assertTrue(all(c.text for c in chunks))

    def test_overlap_is_shared_between_consecutive_chunks(self) -> None:
        text = "".join(str(i % 10) for i in range(100))
        size, overlap = 30, 10
        chunks = chunk_text(text, chunk_size=size, overlap=overlap)
        step = size - overlap
        for first, second in zip(chunks, chunks[1:]):
            self.assertEqual(first.text[step:], second.text[: size - step])

    def test_ordering_is_preserved(self) -> None:
        text = "x" * 250
        chunks = chunk_text(text, chunk_size=50, overlap=10)
        self.assertEqual([c.index for c in chunks], list(range(len(chunks))))

    def test_reconstructs_document_by_advancing_step(self) -> None:
        text = "The quick brown fox. " * 20
        size, overlap = 40, 8
        chunks = chunk_text(text, chunk_size=size, overlap=overlap)
        step = size - overlap
        rebuilt = "".join(c.text[:step] for c in chunks[:-1]) + chunks[-1].text
        self.assertEqual(rebuilt, text)

    def test_deterministic_output(self) -> None:
        text = "deterministic " * 50
        self.assertEqual(
            chunk_text(text, chunk_size=64, overlap=16),
            chunk_text(text, chunk_size=64, overlap=16),
        )

    def test_empty_input_returns_no_chunks(self) -> None:
        self.assertEqual(chunk_text(""), [])
        self.assertEqual(chunk_text("   \n\t  "), [])

    def test_whitespace_is_preserved_within_a_chunk(self) -> None:
        text = "line1\n\n  indented\ttabbed  \ntrailing   "
        chunks = chunk_text(text, chunk_size=1000, overlap=100)
        self.assertEqual(chunks, [Chunk(index=0, text=text)])

    def test_invalid_parameters_raise(self) -> None:
        with self.assertRaises(ValueError):
            chunk_text("data", chunk_size=0)
        with self.assertRaises(ValueError):
            chunk_text("data", chunk_size=10, overlap=10)
        with self.assertRaises(ValueError):
            chunk_text("data", chunk_size=10, overlap=-1)


if __name__ == "__main__":
    unittest.main()
