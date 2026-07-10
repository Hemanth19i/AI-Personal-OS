"""Ingestion coordinator for AI Personal OS.

Orchestrates the ingestion pipeline for a completed file, tying together the
hashing utility, the storage layer, and the PDF parser without any of them
knowing about the others. Two responsibilities live here as application logic:
the "skip if the hash is already registered" decision (T1.4) and driving the
file through its lifecycle during parsing (T2.2).

Called for each file that has passed the write-completion guard.

T6.1 adds crash recovery (PRD §7.1 "Failure philosophy"): ``resume_pending``
sweeps files a previous run left mid-pipeline and resumes each from its last
good state, and ``retry_file`` re-runs a failed file on request. Both reuse the
same two stages ``_process_pdf`` is built from (split out for T6.1) so a file
that already has persisted chunks is never re-parsed or re-chunked.
"""

from __future__ import annotations

import logging
from pathlib import Path

from aipos.chunking import chunk_text
from aipos.embedding import Embedder
from aipos.extraction import EntityExtractor
from aipos.hashing import sha256_file
from aipos.ocr import OcrEngine
from aipos.parsing import parse_pdf
from aipos.storage import FileRecord, FileStatus, SQLiteStorage
from aipos.vector_store import VectorStore

logger = logging.getLogger(__name__)


def register_file(path: Path, storage: SQLiteStorage) -> FileRecord | None:
    """Register a completed file by its content hash.

    Computes the file's SHA-256. If a file with that hash is already registered,
    the file is skipped and None is returned. Otherwise a new row is inserted
    with status 'pending' and the created record is returned.
    """
    file_hash = sha256_file(path)
    existing = storage.get_file_by_hash(file_hash)
    if existing is not None:
        logger.info("Already registered (hash seen); skipping: %s", path)
        return None
    file_id = storage.add_file(path=str(path), file_hash=file_hash)
    logger.info("Registered file id=%d: %s", file_id, path)
    return storage.get_file(file_id)


def process_file(
    path: Path,
    storage: SQLiteStorage,
    embedder: Embedder,
    vector_store: VectorStore,
    ocr: OcrEngine,
    extractor: EntityExtractor,
) -> None:
    """Register a completed file and, if it is a PDF, process it.

    Registration dedupes by content hash. A newly registered PDF is parsed
    (falling back to OCR when it has no text layer), chunked, its chunks
    persisted, one embedding generated per chunk and stored in the vector store
    keyed by chunk_id, then its entities and relationships extracted and
    persisted to the knowledge graph, driven through its lifecycle:
    PARSING -> [OCR] -> CHUNKING -> EMBEDDING -> EXTRACTING -> READY on success,
    or FAILED (with the error recorded) on failure. Non-PDF files are left
    pending for a later parser (TXT/Markdown), and duplicates are skipped.
    """
    record = register_file(path, storage)
    if record is None:
        return  # duplicate content, already registered
    if path.suffix.lower() != ".pdf":
        return  # only PDFs are parsed in this ticket
    _process_pdf(record.id, path, storage, embedder, vector_store, ocr, extractor)


def _process_pdf(
    file_id: int,
    path: Path,
    storage: SQLiteStorage,
    embedder: Embedder,
    vector_store: VectorStore,
    ocr: OcrEngine,
    extractor: EntityExtractor,
) -> None:
    """Run a freshly registered PDF through the full pipeline (T2.1..T4.2).

    Composed of the two stages T6.1 split out below so crash recovery can reuse
    the second stage on its own, without re-parsing or re-chunking.
    """
    if not _parse_and_chunk(file_id, path, storage, ocr):
        return
    _embed_extract(file_id, path, storage, embedder, vector_store, extractor)


def _parse_and_chunk(
    file_id: int,
    path: Path,
    storage: SQLiteStorage,
    ocr: OcrEngine,
) -> bool:
    """Parse a PDF (falling back to OCR) and persist its chunks.

    Drives PARSING -> [OCR] -> CHUNKING (Design Doc §A5). Returns True once
    chunks are persisted; False if any step failed — the file is already
    marked FAILED with the error recorded, and the caller should stop.
    """
    storage.update_status(file_id, FileStatus.PARSING)
    try:
        text = parse_pdf(path)
    except Exception as error:
        logger.exception("PDF parse failed: %s", path)
        storage.update_status(file_id, FileStatus.FAILED, error=str(error))
        return False

    if not text.strip():
        # No extractable text layer — likely a scanned PDF. Recover text via
        # OCR before chunking (Design Doc §A5, the `ocr` step).
        storage.update_status(file_id, FileStatus.OCR)
        try:
            text = ocr.ocr_pdf(path)
        except Exception as error:
            logger.exception("OCR failed: %s", path)
            storage.update_status(file_id, FileStatus.FAILED, error=str(error))
            return False

    storage.update_status(file_id, FileStatus.CHUNKING)
    try:
        storage.add_chunks(file_id, chunk_text(text))
    except Exception as error:
        logger.exception("Chunking/persistence failed: %s", path)
        storage.update_status(file_id, FileStatus.FAILED, error=str(error))
        return False

    return True


def _embed_extract(
    file_id: int,
    path: Path,
    storage: SQLiteStorage,
    embedder: Embedder,
    vector_store: VectorStore,
    extractor: EntityExtractor,
) -> bool:
    """Embed a file's persisted chunks, extract its graph, and mark it ready.

    Drives EMBEDDING -> EXTRACTING -> READY (Design Doc §A5/§A4) over the
    chunks already persisted for ``file_id`` — fetched fresh here, so this
    stage stands alone for crash recovery (T6.1): it never re-parses or
    re-chunks. Returns True on success; False if any step failed — the file
    is already marked FAILED with the error recorded.
    """
    storage.update_status(file_id, FileStatus.EMBEDDING)
    try:
        # Embed the persisted chunks and store each vector keyed by chunk_id.
        records = storage.get_chunk_records(file_id)
        vectors = embedder.embed([record.text for record in records])
        vector_store.add(zip((record.id for record in records), vectors))
    except Exception as error:
        logger.exception("Embedding/vector persistence failed: %s", path)
        storage.update_status(file_id, FileStatus.FAILED, error=str(error))
        return False

    storage.update_status(file_id, FileStatus.EXTRACTING)
    try:
        # Extract entities and relationships per stored chunk (T4.1) and persist
        # them to the SQLite-backed knowledge graph (T4.2) — together the
        # `extracting` lifecycle step (Design Doc §A5/§A4). Extraction runs at
        # chunk granularity, so a relationship's weight counts how many chunks
        # produced it; storage upserts entities and edges on their identity
        # (accumulating edge weight) and resolves edge endpoints to ids.
        # Provenance (which chunk an entity came from) is
        # deferred — the frozen schema has no column for it (see Remaining
        # Technical Debt).
        extractions = [extractor.extract(record.text) for record in records]
        entities = [entity for result in extractions for entity in result.entities]
        relationships = [
            relationship
            for result in extractions
            for relationship in result.relationships
        ]
        storage.add_graph(entities, relationships)
    except Exception as error:
        logger.exception("Entity extraction/persistence failed: %s", path)
        storage.update_status(file_id, FileStatus.FAILED, error=str(error))
        return False

    storage.update_status(file_id, FileStatus.READY)
    logger.info(
        "Processed PDF id=%d (%d chunk(s), %d vector(s), "
        "%d entit(y/ies), %d relationship(s)): %s",
        file_id,
        len(records),
        len(vectors),
        len(entities),
        len(relationships),
        path,
    )
    return True


def resume_pending(
    storage: SQLiteStorage,
    embedder: Embedder,
    vector_store: VectorStore,
    ocr: OcrEngine,
    extractor: EntityExtractor,
) -> None:
    """Resume every file a previous run left mid-pipeline (T6.1).

    Sweeps ``storage.get_in_progress_files()`` — files started but not yet
    ready or failed — and resumes each from its last good state via
    ``_resume_file``: chunks already persisted are reused (never re-parsed or
    re-chunked); otherwise the file restarts cleanly from parsing. Intended to
    run once at startup, before the watcher begins accepting new files, so a
    killed-and-restarted process resumes cleanly (Design Doc §A5, PRD §7.1).

    Isolated per file: one file that fails to resume is marked FAILED (by the
    stage it fails in) and never blocks the rest of the sweep. Idempotent —
    once every in-progress file reaches READY or FAILED, a second call finds
    nothing to sweep and does nothing.
    """
    in_progress = storage.get_in_progress_files()
    if not in_progress:
        return
    logger.info(
        "Resuming %d file(s) left in progress by a previous run", len(in_progress)
    )
    for record in in_progress:
        try:
            _resume_file(record, storage, embedder, vector_store, ocr, extractor)
        except Exception:
            # Defensive safety net beyond each stage's own error handling, so a
            # truly unexpected failure for one file can never halt the sweep.
            logger.exception(
                "Unexpected error resuming file id=%d: %s", record.id, record.path
            )


def retry_file(
    file_id: int,
    storage: SQLiteStorage,
    embedder: Embedder,
    vector_store: VectorStore,
    ocr: OcrEngine,
    extractor: EntityExtractor,
) -> None:
    """Retry a failed file on request (T6.1; Design Doc §A3's ``retry_file``).

    A no-op — logged, not raised — for an unknown file id or a file whose
    status is not FAILED; retry is only meaningful for a failed file. A
    successful retry resumes from the last good state exactly like
    ``resume_pending``'s per-file logic, and the previous error is cleared
    automatically once a new status is written (``update_status``'s existing
    behaviour).
    """
    record = storage.get_file(file_id)
    if record is None:
        logger.info("Retry requested for unknown file id=%d; skipping", file_id)
        return
    if record.status != FileStatus.FAILED:
        logger.info(
            "Retry requested for file id=%d but status is %s (not failed); skipping",
            file_id,
            record.status,
        )
        return
    _resume_file(record, storage, embedder, vector_store, ocr, extractor)


def _resume_file(
    record: FileRecord,
    storage: SQLiteStorage,
    embedder: Embedder,
    vector_store: VectorStore,
    ocr: OcrEngine,
    extractor: EntityExtractor,
) -> None:
    """Resume or retry one file from its last good state (T6.1).

    If chunks already exist for the file, parsing/OCR/chunking are known to
    have already completed — skip straight to embedding/extraction, never
    re-parsing or re-chunking (chunk storage does not deduplicate, T2.4).
    Otherwise restart cleanly from parsing: parsing/OCR are pure reads with no
    DB side effects, so redoing them is always safe.
    """
    path = Path(record.path)
    if storage.get_chunk_records(record.id):
        _embed_extract(record.id, path, storage, embedder, vector_store, extractor)
        return
    if not _parse_and_chunk(record.id, path, storage, ocr):
        return
    _embed_extract(record.id, path, storage, embedder, vector_store, extractor)
