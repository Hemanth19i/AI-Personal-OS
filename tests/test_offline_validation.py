"""Offline validation for AI Personal OS (T6.5).

Proves the pipeline makes no **off-device** network connections (ADR-001:
"nothing leaves your device"). Loopback — ``localhost``, ``127.*``, ``::1`` —
is explicitly allowed, because Ollama is a local daemon: talking to it over
loopback is on-device communication, not egress.

The guard patches only ``socket.create_connection``, the single TCP connection
primitive used by the real pipeline's one socket user: the ``ollama`` client is
built on httpx/httpcore, and httpcore's sync backend opens every TCP connection
via ``socket.create_connection`` (httpcore/_backends/sync.py). Everything else
in the pipeline is local by construction — LanceDB is embedded (files on disk),
SQLite is a file, Tesseract is a subprocess, pypdfium2 is a local library.
``socket.socket.connect`` is deliberately NOT patched: ``create_connection``
calls it internally, so patching both would intercept the same connection
twice. DNS resolution (``socket.getaddrinfo``) is likewise out of scope by
design — data egress is the *connection*, which is what the guard sees.

Two tiers:

- The guard's positive control always runs: stdlib-only, no external backends,
  and no egress (a blocked attempt fails before any packet leaves).
- The real end-to-end validation is **opt-in** via ``AIPOS_RUN_OFFLINE_E2E=1``
  and uses the real SQLite / LanceDB / Ollama / Tesseract backends — no fakes.
  Model names are read from the project's existing config (``config.toml``),
  so the validation follows whatever models the project is configured to use.
  It asserts pipeline *completion* (file reaches READY, the LLM was consulted)
  and ``blocked_connections == []`` — not answer quality, which is a model
  property, not an offline property.

The complementary manual check — the network physically off — is documented in
README.md ("Offline validation"); this module is the automated regression
guard, the manual procedure is the unconditional backstop.
"""

from __future__ import annotations

import os
import socket
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class OffDeviceConnectionBlocked(OSError):
    """Raised by the guard when a connection targets a non-loopback host."""


def _is_loopback(host: str) -> bool:
    """True for on-device destinations: localhost, 127.0.0.0/8, IPv6 ::1."""
    return host == "localhost" or host == "::1" or host.startswith("127.")


class LoopbackOnlyGuard:
    """Context manager: allow loopback connections, block and record the rest.

    While active, ``socket.create_connection`` to a loopback host passes
    through to the real implementation unchanged; any other destination is
    appended to ``blocked_connections`` and fails with
    ``OffDeviceConnectionBlocked`` *before* a socket is opened, so the blocked
    attempt itself produces no egress. The original function is restored on
    exit, even on error.
    """

    def __init__(self) -> None:
        self.blocked_connections: list[tuple[str, object]] = []
        self._original: object = None

    def __enter__(self) -> "LoopbackOnlyGuard":
        original = socket.create_connection
        self._original = original

        def guarded_create_connection(address, *args, **kwargs):  # type: ignore[no-untyped-def]
            host, port = address[0], address[1]
            if _is_loopback(str(host)):
                return original(address, *args, **kwargs)
            self.blocked_connections.append((str(host), port))
            raise OffDeviceConnectionBlocked(
                f"blocked off-device connection to {host}:{port}"
            )

        socket.create_connection = guarded_create_connection
        return self

    def __exit__(self, *exc: object) -> None:
        socket.create_connection = self._original  # type: ignore[assignment]


def _closed_loopback_port() -> int:
    """Return a loopback port that is (momentarily) not accepting connections."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]  # released on close; nothing listens


class LoopbackOnlyGuardTests(unittest.TestCase):
    """Positive control: proves the guard actually blocks and actually allows.

    Without this, a broken (no-op) guard would let the end-to-end validation
    pass vacuously. No external backends, no egress.
    """

    def test_off_device_connection_is_blocked_and_recorded(self) -> None:
        original = socket.create_connection
        with LoopbackOnlyGuard() as guard:
            with self.assertRaises(OffDeviceConnectionBlocked):
                socket.create_connection(("8.8.8.8", 53), timeout=0.1)
        self.assertEqual(guard.blocked_connections, [("8.8.8.8", 53)])
        # The guard restores the real function on exit — no leakage into
        # other tests.
        self.assertIs(socket.create_connection, original)

    def test_loopback_connection_passes_through_and_is_not_recorded(self) -> None:
        # A refused loopback connection proves delegation to the *real*
        # create_connection (the guard neither blocked nor swallowed it):
        # the OS, not the guard, raised.
        port = _closed_loopback_port()
        with LoopbackOnlyGuard() as guard:
            with self.assertRaises(ConnectionRefusedError):
                socket.create_connection(("127.0.0.1", port), timeout=5)
        self.assertEqual(guard.blocked_connections, [])


@unittest.skipUnless(
    os.environ.get("AIPOS_RUN_OFFLINE_E2E") == "1",
    "opt-in: set AIPOS_RUN_OFFLINE_E2E=1 (requires local Ollama with the "
    "configured models, and Tesseract)",
)
class OfflineEndToEndTests(unittest.TestCase):
    """The real pipeline, real backends, under the guard — no fakes.

    Drop → register → parse → chunk → embed (Ollama) → extract (Ollama) →
    READY, then ask → retrieve (LanceDB) → rerank → answer (Ollama), all inside
    ``LoopbackOnlyGuard``. Passing means every network interaction the whole
    flow performed was loopback.
    """

    def test_full_pipeline_makes_no_off_device_connections(self) -> None:
        from aipos import ingest
        from aipos.answering import AnswerResult, AnswerService
        from aipos.config import load_config
        from aipos.embedding import OllamaEmbedder
        from aipos.extraction import LLMEntityExtractor
        from aipos.graph_retrieval import GraphExpander, GraphRetriever, RoutedRetriever
        from aipos.hashing import sha256_file
        from aipos.intent import HeuristicIntentRouter
        from aipos.llm import OllamaLLM
        from aipos.ocr import TesseractOcr
        from aipos.reranking import LexicalReranker
        from aipos.retrieval import SemanticRetriever
        from aipos.storage import FileStatus, SQLiteStorage
        from aipos.vector_store import LanceVectorStore
        from tests.pdf_fixtures import make_text_pdf

        # Models come from the project's existing configuration, not from
        # hardcoded names — the validation follows whatever config.toml says.
        config = load_config(PROJECT_ROOT)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_path = root / "offline_validation.pdf"
            pdf_path.write_bytes(
                make_text_pdf("AI Personal OS processes every document locally")
            )

            storage = SQLiteStorage(root / "aipos.db")
            storage.connect()
            try:
                vector_store = LanceVectorStore(root / "vectors")
                vector_store.connect()

                # Real backends throughout — the exact wiring cli.py uses.
                embedder = OllamaEmbedder(config.embedding_model)
                llm = OllamaLLM(config.llm_model)
                semantic = SemanticRetriever(embedder, vector_store, storage)
                graph = GraphRetriever(semantic, GraphExpander(storage))
                retriever = RoutedRetriever(HeuristicIntentRouter(), semantic, graph)
                service = AnswerService(retriever, LexicalReranker(), llm, storage)

                with LoopbackOnlyGuard() as guard:
                    # Write path: the full ingestion lifecycle.
                    ingest.process_file(
                        pdf_path,
                        storage,
                        embedder,
                        vector_store,
                        TesseractOcr(),
                        LLMEntityExtractor(llm),
                    )
                    record = storage.get_file_by_hash(sha256_file(pdf_path))
                    self.assertIsNotNone(record)
                    # READY proves parse → chunk → embed → extract all
                    # completed against the real backends (a failure at any
                    # stage would leave FAILED or an intermediate status).
                    self.assertEqual(record.status, FileStatus.READY)

                    # Read path: retrieval + reranking + generation.
                    result = service.answer(
                        "Where does AI Personal OS process documents?"
                    )
            finally:
                storage.close()

        # Completion, not quality: the pipeline ran end to end, the LLM was
        # actually consulted, and nothing tried to leave the device.
        self.assertIsInstance(result, AnswerResult)
        self.assertTrue(result.explanation.llm_consulted)
        self.assertEqual(guard.blocked_connections, [])


if __name__ == "__main__":
    unittest.main()
