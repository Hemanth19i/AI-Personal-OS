"""Behaviour tests for the SQLite storage layer."""

import tempfile
import time
import unittest
from pathlib import Path

from aipos.storage import DEFAULT_WORKSPACE_ID, FileStatus, SQLiteStorage


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

    def test_filestatus_vocabulary_matches_design(self) -> None:
        self.assertEqual(
            [s.value for s in FileStatus],
            [
                "pending", "parsing", "ocr", "chunking", "embedding",
                "extracting", "verifying", "ready", "failed",
            ],
        )

    def test_status_defaults_to_pending_enum(self) -> None:
        record = self.storage.get_file(self.storage.add_file(path="/a", file_hash="h"))
        self.assertIs(record.status, FileStatus.PENDING)
        self.assertIsInstance(record.status, FileStatus)

    def test_update_status_moves_through_lifecycle(self) -> None:
        file_id = self.storage.add_file(path="/a", file_hash="h")
        for status in (FileStatus.PARSING, FileStatus.CHUNKING, FileStatus.READY):
            self.storage.update_status(file_id, status)
            self.assertIs(self.storage.get_file(file_id).status, status)

    def test_update_status_records_error(self) -> None:
        file_id = self.storage.add_file(path="/a", file_hash="h")
        self.storage.update_status(file_id, FileStatus.FAILED, error="boom")
        record = self.storage.get_file(file_id)
        self.assertIs(record.status, FileStatus.FAILED)
        self.assertEqual(record.error, "boom")

    def test_update_status_clears_error_on_recovery(self) -> None:
        file_id = self.storage.add_file(path="/a", file_hash="h")
        self.storage.update_status(file_id, FileStatus.FAILED, error="boom")
        self.storage.update_status(file_id, FileStatus.PARSING)
        self.assertIsNone(self.storage.get_file(file_id).error)

    def test_update_status_refreshes_updated_at(self) -> None:
        file_id = self.storage.add_file(path="/a", file_hash="h")
        before = self.storage.get_file(file_id).updated_at
        time.sleep(1.1)  # CURRENT_TIMESTAMP has 1-second resolution
        self.storage.update_status(file_id, FileStatus.PARSING)
        after = self.storage.get_file(file_id).updated_at
        self.assertGreater(after, before)


if __name__ == "__main__":
    unittest.main()
