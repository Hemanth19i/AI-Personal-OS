"""Behaviour tests for the SQLite storage layer."""

import tempfile
import unittest
from pathlib import Path

from aipos.storage import DEFAULT_WORKSPACE_ID, SQLiteStorage


class SQLiteStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "aipos.db"
        self.storage = SQLiteStorage(self.db_path)
        self.storage.connect()

    def tearDown(self) -> None:
        self.storage.close()
        self._tmp.cleanup()

    def test_insert_then_read_round_trip(self) -> None:
        file_id = self.storage.add_file(path="/docs/a.pdf", file_hash="abc123")
        record = self.storage.get_file(file_id)
        self.assertIsNotNone(record)
        self.assertEqual(record.id, file_id)
        self.assertEqual(record.path, "/docs/a.pdf")
        self.assertEqual(record.hash, "abc123")

    def test_defaults_on_insert(self) -> None:
        record = self.storage.get_file(
            self.storage.add_file(path="/docs/a.pdf", file_hash="abc123")
        )
        self.assertEqual(record.workspace_id, DEFAULT_WORKSPACE_ID)
        self.assertEqual(record.status, "pending")
        self.assertIsNone(record.error)
        self.assertTrue(record.created_at)
        self.assertTrue(record.updated_at)

    def test_get_missing_file_returns_none(self) -> None:
        self.assertIsNone(self.storage.get_file(999))

    def test_get_file_by_hash(self) -> None:
        self.storage.add_file(path="/docs/a.pdf", file_hash="deadbeef")
        found = self.storage.get_file_by_hash("deadbeef")
        self.assertIsNotNone(found)
        self.assertEqual(found.hash, "deadbeef")
        self.assertIsNone(self.storage.get_file_by_hash("unseen"))

    def test_data_persists_across_reconnect(self) -> None:
        file_id = self.storage.add_file(path="/docs/a.pdf", file_hash="abc123")
        self.storage.close()

        reopened = SQLiteStorage(self.db_path)
        reopened.connect()
        try:
            record = reopened.get_file(file_id)
            self.assertIsNotNone(record)
            self.assertEqual(record.path, "/docs/a.pdf")
        finally:
            reopened.close()

    def test_use_before_connect_raises(self) -> None:
        disconnected = SQLiteStorage(Path(self._tmp.name) / "other.db")
        with self.assertRaises(RuntimeError):
            disconnected.get_file(1)


if __name__ == "__main__":
    unittest.main()
