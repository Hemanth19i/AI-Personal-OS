"""Behaviour tests for the CLI `ask` and `retry` commands (T3.3, T6.1).

`ask` is driven with a fake AnswerService so no Ollama/LanceDB/SQLite wiring
runs. `retry` uses a real temp SQLiteStorage (lightweight, no external binary)
with fake embedder/vector_store/ocr/extractor, mirroring test_ingest.py.
"""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from aipos import cli
from aipos.answering import AnswerResult, Source
from aipos.explainability import Confidence, EvidenceVerification, Explanation
from aipos.hashing import sha256_file
from aipos.storage import FileRecord, FileStatus, SQLiteStorage
from tests.embedder_fakes import DeterministicEmbedder
from tests.extractor_fakes import RecordingExtractor
from tests.ocr_fakes import RecordingOcr
from tests.pdf_fixtures import make_text_pdf
from tests.vector_store_fakes import RecordingVectorStore


class _FakeAnswerService:
    def __init__(self, result: AnswerResult) -> None:
        self._result = result
        self.questions: list[str] = []

    def answer(self, question: str) -> AnswerResult:
        self.questions.append(question)
        return self._result


_EXPLANATION = Explanation(
    timestamp="2026-01-02T03:04:05+00:00",
    strategy="semantic",
    reason="factual/summary query: 'who'",
    retrieved_count=5,
    graph_expanded=False,
    graph_relation_count=0,
    reranked_count=3,
    llm_consulted=True,
    grounded=True,
    citation_count=1,
    confidence=Confidence.MEDIUM,
    evidence=EvidenceVerification(
        verified=True, reason="all 1 cited chunk(s) are structurally valid",
        verified_citations=1, total_citations=1,
    ),
)

_GROUNDED = AnswerResult(
    answer="Alpha is the first letter.",
    sources=[Source(chunk_id=10, file="/docs/a.pdf", snippet="alpha text")],
    grounded=True,
    explanation=_EXPLANATION,
)
_UNGROUNDED = AnswerResult(
    answer="I don't know.", sources=[], grounded=False, explanation=_EXPLANATION
)


class RenderAnswerTests(unittest.TestCase):
    def test_renders_answer_sources_and_grounding(self) -> None:
        out = cli.render_answer(_GROUNDED)
        self.assertIn("Alpha is the first letter.", out)
        self.assertIn("[10] /docs/a.pdf — alpha text", out)
        self.assertIn("Grounded: yes", out)

    def test_renders_no_sources_and_not_grounded(self) -> None:
        out = cli.render_answer(_UNGROUNDED)
        self.assertIn("(none)", out)
        self.assertIn("Grounded: no", out)


class RenderExplanationTests(unittest.TestCase):
    def test_renders_observable_pipeline_decisions(self) -> None:
        out = cli.render_explanation(_EXPLANATION)
        self.assertIn("Explanation:", out)
        self.assertIn("Strategy:        semantic", out)
        self.assertIn("factual/summary query: 'who'", out)
        self.assertIn("Retrieved:       5 chunk(s)", out)
        self.assertIn("Graph expansion: skipped", out)
        self.assertIn("Sources:         1 citation(s)", out)
        self.assertIn("Confidence:      medium", out)
        self.assertIn("2026-01-02T03:04:05+00:00", out)
        self.assertIn("Evidence", out)
        self.assertIn("Verified: yes", out)
        self.assertIn("Reason: all 1 cited chunk(s) are structurally valid", out)
        self.assertIn("Verified citations: 1/1", out)

    def test_renders_unverified_evidence(self) -> None:
        unverified_explanation = Explanation(
            timestamp="2026-01-02T03:04:05+00:00", strategy="semantic", reason="x",
            retrieved_count=2, graph_expanded=False, graph_relation_count=0,
            reranked_count=2, llm_consulted=True, grounded=False, citation_count=0,
            confidence=Confidence.LOW,
            evidence=EvidenceVerification(
                verified=False, reason="answer is not grounded",
                verified_citations=0, total_citations=0,
            ),
        )
        out = cli.render_explanation(unverified_explanation)
        self.assertIn("Verified: no", out)
        self.assertIn("Reason: answer is not grounded", out)
        self.assertIn("Verified citations: 0/0", out)


class AskCommandTests(unittest.TestCase):
    def test_run_ask_invokes_service_and_renders(self) -> None:
        service = _FakeAnswerService(_GROUNDED)
        out = cli.run_ask("what is alpha?", service)
        self.assertEqual(service.questions, ["what is alpha?"])
        self.assertIn("Alpha is the first letter.", out)

    def test_run_ask_without_explain_omits_the_trace(self) -> None:
        out = cli.run_ask("q", _FakeAnswerService(_GROUNDED))
        self.assertNotIn("Explanation:", out)
        self.assertNotIn("Confidence:", out)  # confidence lives in the trace only
        self.assertNotIn("Evidence", out)  # evidence lives in the trace only

    def test_run_ask_with_explain_appends_the_trace(self) -> None:
        out = cli.run_ask("q", _FakeAnswerService(_GROUNDED), explain=True)
        self.assertIn("Alpha is the first letter.", out)  # answer still rendered
        self.assertIn("Explanation:", out)
        self.assertIn("Strategy:", out)

    def test_main_ask_dispatches_and_prints(self) -> None:
        service = _FakeAnswerService(_GROUNDED)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(["ask", "what is alpha?"], service=service)
        self.assertEqual(code, 0)
        self.assertEqual(service.questions, ["what is alpha?"])
        self.assertIn("Grounded: yes", buffer.getvalue())
        self.assertNotIn("Explanation:", buffer.getvalue())  # no flag -> no trace
        self.assertNotIn("Evidence", buffer.getvalue())

    def test_main_ask_explain_flag_dumps_the_trace(self) -> None:
        service = _FakeAnswerService(_GROUNDED)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(["ask", "what is alpha?", "--explain"], service=service)
        self.assertEqual(code, 0)
        self.assertIn("Explanation:", buffer.getvalue())
        self.assertIn("Evidence", buffer.getvalue())
        self.assertIn("Verified: yes", buffer.getvalue())


class RenderRetryResultTests(unittest.TestCase):
    def test_unknown_file(self) -> None:
        self.assertEqual(cli.render_retry_result(42, None), "No file with id=42.")

    def test_renders_status_and_error(self) -> None:
        record = FileRecord(
            id=7, workspace_id="default", path="/a.pdf", hash="h",
            status=FileStatus.FAILED, error="boom",
            created_at="t", updated_at="t",
        )
        out = cli.render_retry_result(7, record)
        self.assertIn("File id=7: failed", out)
        self.assertIn("Error: boom", out)

    def test_renders_status_without_error_line_when_none(self) -> None:
        record = FileRecord(
            id=7, workspace_id="default", path="/a.pdf", hash="h",
            status=FileStatus.READY, error=None,
            created_at="t", updated_at="t",
        )
        out = cli.render_retry_result(7, record)
        self.assertIn("File id=7: ready", out)
        self.assertNotIn("Error:", out)


class RetryCommandTests(unittest.TestCase):
    """Integration-level: real temp SQLiteStorage, fake embedder/vector_store/ocr/extractor."""

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

    def _seed_failed_file(self) -> int:
        pdf = self.root / "a.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        file_id = self.storage.add_file(path=str(pdf), file_hash=sha256_file(pdf))
        self.storage.update_status(file_id, FileStatus.FAILED, error="boom")
        return file_id

    def test_run_retry_reprocesses_a_failed_file(self) -> None:
        file_id = self._seed_failed_file()
        out = cli.run_retry(
            file_id, self.storage, self.embedder, self.vectors, self.ocr, self.extractor
        )
        self.assertIn(f"File id={file_id}: ready", out)
        self.assertIs(self.storage.get_file(file_id).status, FileStatus.READY)

    def test_run_retry_unknown_id(self) -> None:
        out = cli.run_retry(
            999999, self.storage, self.embedder, self.vectors, self.ocr, self.extractor
        )
        self.assertEqual(out, "No file with id=999999.")

    def test_main_retry_dispatches_and_prints(self) -> None:
        file_id = self._seed_failed_file()
        deps = (self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(["retry", str(file_id)], ingest_deps=deps)
        self.assertEqual(code, 0)
        self.assertIn(f"File id={file_id}: ready", buffer.getvalue())
        self.assertIs(self.storage.get_file(file_id).status, FileStatus.READY)

    def test_main_retry_unknown_id_dispatches_and_prints(self) -> None:
        deps = (self.storage, self.embedder, self.vectors, self.ocr, self.extractor)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(["retry", "999999"], ingest_deps=deps)
        self.assertEqual(code, 0)
        self.assertIn("No file with id=999999.", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
