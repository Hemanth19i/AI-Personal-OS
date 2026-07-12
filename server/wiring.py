"""Engine wiring for the Core API (W1).

Builds the same dependency graphs ``aipos.cli`` builds — per request, from
config, constructor-injected — so the API is just another client of the
frozen engine. No globals, no singletons: a ``Runtime`` instance is created
once per application (``server.app.create_app``) and holds *factories*, not
live connections; every request opens and closes its own ``SQLiteStorage``
(sqlite3 connections are not safe to share across threads — the same rule
``main.py``'s worker jobs follow) and its own vector-store handle.

Tests inject fake factories (no Ollama, no LanceDB, no Tesseract), mirroring
how ``cli.main`` accepts injected dependencies.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from aipos.answering import AnswerService
from aipos.config import AppConfig, load_config
from aipos.embedding import Embedder, OllamaEmbedder
from aipos.extraction import EntityExtractor, LLMEntityExtractor
from aipos.graph_retrieval import GraphExpander, GraphRetriever, RoutedRetriever
from aipos.intent import HeuristicIntentRouter
from aipos.llm import LLM, OllamaLLM
from aipos.ocr import OcrEngine, TesseractOcr
from aipos.paths import database_path, ensure_app_directories, vector_store_path
from aipos.reranking import LexicalReranker
from aipos.retrieval import SemanticRetriever
from aipos.storage import SQLiteStorage
from aipos.vector_store import LanceVectorStore, VectorStore


class Runtime:
    """Per-application factory bundle for the engine's real (or fake) backends.

    ``embedder``/``llm``/``ocr``/``extractor`` factories default to the real
    local backends (Ollama, Tesseract) exactly as ``cli.py`` wires them; the
    ``vector_store`` factory defaults to a connected ``LanceVectorStore``.
    Passing alternatives swaps the whole API onto fakes for tests.
    """

    def __init__(
        self,
        project_root: Path,
        *,
        embedder_factory: Callable[[], Embedder] | None = None,
        llm_factory: Callable[[], LLM] | None = None,
        ocr_factory: Callable[[], OcrEngine] | None = None,
        extractor_factory: Callable[[], EntityExtractor] | None = None,
        vector_store_factory: Callable[[], VectorStore] | None = None,
    ) -> None:
        self.project_root = project_root
        self.config: AppConfig = load_config(project_root)
        ensure_app_directories(self.config)

        self._embedder_factory = embedder_factory or (
            lambda: OllamaEmbedder(self.config.embedding_model)
        )
        self._llm_factory = llm_factory or (lambda: OllamaLLM(self.config.llm_model))
        self._ocr_factory = ocr_factory or TesseractOcr
        self._extractor_factory = extractor_factory or (
            lambda: LLMEntityExtractor(self._llm_factory())
        )
        self._vector_store_factory = vector_store_factory or self._connect_lance

    # -- paths ---------------------------------------------------------------

    @property
    def database_path(self) -> Path:
        return database_path(self.config)

    @property
    def vector_store_dir(self) -> Path:
        return vector_store_path(self.config)

    # -- per-request construction ---------------------------------------------

    def open_storage(self) -> SQLiteStorage:
        """A fresh storage handle; use as a context manager per request."""
        return SQLiteStorage(self.database_path)

    def open_vector_store(self) -> VectorStore:
        return self._vector_store_factory()

    def build_embedder(self) -> Embedder:
        return self._embedder_factory()

    def build_ingest_backends(self) -> tuple[Embedder, OcrEngine, EntityExtractor]:
        """The stateless per-call backends ``ingest.retry_file`` needs."""
        return self._embedder_factory(), self._ocr_factory(), self._extractor_factory()

    def build_retriever(
        self, storage: SQLiteStorage, vector_store: VectorStore
    ) -> SemanticRetriever:
        return SemanticRetriever(self._embedder_factory(), vector_store, storage)

    def build_answer_service(
        self, storage: SQLiteStorage, vector_store: VectorStore
    ) -> AnswerService:
        """The full read path, wired exactly as ``cli._build_answer_service``."""
        semantic = self.build_retriever(storage, vector_store)
        graph = GraphRetriever(semantic, GraphExpander(storage))
        retriever = RoutedRetriever(HeuristicIntentRouter(), semantic, graph)
        return AnswerService(retriever, LexicalReranker(), self._llm_factory(), storage)

    def _connect_lance(self) -> VectorStore:
        store = LanceVectorStore(self.vector_store_dir)
        store.connect()
        return store
