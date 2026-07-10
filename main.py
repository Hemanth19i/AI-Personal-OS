"""Entry point for AI Personal OS.

Phase 1 skeleton. On startup it loads configuration (generating a default
config file on first run), ensures the local data directories exist, and
initializes the SQLite storage layer (creating the database and schema on
first run). It then starts watching the configured folder and runs until
interrupted (Ctrl+C); each completed file is hashed and registered in SQLite.
A fresh clone can run ``python main.py`` with no manual setup. Further
behaviour (parsing, retrieval, reasoning) is introduced in later milestones
per the Build Plan.

T6.2 routes ingestion through a background task queue (``aipos.task_queue``)
instead of running the heavy pipeline on the watcher's own thread: the watcher
callback (``_on_new_file``) registers a file synchronously (fast) and submits
the slow pipeline as a job; each job (``_make_ingest_job``) opens its own
``SQLiteStorage``/``LanceVectorStore`` connections, since neither is safe to
share across threads. ``embedder``/``ocr``/``extractor`` are stateless
per-call clients and are shared across every job. At startup, alongside T6.1's
``resume_pending()``, ``_enqueue_unqueued_pdfs`` re-submits any PDF that was
registered but never reached a worker before a previous crash.
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path

from aipos.config import load_config
from aipos.embedding import Embedder, OllamaEmbedder
from aipos.extraction import EntityExtractor, LLMEntityExtractor
from aipos.ingest import (
    find_unqueued_pdfs,
    process_registered_file,
    register_file,
    resume_pending,
)
from aipos.llm import OllamaLLM
from aipos.ocr import OcrEngine, TesseractOcr
from aipos.paths import database_path, ensure_app_directories, vector_store_path
from aipos.sources import FolderSource
from aipos.storage import SQLiteStorage
from aipos.task_queue import TaskQueue, ThreadPoolTaskQueue
from aipos.vector_store import LanceVectorStore

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent


def _make_ingest_job(
    file_id: int,
    path: Path,
    db_path: Path,
    vector_store_dir: Path,
    embedder: Embedder,
    ocr: OcrEngine,
    extractor: EntityExtractor,
) -> Callable[[], None]:
    """Build a task-queue job that runs the heavy pipeline for one file (T6.2).

    Each job opens its own ``SQLiteStorage``/``LanceVectorStore`` and closes
    the storage connection when done — ``sqlite3`` connections are not
    designed for concurrent use across threads, so every job gets a fresh,
    short-lived pair rather than sharing the app's long-lived connections.
    ``embedder``/``ocr``/``extractor`` are stateless per-call HTTP/subprocess
    clients and are safe to share across every job and worker.
    """

    def job() -> None:
        job_storage = SQLiteStorage(db_path)
        job_storage.connect()
        job_vector_store = LanceVectorStore(vector_store_dir)
        job_vector_store.connect()
        try:
            process_registered_file(
                file_id, path, job_storage, embedder, job_vector_store, ocr, extractor
            )
        finally:
            job_storage.close()

    return job


def _on_new_file(
    path: Path,
    storage: SQLiteStorage,
    task_queue: TaskQueue,
    db_path: Path,
    vector_store_dir: Path,
    embedder: Embedder,
    ocr: OcrEngine,
    extractor: EntityExtractor,
) -> None:
    """Watcher callback (T6.2): register synchronously, queue the heavy work.

    ``register_file`` stays synchronous and fast (hash + one INSERT) so a file
    is never lost between "detected" and "in the database" — only the slow
    pipeline (OCR/embedding/extraction) is deferred to a worker thread. This
    keeps the watcher's own dispatch thread free almost immediately, so a
    burst of file drops doesn't serialize behind one slow file.
    """
    record = register_file(path, storage)
    if record is None:
        return  # duplicate content, already registered
    if path.suffix.lower() != ".pdf":
        return  # only PDFs are parsed in this ticket
    task_queue.submit(
        _make_ingest_job(
            record.id, path, db_path, vector_store_dir, embedder, ocr, extractor
        )
    )


def _enqueue_unqueued_pdfs(
    storage: SQLiteStorage,
    task_queue: TaskQueue,
    db_path: Path,
    vector_store_dir: Path,
    embedder: Embedder,
    ocr: OcrEngine,
    extractor: EntityExtractor,
) -> None:
    """Re-enqueue PDFs registered but never processed before a crash (T6.2).

    Closes a gap T6.1's ``resume_pending()`` deliberately leaves open: PENDING
    is excluded from its sweep (non-PDF files sit there forever by design,
    T2.1), but once ingestion is queued a PDF can also be stuck at PENDING if
    the process crashed after registration but before a worker dequeued it.
    """
    for record in find_unqueued_pdfs(storage):
        task_queue.submit(
            _make_ingest_job(
                record.id,
                Path(record.path),
                db_path,
                vector_store_dir,
                embedder,
                ocr,
                extractor,
            )
        )


def main() -> None:
    """Bootstrap the application and print the liveness banner."""
    # Force UTF-8 output: on Windows, stdout defaults to a legacy code page
    # (e.g. cp1252) which mangles the em dash in a UTF-8 terminal.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = load_config(PROJECT_ROOT)
    ensure_app_directories(config)
    logger.info("Data directory: %s", config.data_dir)
    logger.info("Watched folder: %s", config.watched_folder)

    # Storage stays open for the watch lifetime so completed files can be
    # registered; it is closed in the finally below.
    db_path = database_path(config)
    storage = SQLiteStorage(db_path)
    storage.connect()
    logger.info("SQLite storage initialized at %s (files table ensured)", db_path)

    # Vector store: open (creating on first run) the local LanceDB database.
    vs_path = vector_store_path(config)
    vector_store = LanceVectorStore(vs_path)
    vector_store.connect()
    logger.info("Vector store initialized at %s", vs_path)

    # Watch the configured folder; each file that passes the write-completion
    # guard is registered and (if a PDF) parsed — with OCR fallback for scanned
    # PDFs — chunked, persisted, embedded, its vectors stored, and its entities
    # extracted (T1.4 + T2.2..T2.7 + T4.1). FolderSource owns the watching and
    # knows nothing of hashing, parsing, OCR, embedding, extraction, or storage.
    embedder = OllamaEmbedder(config.embedding_model)
    ocr = TesseractOcr()
    # Entity extraction reuses the existing LLM abstraction (no new backend);
    # the same Ollama model that answers questions extracts the graph.
    extractor = LLMEntityExtractor(OllamaLLM(config.llm_model))

    # Crash recovery (T6.1): resume any file a previous run left mid-pipeline,
    # once, before accepting new files — so killing the process mid-ingest and
    # restarting resumes cleanly (Design Doc §A5, PRD §7.1).
    resume_pending(storage, embedder, vector_store, ocr, extractor)

    # Background task queue (T6.2): heavy ingestion work runs on worker
    # threads, never on the watcher's own dispatch thread, so a burst of file
    # drops doesn't serialize behind one slow file (Design Doc §A9).
    task_queue = ThreadPoolTaskQueue()

    # Re-submit any PDF registered but never queued before a previous crash
    # (T6.2) — resume_pending() alone does not cover this (see docstring).
    _enqueue_unqueued_pdfs(storage, task_queue, db_path, vs_path, embedder, ocr, extractor)

    source = FolderSource(config.watched_folder)
    source.watch(
        lambda path: _on_new_file(
            path, storage, task_queue, db_path, vs_path, embedder, ocr, extractor
        )
    )

    # flush=True: stdout is block-buffered when piped, and the process then
    # blocks in the watch loop, so flush the readiness banner immediately.
    print("AI Personal OS — alive", flush=True)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        source.stop()
        # wait=False: don't block shutdown on in-flight/queued jobs — any file
        # left mid-pipeline is recovered by resume_pending() on the next
        # startup (T6.1), matching the failure philosophy (PRD §7.1).
        task_queue.stop(wait=False)
        storage.close()


if __name__ == "__main__":
    main()
