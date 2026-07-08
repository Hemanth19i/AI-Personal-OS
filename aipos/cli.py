"""Command-line interface for AI Personal OS.

Home for user-facing commands that operate on an already-built index, keeping
``main.py`` focused purely on watcher startup. Today it exposes ``ask`` (the
T3.3 answer command); ``watch``/``index``/``status``/``doctor``/``benchmark``
land here in later milestones.

``ask`` wires the read path — embedder, vector store, storage, retriever,
reranker, and LLM — into an ``AnswerService`` and prints the grounded answer
with its sources. The wiring is separated from the rendering so tests can drive
the command with a fake ``AnswerService`` (no Ollama, no LanceDB).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aipos.answering import AnswerResult, AnswerService
from aipos.config import load_config
from aipos.embedding import OllamaEmbedder
from aipos.graph_retrieval import GraphExpander, GraphRetriever
from aipos.llm import OllamaLLM
from aipos.paths import database_path, ensure_app_directories, vector_store_path
from aipos.reranking import LexicalReranker
from aipos.retrieval import SemanticRetriever
from aipos.storage import SQLiteStorage
from aipos.vector_store import LanceVectorStore

PROJECT_ROOT = Path(__file__).resolve().parent.parent


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


def run_ask(question: str, service: AnswerService) -> str:
    """Answer ``question`` with the given service and return the rendered output."""
    return render_answer(service.answer(question))


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
    # Graph-aware retrieval (T4.3): semantic hits + graph context, composed
    # upstream of answer generation.
    retriever = GraphRetriever(semantic, GraphExpander(storage))
    reranker = LexicalReranker()
    llm = OllamaLLM(config.llm_model)
    return AnswerService(retriever, reranker, llm, storage)


def main(argv: list[str] | None = None, *, service: AnswerService | None = None) -> int:
    """CLI entry point. Inject ``service`` to bypass real-backend wiring (tests)."""
    # Force UTF-8 output: on Windows, stdout defaults to a legacy code page
    # (e.g. cp1252) which mangles the em dash / ellipsis in rendered answers.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(prog="aipos", description="AI Personal OS")
    subparsers = parser.add_subparsers(dest="command", required=True)
    ask_parser = subparsers.add_parser("ask", help="Answer a question from the corpus")
    ask_parser.add_argument("question", help="The question to answer")
    args = parser.parse_args(argv)

    if args.command == "ask":
        answer_service = service if service is not None else _build_answer_service()
        print(run_ask(args.question, answer_service), flush=True)
        return 0
    return 1  # unreachable: argparse enforces a known command


if __name__ == "__main__":
    raise SystemExit(main())
