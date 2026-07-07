"""Behaviour tests for file registration (hash + dedup)."""

import tempfile
import unittest
from pathlib import Path

from aipos.hashing import sha256_file
from aipos.ingest import process_file, register_file
from aipos.storage import FileStatus, SQLiteStorage
from tests.embedder_fakes import DeterministicEmbedder, FailingEmbedder, RecordingEmbedder
from tests.extractor_fakes import FailingExtractor, RecordingExtractor
from tests.ocr_fakes import FailingOcr, RecordingOcr
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
        # Default: OCR recovers nothing, so text-layer PDFs behave as before and
        # a no-text PDF still reaches ready with no chunks. Individual tests
        # swap in an OCR fake that returns text or raises.
        self.ocr = RecordingOcr()
        # Default: extraction records the text it saw and returns nothing.
        # Individual tests swap in a fake that returns entities or raises.
        self.extractor = RecordingExtractor()

    def tearDown(self) -> None:
        self.storage.close()
        self._tmp.cleanup()

    def _status_of(self, hash_hex: str) -> FileStatus:
        return self.storage.get_file_by_hash(hash_hex).status

    def test_text_pdf_becomes_ready(self) -> None:
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        process_file(pdf, self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        self.assertIs(self._status_of(sha256_file(pdf)), FileStatus.READY)

    def test_empty_pdf_becomes_ready(self) -> None:
        pdf = self.root / "blank.pdf"
        write_blank_pdf(pdf)
        process_file(pdf, self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        self.assertIs(self._status_of(sha256_file(pdf)), FileStatus.READY)

    def test_corrupted_pdf_becomes_failed_with_error(self) -> None:
        pdf = self.root / "bad.pdf"
        pdf.write_bytes(b"this is not a pdf at all")
        process_file(pdf, self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        self.assertIs(record.status, FileStatus.FAILED)
        self.assertTrue(record.error)  # a failure reason was recorded

    def test_non_pdf_stays_pending(self) -> None:
        txt = self.root / "note.txt"
        txt.write_text("just text", encoding="utf-8")
        process_file(txt, self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        self.assertIs(self._status_of(sha256_file(txt)), FileStatus.PENDING)

    def test_duplicate_pdf_is_skipped(self) -> None:
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        process_file(pdf, self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        process_file(pdf, self.storage, self.embedder, self.vectors, self.ocr, self.extractor)  # dup hash
        rows = self.storage._require_connection().execute(
            "SELECT count(*) FROM files"
        ).fetchone()[0]
        self.assertEqual(rows, 1)

    def test_text_pdf_persists_chunks_and_stays_ready(self) -> None:
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        process_file(pdf, self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        self.assertIs(record.status, FileStatus.READY)
        self.assertGreaterEqual(len(self.storage.get_chunks(record.id)), 1)

    def test_one_embedding_generated_per_stored_chunk(self) -> None:
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        recorder = RecordingEmbedder()
        process_file(pdf, self.storage, recorder, self.vectors, self.ocr, self.extractor)
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        stored = self.storage.get_chunk_records(record.id)
        # exactly one batch, containing every stored chunk's text in order
        self.assertEqual(len(recorder.calls), 1)
        self.assertEqual(recorder.calls[0], [chunk.text for chunk in stored])
        self.assertIs(record.status, FileStatus.READY)

    def test_embedding_failure_marks_file_failed(self) -> None:
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        process_file(pdf, self.storage, FailingEmbedder(), self.vectors, self.ocr, self.extractor)
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        self.assertIs(record.status, FileStatus.FAILED)
        self.assertTrue(record.error)

    def test_vectors_persisted_keyed_by_chunk_id(self) -> None:
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        process_file(pdf, self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
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
        process_file(pdf, self.storage, self.embedder, FailingVectorStore(), self.ocr, self.extractor)
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        self.assertIs(record.status, FileStatus.FAILED)
        self.assertTrue(record.error)

    def test_scanned_pdf_recovers_text_via_ocr(self) -> None:
        # A PDF with no text layer stands in for a scanned document; OCR
        # recovers its text, which must flow into stored chunks.
        pdf = self.root / "scanned.pdf"
        write_blank_pdf(pdf)
        ocr = RecordingOcr("Recovered scanned text")
        process_file(pdf, self.storage, self.embedder, self.vectors, ocr, self.extractor)
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        self.assertIs(record.status, FileStatus.READY)
        self.assertEqual(len(ocr.calls), 1)  # OCR ran on the no-text PDF
        chunks = self.storage.get_chunks(record.id)
        self.assertTrue(chunks)
        self.assertIn("Recovered scanned text", "".join(c.text for c in chunks))

    def test_text_pdf_does_not_invoke_ocr(self) -> None:
        # A PDF with an extractable text layer must never reach the OCR step.
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        ocr = RecordingOcr("SHOULD NOT APPEAR")
        process_file(pdf, self.storage, self.embedder, self.vectors, ocr, self.extractor)
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        self.assertIs(record.status, FileStatus.READY)
        self.assertEqual(ocr.calls, [])

    def test_ocr_failure_marks_file_failed(self) -> None:
        pdf = self.root / "scanned.pdf"
        write_blank_pdf(pdf)
        process_file(
            pdf, self.storage, self.embedder, self.vectors, FailingOcr(), self.extractor
        )
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        self.assertIs(record.status, FileStatus.FAILED)
        self.assertTrue(record.error)

    def test_extraction_runs_once_per_stored_chunk(self) -> None:
        # Extraction runs at chunk granularity: exactly one call per stored
        # chunk, over that chunk's text and in chunk order (the `extracting`
        # lifecycle step), and the file reaches ready.
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        process_file(pdf, self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        self.assertIs(record.status, FileStatus.READY)
        stored = self.storage.get_chunk_records(record.id)
        self.assertEqual(self.extractor.calls, [chunk.text for chunk in stored])

    def test_extraction_receives_ocr_recovered_text_per_chunk(self) -> None:
        # For a scanned PDF, extraction must run over the OCR-recovered text
        # (confirming it sits after the OCR step) — one call per stored chunk.
        pdf = self.root / "scanned.pdf"
        write_blank_pdf(pdf)
        ocr = RecordingOcr("Recovered scanned text")
        process_file(pdf, self.storage, self.embedder, self.vectors, ocr, self.extractor)
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        self.assertIs(record.status, FileStatus.READY)
        stored = self.storage.get_chunk_records(record.id)
        self.assertEqual(self.extractor.calls, [chunk.text for chunk in stored])
        self.assertIn("Recovered scanned text", "".join(self.extractor.calls))

    def test_extraction_failure_marks_file_failed(self) -> None:
        # An extraction failure behaves exactly like an OCR/embedding failure:
        # the file is marked FAILED with the error recorded.
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        process_file(
            pdf, self.storage, self.embedder, self.vectors, self.ocr, FailingExtractor()
        )
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        self.assertIs(record.status, FileStatus.FAILED)
        self.assertTrue(record.error)

    def test_extraction_runs_after_embedding(self) -> None:
        # When extraction fails, embedding has already happened: chunks and
        # vectors are persisted. This pins the lifecycle order
        # embedding -> extracting.
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        process_file(
            pdf, self.storage, self.embedder, self.vectors, self.ocr, FailingExtractor()
        )
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        self.assertIs(record.status, FileStatus.FAILED)
        self.assertTrue(self.storage.get_chunk_records(record.id))  # embedding ran
        self.assertTrue(self.vectors.added)  # vectors were stored before extraction

    def test_one_bad_file_does_not_stop_the_next(self) -> None:
        # Per-file isolation (Design Doc §A9): a file whose extraction fails is
        # marked FAILED, and a subsequent healthy file still reaches ready.
        bad = self.root / "bad.pdf"
        bad.write_bytes(make_text_pdf("bad document"))
        process_file(
            bad, self.storage, self.embedder, self.vectors, self.ocr, FailingExtractor()
        )
        good = self.root / "good.pdf"
        good.write_bytes(make_text_pdf("good document"))
        process_file(good, self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        self.assertIs(self._status_of(sha256_file(bad)), FileStatus.FAILED)
        self.assertIs(self._status_of(sha256_file(good)), FileStatus.READY)


if __name__ == "__main__":
    unittest.main()
