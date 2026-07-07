"""Ingestion coordinator for AI Personal OS.

Orchestrates the ingestion pipeline for a completed file, tying together the
hashing utility, the storage layer, and the PDF parser without any of them
knowing about the others. Two responsibilities live here as application logic:
the "skip if the hash is already registered" decision (T1.4) and driving the
file through its lifecycle during parsing (T2.2).

Called for each file that has passed the write-completion guard.
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
    keyed by chunk_id, then its entities and relationships extracted, driven
    through its lifecycle:
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
    storage.update_status(file_id, FileStatus.PARSING)
    try:
        text = parse_pdf(path)
    except Exception as error:
        logger.exception("PDF parse failed: %s", path)
        storage.update_status(file_id, FileStatus.FAILED, error=str(error))
        return

    if not text.strip():
        # No extractable text layer — likely a scanned PDF. Recover text via
        # OCR before chunking (Design Doc §A5, the `ocr` step).
        storage.update_status(file_id, FileStatus.OCR)
        try:
            text = ocr.ocr_pdf(path)
        except Exception as error:
            logger.exception("OCR failed: %s", path)
            storage.update_status(file_id, FileStatus.FAILED, error=str(error))
            return

    storage.update_status(file_id, FileStatus.CHUNKING)
    try:
        storage.add_chunks(file_id, chunk_text(text))
    except Exception as error:
        logger.exception("Chunking/persistence failed: %s", path)
        storage.update_status(file_id, FileStatus.FAILED, error=str(error))
        return

    storage.update_status(file_id, FileStatus.EMBEDDING)
    try:
        # Embed the persisted chunks and store each vector keyed by chunk_id.
        records = storage.get_chunk_records(file_id)
        vectors = embedder.embed([record.text for record in records])
        vector_store.add(zip((record.id for record in records), vectors))
    except Exception as error:
        logger.exception("Embedding/vector persistence failed: %s", path)
        storage.update_status(file_id, FileStatus.FAILED, error=str(error))
        return

    storage.update_status(file_id, FileStatus.EXTRACTING)
    try:
        # Extract entities and relationships per stored chunk (T4.1, the
        # `extracting` lifecycle step, Design Doc §A5). Extraction runs at chunk
        # granularity — over each ChunkRecord.text, not the concatenated
        # document — so later milestones (T4.2–T4.4) can attach chunk-level
        # provenance for GraphRAG, graph retrieval, and neighbour expansion. The
        # results are surfaced via logging here; persisting them to the frozen
        # entities/edges tables is T4.2 and is intentionally not done yet (see
        # Remaining Technical Debt).
        extractions = [extractor.extract(record.text) for record in records]
    except Exception as error:
        logger.exception("Entity extraction failed: %s", path)
        storage.update_status(file_id, FileStatus.FAILED, error=str(error))
        return

    entity_count = sum(len(result.entities) for result in extractions)
    relationship_count = sum(len(result.relationships) for result in extractions)

    storage.update_status(file_id, FileStatus.READY)
    logger.info(
        "Processed PDF id=%d (%d chunk(s), %d vector(s), "
        "%d entit(y/ies), %d relationship(s)): %s",
        file_id,
        len(records),
        len(vectors),
        entity_count,
        relationship_count,
        path,
    )
