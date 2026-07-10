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

    # --- get_in_progress_files (T6.1 crash recovery) ---

    def _file_at(self, status: FileStatus, *, path: str = "/a", file_hash: str | None = None) -> int:
        file_id = self.storage.add_file(path=path, file_hash=file_hash or f"h-{path}-{status}")
        self.storage.update_status(file_id, status)
        return file_id

    def test_returns_files_in_each_in_progress_status(self) -> None:
        ids = [
            self._file_at(status, path=f"/{status}.pdf")
            for status in (
                FileStatus.PARSING, FileStatus.OCR, FileStatus.CHUNKING,
                FileStatus.EMBEDDING, FileStatus.EXTRACTING, FileStatus.VERIFYING,
            )
        ]
        found = {r.id for r in self.storage.get_in_progress_files()}
        self.assertEqual(found, set(ids))

    def test_excludes_pending(self) -> None:
        self.storage.add_file(path="/a.txt", file_hash="h")  # defaults to pending
        self.assertEqual(self.storage.get_in_progress_files(), [])

    def test_excludes_ready(self) -> None:
        self._file_at(FileStatus.READY)
        self.assertEqual(self.storage.get_in_progress_files(), [])

    def test_excludes_failed(self) -> None:
        self._file_at(FileStatus.FAILED)
        self.assertEqual(self.storage.get_in_progress_files(), [])

    def test_mixed_statuses_returns_only_in_progress(self) -> None:
        pending = self.storage.add_file(path="/pending.txt", file_hash="p")
        in_progress = self._file_at(FileStatus.CHUNKING, path="/chunking.pdf")
        ready = self._file_at(FileStatus.READY, path="/ready.pdf")
        failed = self._file_at(FileStatus.FAILED, path="/failed.pdf")
        found = {r.id for r in self.storage.get_in_progress_files()}
        self.assertEqual(found, {in_progress})
        self.assertNotIn(pending, found)
        self.assertNotIn(ready, found)
        self.assertNotIn(failed, found)

    def test_workspace_isolation(self) -> None:
        connection = self.storage._require_connection()
        connection.execute(
            "INSERT INTO files (workspace_id, path, hash, status) VALUES (?, ?, ?, ?)",
            ("other", "/other.pdf", "h-other", FileStatus.CHUNKING),
        )
        connection.commit()
        self._file_at(FileStatus.CHUNKING, path="/mine.pdf")
        default_ws = self.storage.get_in_progress_files()
        other_ws = self.storage.get_in_progress_files(workspace_id="other")
        self.assertEqual([r.path for r in default_ws], ["/mine.pdf"])
        self.assertEqual([r.path for r in other_ws], ["/other.pdf"])

    def test_deterministic_ordering_by_id(self) -> None:
        first = self._file_at(FileStatus.CHUNKING, path="/1.pdf")
        second = self._file_at(FileStatus.EMBEDDING, path="/2.pdf")
        third = self._file_at(FileStatus.EXTRACTING, path="/3.pdf")
        self.assertEqual(
            [r.id for r in self.storage.get_in_progress_files()], [first, second, third]
        )

    def test_empty_when_no_files(self) -> None:
        self.assertEqual(self.storage.get_in_progress_files(), [])

    # --- list_files_by_status (T6.2, generic single-status query) ---

    def test_returns_files_at_the_given_status(self) -> None:
        pdf_id = self.storage.add_file(path="/a.pdf", file_hash="h1")
        txt_id = self.storage.add_file(path="/a.txt", file_hash="h2")  # also pending
        found = {r.id for r in self.storage.list_files_by_status(FileStatus.PENDING)}
        self.assertEqual(found, {pdf_id, txt_id})

    def test_is_generic_across_arbitrary_statuses(self) -> None:
        # Not special-cased to PENDING — works for any status value.
        for status in (
            FileStatus.CHUNKING, FileStatus.EMBEDDING, FileStatus.READY, FileStatus.FAILED,
        ):
            with self.subTest(status=status):
                file_id = self._file_at(status, path=f"/{status}.pdf")
                self.assertEqual(
                    [r.id for r in self.storage.list_files_by_status(status)], [file_id]
                )

    def test_excludes_other_statuses(self) -> None:
        pending = self.storage.add_file(path="/pending.pdf", file_hash="p")
        self._file_at(FileStatus.CHUNKING, path="/chunking.pdf")
        self._file_at(FileStatus.READY, path="/ready.pdf")
        self._file_at(FileStatus.FAILED, path="/failed.pdf")
        found = {r.id for r in self.storage.list_files_by_status(FileStatus.PENDING)}
        self.assertEqual(found, {pending})

    def test_workspace_isolation_by_status(self) -> None:
        connection = self.storage._require_connection()
        connection.execute(
            "INSERT INTO files (workspace_id, path, hash, status) VALUES (?, ?, ?, ?)",
            ("other", "/other.pdf", "h-other", FileStatus.PENDING),
        )
        connection.commit()
        self.storage.add_file(path="/mine.pdf", file_hash="h-mine")
        default_ws = self.storage.list_files_by_status(FileStatus.PENDING)
        other_ws = self.storage.list_files_by_status(FileStatus.PENDING, workspace_id="other")
        self.assertEqual([r.path for r in default_ws], ["/mine.pdf"])
        self.assertEqual([r.path for r in other_ws], ["/other.pdf"])

    def test_deterministic_ordering_by_id_for_status(self) -> None:
        first = self.storage.add_file(path="/1.pdf", file_hash="h1")
        second = self.storage.add_file(path="/2.pdf", file_hash="h2")
        third = self.storage.add_file(path="/3.pdf", file_hash="h3")
        self.assertEqual(
            [r.id for r in self.storage.list_files_by_status(FileStatus.PENDING)],
            [first, second, third],
        )

    def test_empty_when_no_files_match_status(self) -> None:
        self.assertEqual(self.storage.list_files_by_status(FileStatus.READY), [])

    # --- backup_to (T6.3 export/import) ---

    def test_backup_to_produces_an_independently_openable_copy(self) -> None:
        file_id = self.storage.add_file(path="/a.pdf", file_hash="h1")
        backup_path = Path(self._tmp.name) / "backup.db"
        self.storage.backup_to(backup_path)

        self.assertTrue(backup_path.exists())
        copy = SQLiteStorage(backup_path)
        copy.connect()
        try:
            record = copy.get_file(file_id)
            self.assertIsNotNone(record)
            self.assertEqual(record.path, "/a.pdf")
            self.assertEqual(record.hash, "h1")
        finally:
            copy.close()

    def test_backup_to_matches_source_row_for_row(self) -> None:
        self.storage.add_file(path="/a.pdf", file_hash="h1")
        self.storage.add_file(path="/b.pdf", file_hash="h2")
        backup_path = Path(self._tmp.name) / "backup.db"
        self.storage.backup_to(backup_path)

        copy = SQLiteStorage(backup_path)
        copy.connect()
        try:
            self.assertIsNotNone(copy.get_file_by_hash("h1"))
            self.assertIsNotNone(copy.get_file_by_hash("h2"))
        finally:
            copy.close()

    def test_backup_to_does_not_mutate_the_source(self) -> None:
        self.storage.add_file(path="/a.pdf", file_hash="h1")
        before = self.storage.get_file_by_hash("h1")
        self.storage.backup_to(Path(self._tmp.name) / "backup.db")
        after = self.storage.get_file_by_hash("h1")
        self.assertEqual(before, after)

    def test_backup_to_creates_parent_directory(self) -> None:
        backup_path = Path(self._tmp.name) / "nested" / "dir" / "backup.db"
        self.storage.backup_to(backup_path)
        self.assertTrue(backup_path.exists())

    def test_backup_to_before_connect_raises(self) -> None:
        disconnected = SQLiteStorage(Path(self._tmp.name) / "other.db")
        with self.assertRaises(RuntimeError):
            disconnected.backup_to(Path(self._tmp.name) / "backup.db")


if __name__ == "__main__":
    unittest.main()
