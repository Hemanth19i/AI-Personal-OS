"""Behaviour tests for answer generation (T3.3).

Exercised through the real DI surface: a fake retriever + passthrough reranker +
FakeLLM + a real temp SQLiteStorage (so citation file lookup runs for real). No
Ollama, no LanceDB.
"""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from aipos.answering import AnswerService, Source
from aipos.chunking import Chunk
from aipos.explainability import Confidence, Explanation
from aipos.graph_retrieval import ExpandedRetrievalResult, RetrievalExecution
from aipos.intent import RoutingDecision, Strategy
from aipos.retrieval import RetrievalResult
from aipos.storage import GraphRelation, SQLiteStorage
from tests.llm_fakes import FailingLLM, FakeLLM


class _FixedClock:
    """Deterministic clock for asserting the Explanation timestamp."""

    def __init__(self, moment: datetime | None = None) -> None:
        self._moment = moment or datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._moment


class _FakeRetriever:
    """Returns a canned RetrievalExecution and records the (question, k)."""

    def __init__(
        self,
        results: list[RetrievalResult],
        graph_context: list[GraphRelation] | None = None,
        *,
        strategy: Strategy = Strategy.SEMANTIC,
        reason: str = "test-reason",
    ) -> None:
        self._results = results
        self._graph_context = graph_context if graph_context is not None else []
        self._decision = RoutingDecision(strategy, reason)
        self.calls: list[tuple[str, int]] = []

    def retrieve(self, query: str, *, k: int) -> RetrievalExecution:
        self.calls.append((query, k))
        return RetrievalExecution(
            routing=self._decision,
            result=ExpandedRetrievalResult(
                chunks=list(self._results), graph_context=list(self._graph_context)
            ),
        )


class _PassthroughReranker:
    """Returns candidates unchanged, so citation positions are predictable."""

    def rerank(self, query: str, results: list[RetrievalResult]) -> list[RetrievalResult]:
        return list(results)


class AnswerServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self._tmp.name) / "aipos.db")
        self.storage.connect()
        self.file_id = self.storage.add_file(path="/docs/a.pdf", file_hash="h")
        self.storage.add_chunks(
            self.file_id, [Chunk(0, "alpha text"), Chunk(1, "beta text"), Chunk(2, "gamma text")]
        )
        self.records = self.storage.get_chunk_records(self.file_id)
        self.results = [
            RetrievalResult(chunk_id=r.id, text=r.text, score=0.1 * i)
            for i, r in enumerate(self.records)
        ]
        self.reranker = _PassthroughReranker()

    def tearDown(self) -> None:
        self.storage.close()
        self._tmp.cleanup()

    def _service(
        self, llm, results=None, graph_context=None, *,
        strategy=Strategy.SEMANTIC, reason="test-reason", clock=None, confidence=None,
    ) -> AnswerService:
        retriever = _FakeRetriever(
            results if results is not None else self.results, graph_context,
            strategy=strategy, reason=reason,
        )
        self._retriever = retriever
        return AnswerService(
            retriever, self.reranker, llm, self.storage,
            clock=clock, confidence=confidence,
        )

    def test_grounded_answer_with_cited_sources(self) -> None:
        llm = FakeLLM("The answer is alpha and gamma.\nUSED_CHUNKS:\n1,3")
        result = self._service(llm).answer("what?")
        self.assertTrue(result.grounded)
        self.assertEqual(result.answer, "The answer is alpha and gamma.")  # footer stripped
        self.assertEqual([s.chunk_id for s in result.sources], [self.records[0].id, self.records[2].id])
        self.assertTrue(all(s.file == "/docs/a.pdf" for s in result.sources))
        self.assertIsInstance(result.sources[0], Source)
        self.assertIn("alpha text", result.sources[0].snippet)

    def test_none_footer_is_not_grounded(self) -> None:
        llm = FakeLLM("I don't know.\nUSED_CHUNKS:\nNONE")
        result = self._service(llm).answer("what?")
        self.assertFalse(result.grounded)
        self.assertEqual(result.sources, [])
        self.assertEqual(result.answer, "I don't know.")

    def test_missing_footer_is_not_grounded(self) -> None:
        llm = FakeLLM("A confident answer with no footer at all.")
        result = self._service(llm).answer("what?")
        self.assertFalse(result.grounded)
        self.assertEqual(result.sources, [])
        self.assertEqual(result.answer, "A confident answer with no footer at all.")

    def test_out_of_range_footer_is_not_grounded(self) -> None:
        llm = FakeLLM("Answer.\nUSED_CHUNKS:\n9,42")  # only 3 chunks exist
        result = self._service(llm).answer("what?")
        self.assertFalse(result.grounded)
        self.assertEqual(result.sources, [])

    def test_empty_retrieval_short_circuits_without_llm(self) -> None:
        llm = FakeLLM("should never be called")
        result = self._service(llm, results=[]).answer("what?")
        self.assertFalse(result.grounded)
        self.assertEqual(result.sources, [])
        self.assertEqual(llm.prompts, [])  # LLM was never consulted

    def test_prompt_contains_context_and_grounding(self) -> None:
        llm = FakeLLM("x\nUSED_CHUNKS:\n1")
        self._service(llm).answer("what is alpha?")
        prompt = llm.prompts[0]
        self.assertIn("alpha text", prompt)
        self.assertIn("what is alpha?", prompt)
        self.assertIn("USED_CHUNKS:", prompt)

    def test_duplicate_and_reordered_citations_dedupe_in_cited_order(self) -> None:
        llm = FakeLLM("Answer.\nUSED_CHUNKS:\n3,1,3")
        result = self._service(llm).answer("what?")
        self.assertEqual([s.chunk_id for s in result.sources], [self.records[2].id, self.records[0].id])

    def test_llm_failure_propagates(self) -> None:
        with self.assertRaises(RuntimeError):
            self._service(FailingLLM()).answer("what?")

    def test_answering_mutates_nothing(self) -> None:
        before = len(self.storage.get_chunk_records(self.file_id))
        self._service(FakeLLM("a\nUSED_CHUNKS:\n1")).answer("what?")
        self.assertEqual(len(self.storage.get_chunk_records(self.file_id)), before)

    def test_k_is_forwarded_to_retriever(self) -> None:
        service = self._service(FakeLLM("a\nUSED_CHUNKS:\n1"))
        service.answer("what?", k=7)
        self.assertEqual(self._retriever.calls[0][1], 7)

    # --- graph context (T4.3) ---

    def test_graph_context_appears_in_prompt(self) -> None:
        gc = [GraphRelation("alpha", "relates_to", "beta", 2)]
        llm = FakeLLM("x\nUSED_CHUNKS:\n1")
        self._service(llm, graph_context=gc).answer("what?")
        self.assertIn("alpha relates_to beta", llm.prompts[0])

    def test_graph_context_never_becomes_a_source(self) -> None:
        # Graph context enriches the prompt but is never a citation source;
        # sources still resolve only from the cited chunks.
        gc = [GraphRelation("alpha", "relates_to", "beta", 2)]
        llm = FakeLLM("Answer.\nUSED_CHUNKS:\n1")
        result = self._service(llm, graph_context=gc).answer("what?")
        self.assertEqual([s.chunk_id for s in result.sources], [self.records[0].id])
        self.assertTrue(all(s.file == "/docs/a.pdf" for s in result.sources))

    def test_no_graph_context_leaves_prompt_without_a_graph_section(self) -> None:
        llm = FakeLLM("x\nUSED_CHUNKS:\n1")
        self._service(llm).answer("what?")
        self.assertNotIn("knowledge graph", llm.prompts[0].lower())

    # --- explanation (T5.1) ---

    def test_grounded_answer_carries_a_deterministic_explanation(self) -> None:
        clock = _FixedClock()
        llm = FakeLLM("Answer.\nUSED_CHUNKS:\n1,3")
        result = self._service(
            llm, strategy=Strategy.SEMANTIC, reason="factual", clock=clock
        ).answer("what?")
        exp = result.explanation
        self.assertIsInstance(exp, Explanation)
        self.assertEqual(exp.strategy, "semantic")
        self.assertEqual(exp.reason, "factual")
        self.assertEqual(exp.retrieved_count, 3)
        self.assertFalse(exp.graph_expanded)
        self.assertEqual(exp.graph_relation_count, 0)
        self.assertEqual(exp.reranked_count, 3)
        self.assertTrue(exp.llm_consulted)
        self.assertTrue(exp.grounded)
        self.assertEqual(exp.citation_count, 2)
        self.assertEqual(exp.timestamp, clock.now().isoformat())

    def test_graph_strategy_explanation_reports_expansion(self) -> None:
        gc = [GraphRelation("alpha", "relates_to", "beta", 2)]
        llm = FakeLLM("Answer.\nUSED_CHUNKS:\n1")
        result = self._service(
            llm, graph_context=gc, strategy=Strategy.GRAPH, reason="relationship keyword"
        ).answer("how?")
        exp = result.explanation
        self.assertEqual(exp.strategy, "graph")
        self.assertTrue(exp.graph_expanded)
        self.assertEqual(exp.graph_relation_count, 1)

    def test_no_context_explanation_reports_llm_not_consulted(self) -> None:
        result = self._service(FakeLLM("never"), results=[]).answer("what?")
        exp = result.explanation
        self.assertEqual(exp.retrieved_count, 0)
        self.assertEqual(exp.reranked_count, 0)
        self.assertFalse(exp.llm_consulted)
        self.assertFalse(exp.grounded)
        self.assertEqual(exp.citation_count, 0)

    def test_ungrounded_explanation_consulted_llm_but_no_citations(self) -> None:
        result = self._service(FakeLLM("Answer.\nUSED_CHUNKS:\nNONE")).answer("what?")
        exp = result.explanation
        self.assertTrue(exp.llm_consulted)
        self.assertFalse(exp.grounded)
        self.assertEqual(exp.citation_count, 0)
        self.assertEqual(exp.reranked_count, 3)

    def test_default_clock_timestamp_is_iso_utc(self) -> None:
        result = self._service(FakeLLM("a\nUSED_CHUNKS:\n1")).answer("what?")
        parsed = datetime.fromisoformat(result.explanation.timestamp)
        self.assertIsNotNone(parsed.tzinfo)

    # --- confidence (T5.2) ---

    def test_no_context_confidence_is_none(self) -> None:
        result = self._service(FakeLLM("never"), results=[]).answer("what?")
        self.assertIs(result.explanation.confidence, Confidence.NONE)

    def test_ungrounded_confidence_is_low(self) -> None:
        result = self._service(FakeLLM("Answer.\nUSED_CHUNKS:\nNONE")).answer("what?")
        self.assertIs(result.explanation.confidence, Confidence.LOW)

    def test_grounded_two_citations_without_graph_is_medium(self) -> None:
        # SEMANTIC path: grounded, two citations, no graph support -> MEDIUM.
        result = self._service(FakeLLM("Answer.\nUSED_CHUNKS:\n1,3")).answer("what?")
        self.assertIs(result.explanation.confidence, Confidence.MEDIUM)

    def test_grounded_two_citations_with_graph_is_high(self) -> None:
        gc = [GraphRelation("alpha", "relates_to", "beta", 2)]
        result = self._service(
            FakeLLM("Answer.\nUSED_CHUNKS:\n1,3"), graph_context=gc,
            strategy=Strategy.GRAPH, reason="rel",
        ).answer("how?")
        self.assertIs(result.explanation.confidence, Confidence.HIGH)

    def test_grounded_single_citation_with_graph_is_medium(self) -> None:
        gc = [GraphRelation("alpha", "relates_to", "beta", 2)]
        result = self._service(
            FakeLLM("Answer.\nUSED_CHUNKS:\n1"), graph_context=gc,
            strategy=Strategy.GRAPH, reason="rel",
        ).answer("how?")
        self.assertIs(result.explanation.confidence, Confidence.MEDIUM)

    def test_confidence_calculator_is_injectable_and_used_verbatim(self) -> None:
        # A fake calculator is consulted with the observed facts and its verdict
        # is used as-is — AnswerService never second-guesses it.
        class _RecordingCalc:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def assess(self, **facts) -> Confidence:
                self.calls.append(facts)
                return Confidence.LOW

        calc = _RecordingCalc()
        result = self._service(
            FakeLLM("Answer.\nUSED_CHUNKS:\n1,3"), confidence=calc
        ).answer("what?")
        self.assertIs(result.explanation.confidence, Confidence.LOW)
        self.assertEqual(len(calc.calls), 1)
        facts = calc.calls[0]
        self.assertTrue(facts["llm_consulted"])
        self.assertTrue(facts["grounded"])
        self.assertEqual(facts["citation_count"], 2)
        self.assertEqual(facts["graph_relation_count"], 0)
        self.assertEqual(facts["retrieved_count"], 3)
        self.assertEqual(facts["reranked_count"], 3)


if __name__ == "__main__":
    unittest.main()
