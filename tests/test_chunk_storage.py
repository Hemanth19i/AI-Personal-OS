"""Behaviour tests for chunk persistence in SQLiteStorage."""

import tempfile
import unittest
from pathlib import Path

from aipos.chunking import Chunk
from aipos.storage import SQLiteStorage


class ChunkStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self._tmp.name) / "aipos.db")
        self.storage.connect()
        self.file_id = self.storage.add_file(path="/doc.pdf", file_hash="h")

    def tearDown(self) -> None:
        self.storage.close()
        self._tmp.cleanup()

    def test_chunks_are_inserted_and_retrieved(self) -> None:
        chunks = [Chunk(0, "alpha"), Chunk(1, "beta")]
        self.storage.add_chunks(self.file_id, chunks)
        self.assertEqual(self.storage.get_chunks(self.file_id), chunks)

    def test_ordering_is_preserved_regardless_of_insert_order(self) -> None:
        self.storage.add_chunks(self.file_id, [Chunk(2, "c"), Chunk(0, "a"), Chunk(1, "b")])
        retrieved = self.storage.get_chunks(self.file_id)
        self.assertEqual([c.index for c in retrieved], [0, 1, 2])
        self.assertEqual([c.text for c in retrieved], ["a", "b", "c"])

    def test_retrieval_is_scoped_to_the_file(self) -> None:
        other_id = self.storage.add_file(path="/other.pdf", file_hash="h2")
        self.storage.add_chunks(self.file_id, [Chunk(0, "mine")])
        self.storage.add_chunks(other_id, [Chunk(0, "theirs")])
        self.assertEqual(self.storage.get_chunks(self.file_id), [Chunk(0, "mine")])
        self.assertEqual(self.storage.get_chunks(other_id), [Chunk(0, "theirs")])

    def test_persisting_twice_appends_duplicates(self) -> None:
        # Storage does not dedupe chunks; file-level dedup prevents re-processing.
        self.storage.add_chunks(self.file_id, [Chunk(0, "x")])
        self.storage.add_chunks(self.file_id, [Chunk(0, "x")])
        self.assertEqual(len(self.storage.get_chunks(self.file_id)), 2)

    def test_empty_chunk_list_persists_nothing(self) -> None:
        self.storage.add_chunks(self.file_id, [])
        self.assertEqual(self.storage.get_chunks(self.file_id), [])

    def test_get_chunks_for_unknown_file_is_empty(self) -> None:
        self.assertEqual(self.storage.get_chunks(9999), [])

    # --- get_chunks_by_ids (retrieval hydration, T3.1) ---

    def test_get_chunks_by_ids_returns_matching_records(self) -> None:
        self.storage.add_chunks(self.file_id, [Chunk(0, "a"), Chunk(1, "b"), Chunk(2, "c")])
        stored = self.storage.get_chunk_records(self.file_id)
        wanted = [stored[2].id, stored[0].id]
        got = {r.id: r.text for r in self.storage.get_chunks_by_ids(wanted)}
        self.assertEqual(got, {stored[2].id: "c", stored[0].id: "a"})

    def test_get_chunks_by_ids_omits_unknown_ids(self) -> None:
        self.storage.add_chunks(self.file_id, [Chunk(0, "only")])
        stored = self.storage.get_chunk_records(self.file_id)
        got = self.storage.get_chunks_by_ids([stored[0].id, 999999])
        self.assertEqual([r.id for r in got], [stored[0].id])

    def test_get_chunks_by_ids_empty_list_returns_empty(self) -> None:
        self.storage.add_chunks(self.file_id, [Chunk(0, "x")])
        self.assertEqual(self.storage.get_chunks_by_ids([]), [])


if __name__ == "__main__":
    unittest.main()
