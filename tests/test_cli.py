"""Behaviour tests for the CLI `ask` command (T3.3).

Driven with a fake AnswerService so no Ollama/LanceDB/SQLite wiring runs.
"""

import io
import unittest
from contextlib import redirect_stdout

from aipos import cli
from aipos.answering import AnswerResult, Source
from aipos.explainability import Confidence, Explanation


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

    def test_main_ask_explain_flag_dumps_the_trace(self) -> None:
        service = _FakeAnswerService(_GROUNDED)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(["ask", "what is alpha?", "--explain"], service=service)
        self.assertEqual(code, 0)
        self.assertIn("Explanation:", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
