"""Behaviour tests for file registration (hash + dedup)."""

import tempfile
import unittest
from pathlib import Path

from aipos.hashing import sha256_file
from aipos.ingest import process_file, register_file
from aipos.storage import FileStatus, SQLiteStorage
from tests.embedder_fakes import DeterministicEmbedder, FailingEmbedder, RecordingEmbedder
from tests.pdf_fixtures import make_text_pdf, write_blank_pdf
from tests.vector_store_fakes import FailingVectorStore, RecordingVectorStore


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


class ProcessFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.storage = SQLiteStorage(self.root / "aipos.db")
        self.storage.connect()
        self.embedder = DeterministicEmbedder()
        self.vectors = RecordingVectorStore()

    def tearDown(self) -> None:
        self.storage.close()
        self._tmp.cleanup()

    def _status_of(self, hash_hex: str) -> FileStatus:
        return self.storage.get_file_by_hash(hash_hex).status

    def test_text_pdf_becomes_ready(self) -> None:
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        process_file(pdf, self.storage, self.embedder, self.vectors)
        self.assertIs(self._status_of(sha256_file(pdf)), FileStatus.READY)

    def test_empty_pdf_becomes_ready(self) -> None:
        pdf = self.root / "blank.pdf"
        write_blank_pdf(pdf)
        process_file(pdf, self.storage, self.embedder, self.vectors)
        self.assertIs(self._status_of(sha256_file(pdf)), FileStatus.READY)

    def test_corrupted_pdf_becomes_failed_with_error(self) -> None:
        pdf = self.root / "bad.pdf"
        pdf.write_bytes(b"this is not a pdf at all")
        process_file(pdf, self.storage, self.embedder, self.vectors)
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        self.assertIs(record.status, FileStatus.FAILED)
        self.assertTrue(record.error)  # a failure reason was recorded

    def test_non_pdf_stays_pending(self) -> None:
        txt = self.root / "note.txt"
        txt.write_text("just text", encoding="utf-8")
        process_file(txt, self.storage, self.embedder, self.vectors)
        self.assertIs(self._status_of(sha256_file(txt)), FileStatus.PENDING)

    def test_duplicate_pdf_is_skipped(self) -> None:
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        process_file(pdf, self.storage, self.embedder, self.vectors)
        process_file(pdf, self.storage, self.embedder, self.vectors)  # duplicate hash
        rows = self.storage._require_connection().execute(
            "SELECT count(*) FROM files"
        ).fetchone()[0]
        self.assertEqual(rows, 1)

    def test_text_pdf_persists_chunks_and_stays_ready(self) -> None:
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        process_file(pdf, self.storage, self.embedder, self.vectors)
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        self.assertIs(record.status, FileStatus.READY)
        self.assertGreaterEqual(len(self.storage.get_chunks(record.id)), 1)

    def test_one_embedding_generated_per_stored_chunk(self) -> None:
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        recorder = RecordingEmbedder()
        process_file(pdf, self.storage, recorder, self.vectors)
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        stored = self.storage.get_chunk_records(record.id)
        # exactly one batch, containing every stored chunk's text in order
        self.assertEqual(len(recorder.calls), 1)
        self.assertEqual(recorder.calls[0], [chunk.text for chunk in stored])
        self.assertIs(record.status, FileStatus.READY)

    def test_embedding_failure_marks_file_failed(self) -> None:
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        process_file(pdf, self.storage, FailingEmbedder(), self.vectors)
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        self.assertIs(record.status, FileStatus.FAILED)
        self.assertTrue(record.error)

    def test_vectors_persisted_keyed_by_chunk_id(self) -> None:
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        process_file(pdf, self.storage, self.embedder, self.vectors)
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        stored = self.storage.get_chunk_records(record.id)
        # one vector persisted per stored chunk, keyed by the chunk's db id
        self.assertEqual(
            [chunk_id for chunk_id, _ in self.vectors.added],
            [chunk.id for chunk in stored],
        )
        self.assertIs(record.status, FileStatus.READY)

    def test_vector_persistence_failure_marks_file_failed(self) -> None:
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        process_file(pdf, self.storage, self.embedder, FailingVectorStore())
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        self.assertIs(record.status, FileStatus.FAILED)
        self.assertTrue(record.error)


if __name__ == "__main__":
    unittest.main()
