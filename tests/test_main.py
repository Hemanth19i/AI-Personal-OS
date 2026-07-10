"""Behaviour tests for main.py's T6.2 queue wiring.

``main()`` itself wires real Ollama/LanceDB/watchdog and is verified via the
`python main.py` smoke-test convention noted in its own docstring (as it
always has been — main.py has never had direct unit tests). What T6.2 adds is
non-trivial enough to warrant testing in isolation, so the wiring logic was
extracted into standalone, parameter-injected functions
(``_on_new_file``, ``_make_ingest_job``, ``_enqueue_unqueued_pdfs``); this
file exercises exactly those, with fakes for embedder/ocr/extractor and a
fake TaskQueue that records submitted jobs without running them on real
threads (real concurrency is covered by tests/test_task_queue.py). Storage and
the vector store are real (temp dir) — lightweight, no external binary.
"""

import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path

from main import _enqueue_unqueued_pdfs, _make_ingest_job, _on_new_file

from aipos.hashing import sha256_file
from aipos.ingest import register_file
from aipos.storage import FileStatus, SQLiteStorage
from aipos.task_queue import TaskQueue
from aipos.vector_store import VECTOR_STORE_DIRNAME
from tests.embedder_fakes import DeterministicEmbedder
from tests.extractor_fakes import RecordingExtractor
from tests.ocr_fakes import RecordingOcr
from tests.pdf_fixtures import make_text_pdf


class _RecordingTaskQueue:
    """Fake TaskQueue: records submitted jobs without running them."""

    def __init__(self) -> None:
        self.submitted: list[Callable[[], None]] = []
        self.stopped = False

    def submit(self, job: Callable[[], None]) -> None:
        self.submitted.append(job)

    def stop(self, *, wait: bool = False) -> None:
        self.stopped = True


class RecordingTaskQueueTests(unittest.TestCase):
    def test_satisfies_protocol(self) -> None:
        self.assertIsInstance(_RecordingTaskQueue(), TaskQueue)


class MainWiringTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db_path = self.root / "aipos.db"
        self.vs_path = self.root / VECTOR_STORE_DIRNAME
        self.storage = SQLiteStorage(self.db_path)
        self.storage.connect()
        self.embedder = DeterministicEmbedder()
        self.ocr = RecordingOcr()
        self.extractor = RecordingExtractor()

    def tearDown(self) -> None:
        self.storage.close()
        self._tmp.cleanup()

    def _write_pdf(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_bytes(make_text_pdf(text))
        return path


class OnNewFileTests(MainWiringTestCase):
    def test_new_pdf_registers_and_submits_one_job(self) -> None:
        pdf = self._write_pdf("a.pdf", "Hello World")
        queue = _RecordingTaskQueue()
        _on_new_file(
            pdf, self.storage, queue, self.db_path, self.vs_path,
            self.embedder, self.ocr, self.extractor,
        )
        self.assertIsNotNone(self.storage.get_file_by_hash(sha256_file(pdf)))
        self.assertEqual(len(queue.submitted), 1)

    def test_duplicate_content_registers_no_job(self) -> None:
        pdf = self._write_pdf("a.pdf", "Hello World")
        queue = _RecordingTaskQueue()
        _on_new_file(
            pdf, self.storage, queue, self.db_path, self.vs_path,
            self.embedder, self.ocr, self.extractor,
        )
        dup = self._write_pdf("b.pdf", "Hello World")  # same content
        _on_new_file(
            dup, self.storage, queue, self.db_path, self.vs_path,
            self.embedder, self.ocr, self.extractor,
        )
        self.assertEqual(len(queue.submitted), 1)  # only the first

    def test_non_pdf_registers_but_submits_no_job(self) -> None:
        txt = self.root / "note.txt"
        txt.write_text("just a note", encoding="utf-8")
        queue = _RecordingTaskQueue()
        _on_new_file(
            txt, self.storage, queue, self.db_path, self.vs_path,
            self.embedder, self.ocr, self.extractor,
        )
        record = self.storage.get_file_by_hash(sha256_file(txt))
        self.assertIsNotNone(record)
        self.assertIs(record.status, FileStatus.PENDING)
        self.assertEqual(queue.submitted, [])

    def test_submitted_job_runs_the_full_pipeline(self) -> None:
        pdf = self._write_pdf("a.pdf", "Hello World")
        queue = _RecordingTaskQueue()
        _on_new_file(
            pdf, self.storage, queue, self.db_path, self.vs_path,
            self.embedder, self.ocr, self.extractor,
        )
        self.assertEqual(len(queue.submitted), 1)
        queue.submitted[0]()  # run the job synchronously, as a worker would
        record = self.storage.get_file_by_hash(sha256_file(pdf))
        self.assertIs(record.status, FileStatus.READY)
        self.assertTrue(self.storage.get_chunk_records(record.id))


class MakeIngestJobTests(MainWiringTestCase):
    def test_job_processes_file_to_ready_with_its_own_connections(self) -> None:
        pdf = self._write_pdf("a.pdf", "Hello World")
        record = register_file(pdf, self.storage)
        job = _make_ingest_job(
            record.id, pdf, self.db_path, self.vs_path,
            self.embedder, self.ocr, self.extractor,
        )
        job()
        # Read back through the ORIGINAL (outer) storage connection — proves
        # the job's own connection wrote to the same underlying database file.
        result = self.storage.get_file(record.id)
        self.assertIs(result.status, FileStatus.READY)
        self.assertTrue(self.storage.get_chunk_records(record.id))

    def test_job_marks_failed_on_pipeline_error(self) -> None:
        pdf = self.root / "bad.pdf"
        pdf.write_bytes(b"not a pdf at all")
        record = register_file(pdf, self.storage)
        job = _make_ingest_job(
            record.id, pdf, self.db_path, self.vs_path,
            self.embedder, self.ocr, self.extractor,
        )
        job()
        result = self.storage.get_file(record.id)
        self.assertIs(result.status, FileStatus.FAILED)
        self.assertTrue(result.error)

    def test_two_jobs_do_not_cross_contaminate(self) -> None:
        # Worker isolation: each job opens its own storage/vector_store; two
        # different files' jobs must not interfere with each other's chunks.
        pdf_a = self._write_pdf("a.pdf", "Alpha document text")
        pdf_b = self._write_pdf("b.pdf", "Beta document text, quite different")
        record_a = register_file(pdf_a, self.storage)
        record_b = register_file(pdf_b, self.storage)

        job_a = _make_ingest_job(
            record_a.id, pdf_a, self.db_path, self.vs_path,
            self.embedder, self.ocr, self.extractor,
        )
        job_b = _make_ingest_job(
            record_b.id, pdf_b, self.db_path, self.vs_path,
            self.embedder, self.ocr, self.extractor,
        )
        job_a()
        job_b()

        result_a = self.storage.get_file(record_a.id)
        result_b = self.storage.get_file(record_b.id)
        self.assertIs(result_a.status, FileStatus.READY)
        self.assertIs(result_b.status, FileStatus.READY)
        chunks_a = self.storage.get_chunk_records(record_a.id)
        chunks_b = self.storage.get_chunk_records(record_b.id)
        self.assertTrue(chunks_a)
        self.assertTrue(chunks_b)
        self.assertEqual(set(c.id for c in chunks_a) & set(c.id for c in chunks_b), set())


class EnqueueUnqueuedPdfsTests(MainWiringTestCase):
    def test_submits_a_job_per_unqueued_pdf(self) -> None:
        pdf = self._write_pdf("a.pdf", "Hello World")
        register_file(pdf, self.storage)
        queue = _RecordingTaskQueue()
        _enqueue_unqueued_pdfs(
            self.storage, queue, self.db_path, self.vs_path,
            self.embedder, self.ocr, self.extractor,
        )
        self.assertEqual(len(queue.submitted), 1)

    def test_excludes_pending_non_pdf_and_in_progress_files(self) -> None:
        txt = self.root / "note.txt"
        txt.write_text("just a note", encoding="utf-8")
        register_file(txt, self.storage)

        in_progress_pdf = self._write_pdf("b.pdf", "In progress")
        in_progress_record = register_file(in_progress_pdf, self.storage)
        self.storage.update_status(in_progress_record.id, FileStatus.CHUNKING)

        queue = _RecordingTaskQueue()
        _enqueue_unqueued_pdfs(
            self.storage, queue, self.db_path, self.vs_path,
            self.embedder, self.ocr, self.extractor,
        )
        self.assertEqual(queue.submitted, [])

    def test_no_pending_pdfs_submits_nothing(self) -> None:
        queue = _RecordingTaskQueue()
        _enqueue_unqueued_pdfs(
            self.storage, queue, self.db_path, self.vs_path,
            self.embedder, self.ocr, self.extractor,
        )
        self.assertEqual(queue.submitted, [])

    def test_re_enqueued_job_reaches_ready(self) -> None:
        # Simulates a crash: a PDF was registered (synchronously, as
        # register_file always is) but never reached a worker.
        pdf = self._write_pdf("crashed.pdf", "Hello World")
        register_file(pdf, self.storage)

        queue = _RecordingTaskQueue()
        _enqueue_unqueued_pdfs(
            self.storage, queue, self.db_path, self.vs_path,
            self.embedder, self.ocr, self.extractor,
        )
        self.assertEqual(len(queue.submitted), 1)
        queue.submitted[0]()

        record = self.storage.get_file_by_hash(sha256_file(pdf))
        self.assertIs(record.status, FileStatus.READY)


if __name__ == "__main__":
    unittest.main()
