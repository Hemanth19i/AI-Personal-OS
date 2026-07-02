"""Behaviour tests for file registration (hash + dedup)."""

import tempfile
import unittest
from pathlib import Path

from aipos.hashing import sha256_file
from aipos.ingest import register_file
from aipos.storage import SQLiteStorage


class RegisterFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.storage = SQLiteStorage(self.root / "aipos.db")
        self.storage.connect()

    def tearDown(self) -> None:
        self.storage.close()
        self._tmp.cleanup()

    def _write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_new_file_registers_as_pending(self) -> None:
        path = self._write("a.txt", "content")
        record = register_file(path, self.storage)
        self.assertIsNotNone(record)
        self.assertEqual(record.status, "pending")
        self.assertEqual(record.hash, sha256_file(path))
        self.assertEqual(record.path, str(path))

    def test_same_file_again_is_skipped(self) -> None:
        path = self._write("a.txt", "content")
        first = register_file(path, self.storage)
        again = register_file(path, self.storage)
        self.assertIsNotNone(first)
        self.assertIsNone(again)  # duplicate hash -> skipped
        self.assertIsNotNone(self.storage.get_file_by_hash(first.hash))

    def test_identical_content_different_name_is_deduped(self) -> None:
        register_file(self._write("a.txt", "same"), self.storage)
        duplicate = register_file(self._write("b.txt", "same"), self.storage)
        self.assertIsNone(duplicate)

    def test_different_content_registers_separately(self) -> None:
        first = register_file(self._write("a.txt", "one"), self.storage)
        second = register_file(self._write("b.txt", "two"), self.storage)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(first.id, second.id)


if __name__ == "__main__":
    unittest.main()
