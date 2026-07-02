"""Behaviour tests for LanceDB vector persistence.

These use a real LanceVectorStore against a temp directory and verify by reading
the underlying LanceDB table directly (the store itself is persistence-only and
exposes no read/query API).
"""

import tempfile
import unittest
from pathlib import Path

import lancedb

from aipos.vector_store import VECTOR_STORE_DIRNAME, LanceVectorStore


def _stored_rows(root: Path) -> dict[int, list[float]]:
    """Read persisted (chunk_id -> vector) rows straight from LanceDB."""
    database = lancedb.connect(str(root / VECTOR_STORE_DIRNAME))
    listing = database.list_tables()
    if "chunk_vectors" not in getattr(listing, "tables", listing):
        return {}
    rows = database.open_table("chunk_vectors").to_arrow().to_pylist()
    return {row["chunk_id"]: [round(x, 4) for x in row["vector"]] for row in rows}


class LanceVectorStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / VECTOR_STORE_DIRNAME
        self.store = LanceVectorStore(self.path)
        self.store.connect()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_vectors_persist_keyed_by_chunk_id(self) -> None:
        self.store.add([(1, [0.1, 0.2]), (2, [0.3, 0.4])])
        self.assertEqual(_stored_rows(self.root), {1: [0.1, 0.2], 2: [0.3, 0.4]})

    def test_vectors_reload_after_reopening(self) -> None:
        self.store.add([(7, [0.5, 0.6])])
        reopened = LanceVectorStore(self.path)
        reopened.connect()
        reopened.add([(8, [0.7, 0.8])])
        self.assertEqual(_stored_rows(self.root), {7: [0.5, 0.6], 8: [0.7, 0.8]})

    def test_empty_batch_persists_nothing(self) -> None:
        self.store.add([])
        self.assertEqual(_stored_rows(self.root), {})

    def test_duplicate_chunk_id_appends(self) -> None:
        # No upsert: re-adding a chunk_id appends a row (file-level dedup upstream
        # prevents re-persistence in practice — consistent with add_chunks).
        self.store.add([(1, [0.1, 0.2])])
        self.store.add([(1, [0.1, 0.2])])
        rows = lancedb.connect(str(self.path)).open_table("chunk_vectors").count_rows()
        self.assertEqual(rows, 2)

    def test_add_before_connect_raises(self) -> None:
        disconnected = LanceVectorStore(self.root / "other")
        with self.assertRaises(RuntimeError):
            disconnected.add([(1, [0.1])])


if __name__ == "__main__":
    unittest.main()
