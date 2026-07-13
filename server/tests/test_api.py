"""Behaviour tests for the Core API (W1).

Real temp ``SQLiteStorage`` (lightweight, no external binary) + fakes for
every model/vector backend, injected through ``Runtime``'s factories exactly
the way ``cli.main`` accepts injected dependencies. The API is exercised
through FastAPI's ``TestClient`` — the same request path a real client takes.
"""

from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from aipos.chunking import Chunk
from aipos.extraction import Entity, ExtractionResult, Relationship
from aipos.storage import FileStatus, SQLiteStorage

from server.app import create_app
from server.wiring import Runtime
from tests.embedder_fakes import DeterministicEmbedder
from tests.extractor_fakes import RecordingExtractor
from tests.llm_fakes import FakeLLM
from tests.ocr_fakes import RecordingOcr
from tests.pdf_fixtures import make_text_pdf


class InlineTaskQueue:
    """Runs each submitted job synchronously — deterministic uploads in tests."""

    def submit(self, job) -> None:  # noqa: ANN001 - protocol signature
        job()

    def stop(self, *, wait: bool = False) -> None:
        pass


class SeededVectorStore:
    """Returns a configured ranking; records adds (no LanceDB)."""

    def __init__(self, hits: list[tuple[int, float]] | None = None) -> None:
        self.hits = hits or []
        self.added: list[tuple[int, list[float]]] = []

    def add(self, items) -> None:  # noqa: ANN001 - protocol signature
        self.added.extend((chunk_id, list(vector)) for chunk_id, vector in items)

    def search(self, query, k):  # noqa: ANN001 - protocol signature
        return self.hits[:k]


class ApiTestCase(unittest.TestCase):
    """A temp project root + a Runtime wired entirely onto fakes."""

    GROUNDED_REPLY = "Priya Nair designed GraphCore.\n\nUSED_CHUNKS:\n1"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.vector_store = SeededVectorStore()
        self.runtime = Runtime(
            self.root,
            embedder_factory=lambda: DeterministicEmbedder(),
            llm_factory=lambda: FakeLLM(self.GROUNDED_REPLY),
            ocr_factory=lambda: RecordingOcr(),
            extractor_factory=lambda: RecordingExtractor(),
            vector_store_factory=lambda: self.vector_store,
            task_queue_factory=InlineTaskQueue,
        )
        self.client = TestClient(create_app(self.runtime))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- seeding helpers -------------------------------------------------------

    def seed_document(
        self, *, status: FileStatus = FileStatus.READY, with_chunks: bool = True
    ) -> tuple[int, list[int]]:
        """Insert one file (and optionally two chunks); return (file_id, chunk_ids)."""
        with self.runtime.open_storage() as storage:
            file_id = storage.add_file(path="/docs/meridian.pdf", file_hash="h1")
            storage.update_status(file_id, status)
            chunk_ids: list[int] = []
            if with_chunks:
                storage.add_chunks(
                    file_id,
                    [
                        Chunk(index=0, text="Priya Nair designed GraphCore."),
                        Chunk(index=1, text="Lumen queries GraphCore."),
                    ],
                )
                chunk_ids = [c.id for c in storage.get_chunk_records(file_id)]
        return file_id, chunk_ids

    def seed_graph(self) -> None:
        with self.runtime.open_storage() as storage:
            storage.add_graph(
                [Entity(name="GraphCore", type="concept"),
                 Entity(name="Priya Nair", type="person")],
                [Relationship(source="Priya Nair", relation="designed", target="GraphCore")],
            )


class HealthTests(ApiTestCase):
    def test_cors_allows_the_web_dev_origin_only(self) -> None:
        allowed = self.client.get("/health", headers={"Origin": "http://localhost:5173"})
        self.assertEqual(
            allowed.headers.get("access-control-allow-origin"), "http://localhost:5173"
        )
        foreign = self.client.get("/health", headers={"Origin": "http://evil.example"})
        self.assertIsNone(foreign.headers.get("access-control-allow-origin"))

    def test_health_reports_ok_and_configured_models(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["embedding_model"], self.runtime.config.embedding_model)
        self.assertEqual(payload["llm_model"], self.runtime.config.llm_model)
        self.assertTrue(payload["offline"])


class AskTests(ApiTestCase):
    def test_ask_returns_grounded_cited_answer_with_explanation(self) -> None:
        _, chunk_ids = self.seed_document()
        self.vector_store.hits = [(chunk_ids[0], 0.05)]

        response = self.client.post("/ask", json={"question": "Who designed GraphCore?"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("Priya Nair", payload["answer"])
        self.assertTrue(payload["grounded"])
        self.assertEqual(payload["sources"][0]["chunk_id"], chunk_ids[0])
        explanation = payload["explanation"]
        self.assertTrue(explanation["llm_consulted"])
        self.assertEqual(explanation["citation_count"], 1)
        self.assertIn(explanation["strategy"], ("semantic", "graph"))
        self.assertEqual(explanation["evidence"]["total_citations"], 1)

    def test_ask_with_empty_corpus_is_honest_not_an_error(self) -> None:
        response = self.client.post("/ask", json={"question": "Anything at all?"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["grounded"])
        self.assertEqual(payload["sources"], [])
        self.assertFalse(payload["explanation"]["llm_consulted"])

    def test_ask_rejects_blank_question(self) -> None:
        self.assertEqual(
            self.client.post("/ask", json={"question": ""}).status_code, 422
        )


class DocumentTests(ApiTestCase):
    def test_list_documents_returns_seeded_files_sorted_by_id(self) -> None:
        file_id, _ = self.seed_document()
        response = self.client.get("/documents")
        self.assertEqual(response.status_code, 200)
        documents = response.json()
        self.assertEqual([d["id"] for d in documents], [file_id])
        self.assertEqual(documents[0]["status"], "ready")

    def test_get_document_and_404(self) -> None:
        file_id, _ = self.seed_document()
        self.assertEqual(
            self.client.get(f"/documents/{file_id}").json()["path"],
            "/docs/meridian.pdf",
        )
        self.assertEqual(self.client.get("/documents/99999").status_code, 404)

    def test_document_chunks_and_404(self) -> None:
        file_id, chunk_ids = self.seed_document()
        chunks = self.client.get(f"/documents/{file_id}/chunks").json()
        self.assertEqual([c["id"] for c in chunks], chunk_ids)
        self.assertEqual(self.client.get("/documents/99999/chunks").status_code, 404)


class UploadTests(ApiTestCase):
    def test_upload_pdf_registers_and_processes_to_ready(self) -> None:
        pdf = make_text_pdf("GraphCore connects entities across documents")
        response = self.client.post(
            "/documents",
            files={"file": ("meridian.pdf", pdf, "application/pdf")},
        )
        self.assertEqual(response.status_code, 202)
        document_id = response.json()["id"]
        # The inline queue ran the pipeline synchronously with fakes.
        self.assertEqual(
            self.client.get(f"/documents/{document_id}").json()["status"], "ready"
        )
        listed = self.client.get("/documents").json()
        self.assertEqual([d["id"] for d in listed], [document_id])
        self.assertTrue(self.vector_store.added)

    def test_upload_rejects_unsupported_type(self) -> None:
        response = self.client.post(
            "/documents",
            files={"file": ("notes.docx", b"x", "application/octet-stream")},
        )
        self.assertEqual(response.status_code, 415)

    def test_upload_duplicate_content_is_409(self) -> None:
        pdf = make_text_pdf("the same bytes twice")
        first = self.client.post("/documents", files={"file": ("a.pdf", pdf, "application/pdf")})
        self.assertEqual(first.status_code, 202)
        again = self.client.post("/documents", files={"file": ("b.pdf", pdf, "application/pdf")})
        self.assertEqual(again.status_code, 409)

    def test_upload_txt_registers_but_stays_pending(self) -> None:
        # Honest mirror of the engine: TXT is accepted and registered, but not
        # yet parsed, so it waits at pending — never silently "processing".
        response = self.client.post(
            "/documents",
            files={"file": ("notes.txt", b"plain text", "text/plain")},
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "pending")


class RetryTests(ApiTestCase):
    def test_retry_runs_failed_file_back_to_ready(self) -> None:
        # A real (tiny) PDF on disk so the resumed pipeline can re-parse it.
        pdf_path = self.root / "doc.pdf"
        pdf_path.write_bytes(make_text_pdf("GraphCore connects entities across documents"))
        with self.runtime.open_storage() as storage:
            file_id = storage.add_file(path=str(pdf_path), file_hash="h-retry")
            storage.update_status(file_id, FileStatus.FAILED, error="boom")

        response = self.client.post(f"/documents/{file_id}/retry")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": file_id, "status": "ready"})
        self.assertTrue(self.vector_store.added)  # embeddings were persisted

    def test_retry_is_a_noop_for_a_ready_file(self) -> None:
        file_id, _ = self.seed_document(status=FileStatus.READY)
        response = self.client.post(f"/documents/{file_id}/retry")
        self.assertEqual(response.json()["status"], "ready")

    def test_retry_unknown_id_is_404(self) -> None:
        self.assertEqual(self.client.post("/documents/424242/retry").status_code, 404)


class SearchTests(ApiTestCase):
    def test_search_returns_ranked_hits_with_text(self) -> None:
        _, chunk_ids = self.seed_document()
        self.vector_store.hits = [(chunk_ids[1], 0.02), (chunk_ids[0], 0.08)]
        response = self.client.get("/search", params={"q": "GraphCore", "k": 2})
        self.assertEqual(response.status_code, 200)
        hits = response.json()
        self.assertEqual([h["chunk_id"] for h in hits], [chunk_ids[1], chunk_ids[0]])
        self.assertIn("Lumen", hits[0]["text"])

    def test_search_rejects_blank_query_and_bad_k(self) -> None:
        self.assertEqual(self.client.get("/search", params={"q": "  "}).status_code, 422)
        self.assertEqual(
            self.client.get("/search", params={"q": "x", "k": 0}).status_code, 422
        )


class GraphTests(ApiTestCase):
    def test_entity_page_returns_entity_and_neighbors(self) -> None:
        self.seed_graph()
        response = self.client.get("/graph/entity", params={"name": "GraphCore"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["entity"]["name"], "GraphCore")
        self.assertEqual([n["name"] for n in payload["neighbors"]], ["Priya Nair"])

    def test_unknown_entity_is_404_and_edges_list(self) -> None:
        self.seed_graph()
        self.assertEqual(
            self.client.get("/graph/entity", params={"name": "Nobody"}).status_code, 404
        )
        edges = self.client.get("/graph/edges").json()
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["relation"], "designed")
        self.assertEqual(edges[0]["weight"], 1)


class WorkspaceTests(ApiTestCase):
    def test_export_streams_a_valid_zip(self) -> None:
        self.seed_document()
        response = self.client.get("/workspace/export")
        self.assertEqual(response.status_code, 200)
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        self.assertIn("aipos.db", archive.namelist())

    def test_import_into_clean_install_restores_documents(self) -> None:
        file_id, _ = self.seed_document()
        exported = self.client.get("/workspace/export").content

        with tempfile.TemporaryDirectory() as clean_root:
            clean_runtime = Runtime(
                Path(clean_root),
                embedder_factory=lambda: DeterministicEmbedder(),
                llm_factory=lambda: FakeLLM(""),
                ocr_factory=lambda: RecordingOcr(),
                extractor_factory=lambda: RecordingExtractor(),
                vector_store_factory=lambda: SeededVectorStore(),
            )
            clean_client = TestClient(create_app(clean_runtime))
            response = clean_client.post(
                "/workspace/import",
                files={"archive": ("w.zip", exported, "application/zip")},
            )
            self.assertEqual(response.status_code, 200)
            documents = clean_client.get("/documents").json()
            self.assertEqual([d["id"] for d in documents], [file_id])

    def test_import_refuses_a_non_empty_install_with_409(self) -> None:
        self.seed_document()  # this install now has a database
        exported = self.client.get("/workspace/export").content
        response = self.client.post(
            "/workspace/import",
            files={"archive": ("w.zip", exported, "application/zip")},
        )
        self.assertEqual(response.status_code, 409)

    def test_import_rejects_a_bogus_archive_with_400(self) -> None:
        bogus = io.BytesIO()
        with zipfile.ZipFile(bogus, "w") as archive:
            archive.writestr("readme.txt", "not a workspace")
        with tempfile.TemporaryDirectory() as clean_root:
            clean_runtime = Runtime(
                Path(clean_root),
                embedder_factory=lambda: DeterministicEmbedder(),
                llm_factory=lambda: FakeLLM(""),
                ocr_factory=lambda: RecordingOcr(),
                extractor_factory=lambda: RecordingExtractor(),
                vector_store_factory=lambda: SeededVectorStore(),
            )
            clean_client = TestClient(create_app(clean_runtime))
            response = clean_client.post(
                "/workspace/import",
                files={"archive": ("b.zip", bogus.getvalue(), "application/zip")},
            )
            self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
