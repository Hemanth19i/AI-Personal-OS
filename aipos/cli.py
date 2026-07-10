"""Command-line interface for AI Personal OS.

Home for user-facing commands that operate on an already-built index, keeping
``main.py`` focused purely on watcher startup. Today it exposes ``ask`` (the
T3.3 answer command) and ``retry`` (the T6.1 crash-recovery command);
``watch``/``index``/``status``/``doctor``/``benchmark`` land here in later
milestones.

``ask`` wires the read path — embedder, vector store, storage, retriever,
reranker, and LLM — into an ``AnswerService`` and prints the grounded answer
with its sources. ``retry`` wires the ingest dependencies and calls
``aipos.ingest.retry_file`` for a failed file, printing its resulting status —
the CLI stands in for the ``Retry`` button the not-yet-built Library UI
pillar will eventually own (Design Doc §B4). Both commands separate wiring
from rendering so tests can drive them with fakes (no Ollama, no LanceDB).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aipos.answering import AnswerResult, AnswerService
from aipos.config import load_config
from aipos.embedding import Embedder, OllamaEmbedder
from aipos.explainability import Explanation
from aipos.extraction import EntityExtractor, LLMEntityExtractor
from aipos.graph_retrieval import GraphExpander, GraphRetriever, RoutedRetriever
from aipos.ingest import retry_file
from aipos.intent import HeuristicIntentRouter
from aipos.llm import OllamaLLM
from aipos.ocr import OcrEngine, TesseractOcr
from aipos.paths import database_path, ensure_app_directories, vector_store_path
from aipos.reranking import LexicalReranker
from aipos.retrieval import SemanticRetriever
from aipos.storage import FileRecord, SQLiteStorage
from aipos.vector_store import LanceVectorStore, VectorStore

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# The ingest dependencies retry_file needs, in the order it takes them.
IngestDependencies = tuple[SQLiteStorage, Embedder, VectorStore, OcrEngine, EntityExtractor]


def render_answer(result: AnswerResult) -> str:
    """Format an ``AnswerResult`` for the terminal (answer + sources + grounding)."""
    lines = [result.answer, "", "Sources:"]
    if result.sources:
        for source in result.sources:
            lines.append(f"  [{source.chunk_id}] {source.file} — {source.snippet}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append(f"Grounded: {'yes' if result.grounded else 'no'}")
    return "\n".join(lines)


def render_explanation(explanation: Explanation) -> str:
    """Format an ``Explanation`` for the terminal (the T5.1-T5.3 reasoning trace)."""
    graph = (
        f"{explanation.graph_relation_count} relation(s)"
        if explanation.graph_expanded
        else "skipped"
    )
    if not explanation.llm_consulted:
        llm = "not consulted (no context)"
    elif explanation.grounded:
        llm = "grounded answer generated"
    else:
        llm = "answer generated (not grounded)"
    evidence = explanation.evidence
    return "\n".join(
        [
            "Explanation:",
            f"  Strategy:        {explanation.strategy}",
            f"  Reason:          {explanation.reason}",
            f"  Retrieved:       {explanation.retrieved_count} chunk(s)",
            f"  Graph expansion: {graph}",
            f"  Reranker:        {explanation.reranked_count} reranked",
            f"  LLM:             {llm}",
            f"  Sources:         {explanation.citation_count} citation(s)",
            f"  Confidence:      {explanation.confidence.value}",
            f"  Timestamp:       {explanation.timestamp}",
            "",
            "Evidence",
            "---------",
            f"Verified: {'yes' if evidence.verified else 'no'}",
            f"Reason: {evidence.reason}",
            f"Verified citations: {evidence.verified_citations}/{evidence.total_citations}",
        ]
    )


def run_ask(question: str, service: AnswerService, *, explain: bool = False) -> str:
    """Answer ``question`` and render it, optionally with its reasoning trace."""
    result = service.answer(question)
    output = render_answer(result)
    if explain:
        output = f"{output}\n\n{render_explanation(result.explanation)}"
    return output


def render_retry_result(file_id: int, record: FileRecord | None) -> str:
    """Format the outcome of a retry attempt for the terminal (T6.1)."""
    if record is None:
        return f"No file with id={file_id}."
    lines = [f"File id={file_id}: {record.status.value}"]
    if record.error:
        lines.append(f"Error: {record.error}")
    return "\n".join(lines)


def run_retry(
    file_id: int,
    storage: SQLiteStorage,
    embedder: Embedder,
    vector_store: VectorStore,
    ocr: OcrEngine,
    extractor: EntityExtractor,
) -> str:
    """Retry a failed file and render its resulting status (T6.1)."""
    retry_file(file_id, storage, embedder, vector_store, ocr, extractor)
    return render_retry_result(file_id, storage.get_file(file_id))


def _build_answer_service() -> AnswerService:
    """Wire the real read-path dependencies from config."""
    config = load_config(PROJECT_ROOT)
    ensure_app_directories(config)

    storage = SQLiteStorage(database_path(config))
    storage.connect()

    vector_store = LanceVectorStore(vector_store_path(config))
    vector_store.connect()

    embedder = OllamaEmbedder(config.embedding_model)
    semantic = SemanticRetriever(embedder, vector_store, storage)
    graph = GraphRetriever(semantic, GraphExpander(storage))
    # Intent routing (T4.4): a heuristic router picks the semantic or graph path
    # per query, upstream of answer generation.
    retriever = RoutedRetriever(HeuristicIntentRouter(), semantic, graph)
    reranker = LexicalReranker()
    llm = OllamaLLM(config.llm_model)
    return AnswerService(retriever, reranker, llm, storage)


def _build_ingest_dependencies() -> IngestDependencies:
    """Wire the real ingestion dependencies from config (for ``retry``)."""
    config = load_config(PROJECT_ROOT)
    ensure_app_directories(config)

    storage = SQLiteStorage(database_path(config))
    storage.connect()

    vector_store = LanceVectorStore(vector_store_path(config))
    vector_store.connect()

    embedder = OllamaEmbedder(config.embedding_model)
    ocr = TesseractOcr()
    extractor = LLMEntityExtractor(OllamaLLM(config.llm_model))
    return storage, embedder, vector_store, ocr, extractor


def main(
    argv: list[str] | None = None,
    *,
    service: AnswerService | None = None,
    ingest_deps: IngestDependencies | None = None,
) -> int:
    """CLI entry point. Inject ``service``/``ingest_deps`` to bypass real-backend wiring (tests)."""
    # Force UTF-8 output: on Windows, stdout defaults to a legacy code page
    # (e.g. cp1252) which mangles the em dash / ellipsis in rendered answers.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(prog="aipos", description="AI Personal OS")
    subparsers = parser.add_subparsers(dest="command", required=True)
    ask_parser = subparsers.add_parser("ask", help="Answer a question from the corpus")
    ask_parser.add_argument("question", help="The question to answer")
    ask_parser.add_argument(
        "--explain",
        action="store_true",
        help="Also show the reasoning trace behind the answer",
    )
    retry_parser = subparsers.add_parser("retry", help="Retry a failed file")
    retry_parser.add_argument(
        "file_id", type=int, help="The id of the failed file to retry"
    )
    args = parser.parse_args(argv)

    if args.command == "ask":
        answer_service = service if service is not None else _build_answer_service()
        print(run_ask(args.question, answer_service, explain=args.explain), flush=True)
        return 0
    if args.command == "retry":
        storage, embedder, vector_store, ocr, extractor = (
            ingest_deps if ingest_deps is not None else _build_ingest_dependencies()
        )
        print(
            run_retry(args.file_id, storage, embedder, vector_store, ocr, extractor),
            flush=True,
        )
        return 0
    return 1  # unreachable: argparse enforces a known command


if __name__ == "__main__":
    raise SystemExit(main())
