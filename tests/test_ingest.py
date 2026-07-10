"""Behaviour tests for file registration (hash + dedup)."""

import tempfile
import unittest
from pathlib import Path

from aipos.chunking import chunk_text
from aipos.hashing import sha256_file
from aipos.ingest import (
    find_unqueued_pdfs,
    process_file,
    process_registered_file,
    register_file,
    resume_pending,
    retry_file,
)
from aipos.storage import FileStatus, SQLiteStorage
from tests.embedder_fakes import DeterministicEmbedder, FailingEmbedder, RecordingEmbedder
from tests.extractor_fakes import SAMPLE_RESULT, FailingExtractor, RecordingExtractor
from tests.ocr_fakes import FailingOcr, RecordingOcr
from tests.pdf_fixtures import make_text_pdf, write_blank_pdf
from tests.vector_store_fakes import FailingVectorStore, RecordingVectorStore


class _GraphFailingStorage(SQLiteStorage):
    """SQLiteStorage whose graph persistence always fails (isolation testing)."""

    def add_graph(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("graph persistence unavailable")


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

    # --- graph persistence during EXTRACTING (T4.2) ---

    def test_ingestion_persists_extracted_graph(self) -> None:
        # The extracted entities/relationships are persisted and queryable, and
        # the file reaches ready.
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        process_file(
            pdf, self.storage, self.embedder, self.vectors, self.ocr,
            RecordingExtractor(SAMPLE_RESULT),
        )
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        self.assertIs(record.status, FileStatus.READY)
        alice = self.storage.get_entity_by_name("Alice")
        ztna = self.storage.get_entity_by_name("ZTNA")
        self.assertIsNotNone(alice)
        self.assertIsNotNone(ztna)
        self.assertIn(ztna.id, [n.id for n in self.storage.get_neighbors(alice.id)])

    def test_ingestion_edge_weight_matches_chunk_count(self) -> None:
        # SAMPLE_RESULT is returned for every chunk, so the single triple's
        # weight equals the number of stored chunks.
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        process_file(
            pdf, self.storage, self.embedder, self.vectors, self.ocr,
            RecordingExtractor(SAMPLE_RESULT),
        )
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        chunk_count = len(self.storage.get_chunk_records(record.id))
        edges = self.storage.get_edges()
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].weight, chunk_count)

    def test_ingestion_with_no_entities_stays_ready_with_empty_graph(self) -> None:
        # The default RecordingExtractor returns an empty result: the file still
        # reaches ready and no graph rows are written.
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        process_file(pdf, self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        self.assertIs(record.status, FileStatus.READY)
        self.assertEqual(self.storage.get_edges(), [])
        self.assertIsNone(self.storage.get_entity_by_name("Alice"))

    def test_graph_persistence_failure_marks_file_failed(self) -> None:
        # A persistence failure during EXTRACTING behaves like any other stage
        # failure: FAILED with the error recorded, and embedding already ran.
        storage = _GraphFailingStorage(self.root / "fail.db")
        storage.connect()
        try:
            pdf = self.root / "doc.pdf"
            pdf.write_bytes(make_text_pdf("Hello World"))
            process_file(
                pdf, storage, self.embedder, self.vectors, self.ocr,
                RecordingExtractor(SAMPLE_RESULT),
            )
            record = storage.get_file_by_hash(sha256_file(pdf))
            self.assertIs(record.status, FileStatus.FAILED)
            self.assertTrue(record.error)
            self.assertTrue(storage.get_chunk_records(record.id))  # embedding ran first
        finally:
            storage.close()


class ResumeAndRetryTests(unittest.TestCase):
    """Crash recovery (T6.1): resume_pending() and retry_file()."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.storage = SQLiteStorage(self.root / "aipos.db")
        self.storage.connect()
        self.embedder = DeterministicEmbedder()
        self.vectors = RecordingVectorStore()
        self.ocr = RecordingOcr()
        self.extractor = RecordingExtractor()

    def tearDown(self) -> None:
        self.storage.close()
        self._tmp.cleanup()

    def _seed_file(
        self,
        name: str,
        text: str,
        status: FileStatus,
        *,
        with_chunks: bool = False,
        error: str | None = None,
    ) -> int:
        """Register a PDF and force it into ``status``, simulating a crash."""
        path = self.root / name
        path.write_bytes(make_text_pdf(text))
        file_id = self.storage.add_file(path=str(path), file_hash=sha256_file(path))
        if with_chunks:
            self.storage.add_chunks(file_id, chunk_text(text))
        self.storage.update_status(file_id, status, error=error)
        return file_id

    # --- resume_pending: resuming from each in-progress status ---

    def test_resume_from_parsing_runs_full_pipeline(self) -> None:
        file_id = self._seed_file("a.pdf", "Hello World", FileStatus.PARSING)
        resume_pending(self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        record = self.storage.get_file(file_id)
        self.assertIs(record.status, FileStatus.READY)
        self.assertTrue(self.storage.get_chunk_records(file_id))

    def test_resume_from_embedding_skips_reparse_and_rechunk(self) -> None:
        file_id = self._seed_file(
            "a.pdf", "Hello World", FileStatus.EMBEDDING, with_chunks=True
        )
        resume_pending(self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        record = self.storage.get_file(file_id)
        self.assertIs(record.status, FileStatus.READY)
        self.assertEqual(self.ocr.calls, [])  # parsing/OCR never re-ran

    def test_resume_from_extracting_skips_reparse_and_rechunk(self) -> None:
        file_id = self._seed_file(
            "a.pdf", "Hello World", FileStatus.EXTRACTING, with_chunks=True
        )
        resume_pending(self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        record = self.storage.get_file(file_id)
        self.assertIs(record.status, FileStatus.READY)
        self.assertEqual(self.ocr.calls, [])

    def test_resume_skips_chunking_when_chunks_already_exist(self) -> None:
        file_id = self._seed_file(
            "a.pdf", "Hello World", FileStatus.CHUNKING, with_chunks=True
        )
        before = self.storage.get_chunk_records(file_id)
        resume_pending(self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        after = self.storage.get_chunk_records(file_id)
        # Same rows, not re-inserted (chunk storage does not deduplicate — T2.4).
        self.assertEqual([c.id for c in after], [c.id for c in before])

    def test_resume_preserves_chunk_count(self) -> None:
        file_id = self._seed_file("a.pdf", "Hello World", FileStatus.PARSING)
        resume_pending(self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        resumed_chunks = self.storage.get_chunk_records(file_id)

        control_path = self.root / "control.pdf"
        control_path.write_bytes(make_text_pdf("Hello World"))
        process_file(
            control_path, self.storage, self.embedder, self.vectors, self.ocr, self.extractor
        )
        control_id = self.storage.get_file_by_hash(sha256_file(control_path)).id
        control_chunks = self.storage.get_chunk_records(control_id)

        self.assertEqual(len(resumed_chunks), len(control_chunks))

    def test_resume_preserves_graph_state(self) -> None:
        extractor = RecordingExtractor(SAMPLE_RESULT)
        file_id = self._seed_file(
            "a.pdf", "Hello World", FileStatus.EXTRACTING, with_chunks=True
        )
        resume_pending(self.storage, self.embedder, self.vectors, self.ocr, extractor)
        self.assertIs(self.storage.get_file(file_id).status, FileStatus.READY)
        self.assertIsNotNone(self.storage.get_entity_by_name("Alice"))
        self.assertIsNotNone(self.storage.get_entity_by_name("ZTNA"))

    def test_resume_preserves_vector_count(self) -> None:
        file_id = self._seed_file(
            "a.pdf", "Hello World", FileStatus.EMBEDDING, with_chunks=True
        )
        resume_pending(self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        chunks = self.storage.get_chunk_records(file_id)
        self.assertEqual(len(self.vectors.added), len(chunks))

    def test_resume_excludes_pending_non_pdf_files(self) -> None:
        # Non-PDF files sit at PENDING forever by design (T2.1) — resume must
        # never sweep them in, or it would misclassify them as failures.
        txt = self.root / "note.txt"
        txt.write_text("just a note", encoding="utf-8")
        txt_id = self.storage.add_file(path=str(txt), file_hash=sha256_file(txt))
        resume_pending(self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        self.assertIs(self.storage.get_file(txt_id).status, FileStatus.PENDING)

    def test_one_bad_resume_does_not_stop_the_remaining_files(self) -> None:
        # A file whose PDF no longer exists on disk (deleted after the crash)
        # alongside a healthy stuck file; the healthy one must still resume.
        missing_path = self.root / "missing.pdf"  # never written
        missing_id = self.storage.add_file(
            path=str(missing_path), file_hash="missing-hash"
        )
        self.storage.update_status(missing_id, FileStatus.PARSING)
        good_id = self._seed_file("good.pdf", "good document", FileStatus.PARSING)

        resume_pending(self.storage, self.embedder, self.vectors, self.ocr, self.extractor)

        self.assertIs(self.storage.get_file(missing_id).status, FileStatus.FAILED)
        self.assertTrue(self.storage.get_file(missing_id).error)
        self.assertIs(self.storage.get_file(good_id).status, FileStatus.READY)

    def test_resume_after_simulated_crash_reaches_ready_cleanly(self) -> None:
        # The literal T6.1 done-when: a file interrupted mid-pipeline (crash)
        # reaches a clean, fully-processed state after a resume sweep, as
        # main() would run on restart.
        extractor = RecordingExtractor(SAMPLE_RESULT)
        file_id = self._seed_file(
            "crashed.pdf", "Hello World", FileStatus.CHUNKING, with_chunks=True
        )
        resume_pending(self.storage, self.embedder, self.vectors, self.ocr, extractor)
        record = self.storage.get_file(file_id)
        self.assertIs(record.status, FileStatus.READY)
        self.assertIsNone(record.error)
        chunks = self.storage.get_chunk_records(file_id)
        self.assertTrue(chunks)
        self.assertEqual(len(self.vectors.added), len(chunks))
        self.assertIsNotNone(self.storage.get_entity_by_name("Alice"))

    # --- retry_file ---

    def test_retry_failed_file_reprocesses(self) -> None:
        file_id = self._seed_file(
            "a.pdf", "Hello World", FileStatus.FAILED, error="boom"
        )
        retry_file(file_id, self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        self.assertIs(self.storage.get_file(file_id).status, FileStatus.READY)

    def test_retry_unknown_file_is_a_noop(self) -> None:
        retry_file(999999, self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        self.assertIsNone(self.storage.get_file(999999))  # no crash, nothing created

    def test_retry_ready_file_is_a_noop(self) -> None:
        file_id = self._seed_file(
            "a.pdf", "Hello World", FileStatus.READY, with_chunks=True
        )
        before = self.storage.get_chunk_records(file_id)
        retry_file(file_id, self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        after = self.storage.get_chunk_records(file_id)
        self.assertEqual([c.id for c in after], [c.id for c in before])  # untouched
        self.assertIs(self.storage.get_file(file_id).status, FileStatus.READY)

    def test_retry_clears_previous_error(self) -> None:
        file_id = self._seed_file(
            "a.pdf", "Hello World", FileStatus.FAILED, error="boom"
        )
        self.assertEqual(self.storage.get_file(file_id).error, "boom")
        retry_file(file_id, self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        record = self.storage.get_file(file_id)
        self.assertIs(record.status, FileStatus.READY)
        self.assertIsNone(record.error)

    def test_retry_reuses_chunks_when_failure_happened_after_chunking(self) -> None:
        # Failed after chunking succeeded (e.g. embedding failed) — retry must
        # not re-chunk.
        file_id = self._seed_file(
            "a.pdf", "Hello World", FileStatus.FAILED, with_chunks=True, error="boom"
        )
        before = self.storage.get_chunk_records(file_id)
        retry_file(file_id, self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        after = self.storage.get_chunk_records(file_id)
        self.assertEqual([c.id for c in after], [c.id for c in before])
        self.assertIs(self.storage.get_file(file_id).status, FileStatus.READY)

    # --- idempotency regression (approved decision 5) ---

    def test_resume_pending_called_twice_is_idempotent(self) -> None:
        extractor = RecordingExtractor(SAMPLE_RESULT)
        crashed_id = self._seed_file(
            "crashed.pdf", "Hello World", FileStatus.CHUNKING, with_chunks=True
        )

        ready_path = self.root / "ready.pdf"
        ready_path.write_bytes(make_text_pdf("Already done"))
        process_file(ready_path, self.storage, self.embedder, self.vectors, self.ocr, extractor)
        ready_id = self.storage.get_file_by_hash(sha256_file(ready_path)).id
        self.assertIs(self.storage.get_file(ready_id).status, FileStatus.READY)

        resume_pending(self.storage, self.embedder, self.vectors, self.ocr, extractor)

        crashed_chunks_1 = self.storage.get_chunk_records(crashed_id)
        ready_chunks_1 = self.storage.get_chunk_records(ready_id)
        vectors_1 = list(self.vectors.added)
        edges_1 = [
            (e.source_entity_id, e.target_entity_id, e.relation, e.weight)
            for e in self.storage.get_edges()
        ]
        ready_record_1 = self.storage.get_file(ready_id)

        resume_pending(self.storage, self.embedder, self.vectors, self.ocr, extractor)

        crashed_chunks_2 = self.storage.get_chunk_records(crashed_id)
        ready_chunks_2 = self.storage.get_chunk_records(ready_id)
        vectors_2 = list(self.vectors.added)
        edges_2 = [
            (e.source_entity_id, e.target_entity_id, e.relation, e.weight)
            for e in self.storage.get_edges()
        ]
        ready_record_2 = self.storage.get_file(ready_id)

        self.assertEqual(crashed_chunks_1, crashed_chunks_2)  # no duplicate chunks
        self.assertEqual(ready_chunks_1, ready_chunks_2)
        self.assertEqual(vectors_1, vectors_2)  # no duplicate vectors
        self.assertEqual(edges_1, edges_2)  # no increased edge weight
        self.assertEqual(ready_record_1, ready_record_2)  # READY file unchanged
        self.assertIs(self.storage.get_file(crashed_id).status, FileStatus.READY)


class ProcessRegisteredFileAndUnqueuedPdfsTests(unittest.TestCase):
    """T6.2: process_registered_file (the renamed, now-public pipeline entry
    point) and find_unqueued_pdfs (the queued-PDF crash-recovery gap)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.storage = SQLiteStorage(self.root / "aipos.db")
        self.storage.connect()
        self.embedder = DeterministicEmbedder()
        self.vectors = RecordingVectorStore()
        self.ocr = RecordingOcr()
        self.extractor = RecordingExtractor()

    def tearDown(self) -> None:
        self.storage.close()
        self._tmp.cleanup()

    # --- process_registered_file: identical behaviour to the old _process_pdf ---

    def test_process_registered_file_reaches_ready(self) -> None:
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        record = register_file(pdf, self.storage)
        process_registered_file(
            record.id, pdf, self.storage, self.embedder, self.vectors, self.ocr, self.extractor
        )
        self.assertIs(self.storage.get_file(record.id).status, FileStatus.READY)
        self.assertTrue(self.storage.get_chunk_records(record.id))

    def test_process_registered_file_produces_same_result_as_process_file(self) -> None:
        # Two identical documents, one driven through process_file (register +
        # process in one call) and one through register_file +
        # process_registered_file separately — same chunk/vector/ready outcome.
        via_process_file = self.root / "a.pdf"
        via_process_file.write_bytes(make_text_pdf("Hello World"))
        process_file(
            via_process_file, self.storage, self.embedder, self.vectors, self.ocr, self.extractor
        )
        a_record = self.storage.get_file_by_hash(sha256_file(via_process_file))

        via_registered = self.root / "b.pdf"
        via_registered.write_bytes(make_text_pdf("Hello World, again"))
        b_record = register_file(via_registered, self.storage)
        process_registered_file(
            b_record.id, via_registered, self.storage, self.embedder, self.vectors,
            self.ocr, self.extractor,
        )

        self.assertIs(a_record.status, FileStatus.READY)
        self.assertIs(self.storage.get_file(b_record.id).status, FileStatus.READY)
        self.assertEqual(
            len(self.storage.get_chunk_records(a_record.id)),
            len(self.storage.get_chunk_records(b_record.id)),
        )

    def test_process_registered_file_marks_failed_on_error(self) -> None:
        pdf = self.root / "bad.pdf"
        pdf.write_bytes(b"this is not a pdf at all")
        record = register_file(pdf, self.storage)
        process_registered_file(
            record.id, pdf, self.storage, self.embedder, self.vectors, self.ocr, self.extractor
        )
        result = self.storage.get_file(record.id)
        self.assertIs(result.status, FileStatus.FAILED)
        self.assertTrue(result.error)

    # --- find_unqueued_pdfs ---

    def test_finds_pending_pdf(self) -> None:
        pdf = self.root / "a.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        record = register_file(pdf, self.storage)
        found = {r.id for r in find_unqueued_pdfs(self.storage)}
        self.assertEqual(found, {record.id})

    def test_excludes_pending_non_pdf(self) -> None:
        txt = self.root / "note.txt"
        txt.write_text("just a note", encoding="utf-8")
        register_file(txt, self.storage)
        self.assertEqual(find_unqueued_pdfs(self.storage), [])

    def test_excludes_pdfs_past_pending(self) -> None:
        pdf = self.root / "a.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        record = register_file(pdf, self.storage)
        process_registered_file(
            record.id, pdf, self.storage, self.embedder, self.vectors, self.ocr, self.extractor
        )
        self.assertEqual(find_unqueued_pdfs(self.storage), [])

    def test_excludes_in_progress_pdf(self) -> None:
        pdf = self.root / "a.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        record = register_file(pdf, self.storage)
        self.storage.update_status(record.id, FileStatus.CHUNKING)
        self.assertEqual(find_unqueued_pdfs(self.storage), [])

    def test_empty_when_no_files(self) -> None:
        self.assertEqual(find_unqueued_pdfs(self.storage), [])

    def test_mixed_pending_files_returns_only_pdfs(self) -> None:
        pdf = self.root / "a.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        pdf_record = register_file(pdf, self.storage)
        txt = self.root / "b.txt"
        txt.write_text("note", encoding="utf-8")
        register_file(txt, self.storage)
        found = {r.id for r in find_unqueued_pdfs(self.storage)}
        self.assertEqual(found, {pdf_record.id})


if __name__ == "__main__":
    unittest.main()
