"""Behaviour tests for the SHA-256 utility."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from aipos.hashing import sha256_file


class Sha256FileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_matches_hashlib(self) -> None:
        content = b"hello world\n"
        f = self.root / "small.txt"
        f.write_bytes(content)
        self.assertEqual(sha256_file(f), hashlib.sha256(content).hexdigest())

    def test_handles_large_file_across_chunks(self) -> None:
        content = b"x" * (65536 * 3 + 17)  # spans multiple read chunks
        f = self.root / "big.bin"
        f.write_bytes(content)
        self.assertEqual(sha256_file(f), hashlib.sha256(content).hexdigest())

    def test_same_content_same_hash(self) -> None:
        (self.root / "a.txt").write_text("identical", encoding="utf-8")
        (self.root / "b.txt").write_text("identical", encoding="utf-8")
        self.assertEqual(
            sha256_file(self.root / "a.txt"),
            sha256_file(self.root / "b.txt"),
        )

    def test_different_content_different_hash(self) -> None:
        (self.root / "a.txt").write_text("one", encoding="utf-8")
        (self.root / "b.txt").write_text("two", encoding="utf-8")
        self.assertNotEqual(
            sha256_file(self.root / "a.txt"),
            sha256_file(self.root / "b.txt"),
        )


if __name__ == "__main__":
    unittest.main()
