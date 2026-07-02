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
from aipos.hashing import sha256_file
from aipos.parsing import parse_pdf
from aipos.storage import FileRecord, FileStatus, SQLiteStorage

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


def process_file(path: Path, storage: SQLiteStorage, embedder: Embedder) -> None:
    """Register a completed file and, if it is a PDF, process it.

    Registration dedupes by content hash. A newly registered PDF is parsed,
    chunked, its chunks persisted, and one embedding generated per chunk,
    driven through its lifecycle: PARSING -> CHUNKING -> EMBEDDING -> READY on
    success, or FAILED (with the error recorded) on failure. Non-PDF files are
    left pending for a later parser (TXT/Markdown), and duplicates are skipped.
    """
    record = register_file(path, storage)
    if record is None:
        return  # duplicate content, already registered
    if path.suffix.lower() != ".pdf":
        return  # only PDFs are parsed in this ticket
    _process_pdf(record.id, path, storage, embedder)


def _process_pdf(
    file_id: int, path: Path, storage: SQLiteStorage, embedder: Embedder
) -> None:
    storage.update_status(file_id, FileStatus.PARSING)
    try:
        text = parse_pdf(path)
    except Exception as error:
        logger.exception("PDF parse failed: %s", path)
        storage.update_status(file_id, FileStatus.FAILED, error=str(error))
        return

    storage.update_status(file_id, FileStatus.CHUNKING)
    try:
        chunks = chunk_text(text)
        storage.add_chunks(file_id, chunks)
    except Exception as error:
        logger.exception("Chunking/persistence failed: %s", path)
        storage.update_status(file_id, FileStatus.FAILED, error=str(error))
        return

    storage.update_status(file_id, FileStatus.EMBEDDING)
    try:
        # One embedding per stored chunk. Persisting vectors (to LanceDB, keyed
        # by chunk_id) is the next ticket, so the vectors are not stored yet.
        embeddings = embedder.embed([chunk.text for chunk in chunks])
    except Exception as error:
        logger.exception("Embedding failed: %s", path)
        storage.update_status(file_id, FileStatus.FAILED, error=str(error))
        return

    storage.update_status(file_id, FileStatus.READY)
    logger.info(
        "Processed PDF id=%d (%d chunk(s), %d embedding(s)): %s",
        file_id,
        len(chunks),
        len(embeddings),
        path,
    )
