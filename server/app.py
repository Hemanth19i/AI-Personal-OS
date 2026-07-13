"""Core API routes (W1): the engine's existing capabilities over HTTP.

Every handler is a thin translation layer: open per-request engine handles via
``Runtime``, call the same public functions the CLI calls, map the result onto
the contract models in ``server.schemas``. No SQL, no LanceDB, no pipeline
logic lives here — a handler that grows beyond translation belongs in the
engine, behind its protocols.

Write paths are exactly the CLI's: ``retry`` delegates to
``aipos.ingest.retry_file`` (ingest stays the sole write coordinator) and
``workspace import`` to ``aipos.backup.import_workspace`` (which refuses a
non-empty install — surfaced as 409, the guardrail as reassurance).
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from aipos import backup, ingest
from aipos.storage import DEFAULT_WORKSPACE_ID, FileRecord, FileStatus

# The document types the engine accepts (config: PDF/TXT/Markdown). Only PDFs
# are parsed today (T2.x); a TXT/Markdown upload registers and waits, exactly
# as the folder watcher leaves it — the API mirrors the engine, never guesses.
ACCEPTED_SUFFIXES = {".pdf", ".txt", ".md"}

from server import __version__
from server.schemas import (
    AnswerResponse,
    AskRequest,
    ChunkModel,
    DocumentModel,
    EdgeModel,
    EntityModel,
    EntityPageResponse,
    EvidenceModel,
    ExplanationModel,
    HealthResponse,
    MessageResponse,
    RetryResponse,
    SearchHit,
    SourceModel,
)
from server.wiring import Runtime

logger = logging.getLogger(__name__)


def _document(record: FileRecord) -> DocumentModel:
    return DocumentModel(
        id=record.id,
        workspace_id=record.workspace_id,
        path=record.path,
        hash=record.hash,
        status=str(record.status),
        error=record.error,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _dir_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _unique_path(directory: Path, filename: str) -> Path:
    """A non-colliding path in ``directory`` for ``filename`` (basename only)."""
    stem = Path(filename).stem or "document"
    suffix = Path(filename).suffix
    candidate = directory / f"{stem}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


def create_app(runtime: Runtime) -> FastAPI:
    """Build the Core API application around an engine ``Runtime``."""
    app = FastAPI(
        title="AI Personal OS — Core API",
        version=__version__,
        description=(
            "Local-only API wrapping the AI Personal OS engine (ADR-017). "
            "The contract is the boundary; HTTP is the first transport."
        ),
    )

    # The web client's dev/preview origins only (W2). Everything is loopback;
    # this exists solely because the Vite dev server runs on its own port.
    # Widening this list is a deliberate decision, never a convenience.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- system ---------------------------------------------------------------

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        db = runtime.database_path
        return HealthResponse(
            status="ok",
            version=__version__,
            embedding_model=runtime.config.embedding_model,
            llm_model=runtime.config.llm_model,
            database_bytes=db.stat().st_size if db.exists() else 0,
            vector_store_bytes=_dir_bytes(runtime.vector_store_dir),
        )

    # -- ask ------------------------------------------------------------------

    @app.post("/ask", response_model=AnswerResponse)
    def ask(request: AskRequest) -> AnswerResponse:
        with runtime.open_storage() as storage:
            vector_store = runtime.open_vector_store()
            service = runtime.build_answer_service(storage, vector_store)
            try:
                result = service.answer(request.question, k=request.k)
            except Exception as error:  # backend (e.g. Ollama) unavailable
                logger.exception("answer generation failed")
                raise HTTPException(
                    status_code=502, detail=f"Generation backend unavailable: {error}"
                ) from error
        explanation = result.explanation
        return AnswerResponse(
            answer=result.answer,
            sources=[
                SourceModel(chunk_id=s.chunk_id, file=s.file, snippet=s.snippet)
                for s in result.sources
            ],
            grounded=result.grounded,
            explanation=ExplanationModel(
                timestamp=explanation.timestamp,
                strategy=explanation.strategy,
                reason=explanation.reason,
                retrieved_count=explanation.retrieved_count,
                graph_expanded=explanation.graph_expanded,
                graph_relation_count=explanation.graph_relation_count,
                reranked_count=explanation.reranked_count,
                llm_consulted=explanation.llm_consulted,
                grounded=explanation.grounded,
                citation_count=explanation.citation_count,
                confidence=str(explanation.confidence),
                evidence=EvidenceModel(
                    verified=explanation.evidence.verified,
                    reason=explanation.evidence.reason,
                    verified_citations=explanation.evidence.verified_citations,
                    total_citations=explanation.evidence.total_citations,
                ),
            ),
        )

    # -- documents --------------------------------------------------------------

    @app.get("/documents", response_model=list[DocumentModel])
    def list_documents() -> list[DocumentModel]:
        # Composed from the engine's existing per-status query (W1 exposes
        # existing capabilities only); a dedicated list-all can arrive later as
        # an additive storage method without changing this route's contract.
        with runtime.open_storage() as storage:
            records = [
                record
                for status in FileStatus
                for record in storage.list_files_by_status(status)
            ]
        records.sort(key=lambda record: record.id)
        return [_document(record) for record in records]

    @app.post("/documents", response_model=DocumentModel, status_code=202)
    async def add_document(file: UploadFile) -> DocumentModel:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in ACCEPTED_SUFFIXES:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported type {suffix or '(none)'}; accepts PDF, TXT, Markdown",
            )
        # Save into the watched folder under a sanitized, collision-free name,
        # streaming to disk (no whole-file buffering in RAM).
        runtime.config.watched_folder.mkdir(parents=True, exist_ok=True)
        destination = _unique_path(runtime.config.watched_folder, Path(file.filename).name)
        with destination.open("wb") as sink:
            while chunk := await file.read(1 << 20):
                sink.write(chunk)

        # Register synchronously (fast: hash + one INSERT) so the document is
        # never lost between "uploaded" and "in the library"; defer the heavy
        # pipeline to the queue. Duplicate *content* is skipped by the engine.
        with runtime.open_storage() as storage:
            record = ingest.register_file(destination, storage)
        if record is None:
            destination.unlink(missing_ok=True)
            raise HTTPException(
                status_code=409, detail="This document is already in your library"
            )
        if suffix == ".pdf":
            runtime.submit_ingest_job(record.id, destination)
        return _document(record)

    @app.get("/documents/{document_id}", response_model=DocumentModel)
    def get_document(document_id: int) -> DocumentModel:
        with runtime.open_storage() as storage:
            record = storage.get_file(document_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"No document with id={document_id}")
        return _document(record)

    @app.get("/documents/{document_id}/chunks", response_model=list[ChunkModel])
    def get_document_chunks(document_id: int) -> list[ChunkModel]:
        with runtime.open_storage() as storage:
            record = storage.get_file(document_id)
            if record is None:
                raise HTTPException(
                    status_code=404, detail=f"No document with id={document_id}"
                )
            chunks = storage.get_chunk_records(document_id)
        return [ChunkModel(id=c.id, index=c.index, text=c.text) for c in chunks]

    @app.post("/documents/{document_id}/retry", response_model=RetryResponse)
    def retry_document(document_id: int) -> RetryResponse:
        with runtime.open_storage() as storage:
            record = storage.get_file(document_id)
            if record is None:
                raise HTTPException(
                    status_code=404, detail=f"No document with id={document_id}"
                )
            embedder, ocr, extractor = runtime.build_ingest_backends()
            vector_store = runtime.open_vector_store()
            ingest.retry_file(document_id, storage, embedder, vector_store, ocr, extractor)
            refreshed = storage.get_file(document_id)
        if refreshed is None:  # unreachable: retry never deletes the row
            raise HTTPException(status_code=500, detail="Document vanished during retry")
        return RetryResponse(id=refreshed.id, status=str(refreshed.status))

    # -- search -------------------------------------------------------------------

    @app.get("/search", response_model=list[SearchHit])
    def search(q: str, k: int = 5) -> list[SearchHit]:
        if not q.strip():
            raise HTTPException(status_code=422, detail="q must not be empty")
        if not 1 <= k <= 50:
            raise HTTPException(status_code=422, detail="k must be between 1 and 50")
        with runtime.open_storage() as storage:
            vector_store = runtime.open_vector_store()
            retriever = runtime.build_retriever(storage, vector_store)
            results = retriever.retrieve(q, k=k)
            sources = {
                source.chunk_id: source.file_path
                for source in storage.get_chunk_sources([r.chunk_id for r in results])
            }
        return [
            SearchHit(
                chunk_id=r.chunk_id,
                text=r.text,
                score=r.score,
                file=sources.get(r.chunk_id, ""),
            )
            for r in results
        ]

    # -- graph ----------------------------------------------------------------------

    @app.get("/graph/edges", response_model=list[EdgeModel])
    def graph_edges() -> list[EdgeModel]:
        with runtime.open_storage() as storage:
            edges = storage.get_edges()
        return [
            EdgeModel(
                id=e.id,
                source_entity_id=e.source_entity_id,
                target_entity_id=e.target_entity_id,
                relation=e.relation,
                weight=e.weight,
            )
            for e in edges
        ]

    @app.get("/graph/entity", response_model=EntityPageResponse)
    def entity_page(name: str) -> EntityPageResponse:
        with runtime.open_storage() as storage:
            entity = storage.get_entity_by_name(name)
            if entity is None:
                raise HTTPException(status_code=404, detail=f"No entity named {name!r}")
            neighbors = storage.get_neighbors(entity.id)
        return EntityPageResponse(
            entity=EntityModel(id=entity.id, name=entity.name, type=entity.type),
            neighbors=[
                EntityModel(id=n.id, name=n.name, type=n.type) for n in neighbors
            ],
        )

    # -- workspace ---------------------------------------------------------------------

    @app.get("/workspace/export")
    def export_workspace() -> FileResponse:
        handle = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        handle.close()
        destination = Path(handle.name)
        try:
            with runtime.open_storage() as storage:
                backup.export_workspace(
                    DEFAULT_WORKSPACE_ID, storage, runtime.vector_store_dir, destination
                )
        except Exception:
            os.remove(destination)  # don't leak the temp archive on failure
            raise
        return FileResponse(
            destination,
            filename="aipos-workspace.zip",
            media_type="application/zip",
            background=BackgroundTask(os.remove, destination),
        )

    @app.post(
        "/workspace/import",
        response_model=MessageResponse,
        responses={409: {"model": MessageResponse}, 400: {"model": MessageResponse}},
    )
    def import_workspace(archive: UploadFile) -> MessageResponse:
        # Sync handler (FastAPI runs it in a worker thread) so the upload can
        # stream to disk without buffering the whole archive in memory.
        handle = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        try:
            shutil.copyfileobj(archive.file, handle)
            handle.close()
            backup.import_workspace(
                Path(handle.name), runtime.database_path, runtime.vector_store_dir
            )
        except RuntimeError as error:  # refuses a non-empty install (T6.3)
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:  # not a valid workspace archive
            raise HTTPException(status_code=400, detail=str(error)) from error
        finally:
            handle.close()
            os.remove(handle.name)
        return MessageResponse(detail="Workspace imported")

    @app.on_event("shutdown")
    def _stop_ingestion() -> None:
        runtime.shutdown()

    return app
