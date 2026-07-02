"""Embedding generation for AI Personal OS.

Turns chunk text into vectors and nothing else — no SQL, no storage, no
retrieval. The runtime backend is a local Ollama model (nomic-embed-text, per
PRD §9 and config); the model name is injected, so this module never reads
config or touches storage.

This is the embedding half of the frozen "Model Manager" (Build Plan T2.3);
the LLM half arrives with reasoning (T3.3) and can be unified there. Callers
depend on the ``Embedder`` protocol, so tests can inject a deterministic fake
instead of requiring a running Ollama service.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# A vector is a list of floats; a batch call returns one vector per input text.
Vector = list[float]


@runtime_checkable
class Embedder(Protocol):
    """Produces one embedding vector per input text, in order."""

    def embed(self, texts: list[str]) -> list[Vector]:
        ...


class OllamaEmbedder:
    """Embedder backed by a local Ollama model (default: nomic-embed-text).

    Offline and local — it talks only to a local Ollama server, never a cloud
    API. ``ollama`` is imported lazily so the module (and the app) load even
    when the client/server is absent; a missing backend surfaces when ``embed``
    is called, which the coordinator records as a file failure.
    """

    def __init__(self, model: str, *, host: str | None = None) -> None:
        self._model = model
        self._host = host

    def embed(self, texts: list[str]) -> list[Vector]:
        import ollama

        client = ollama.Client(host=self._host) if self._host else ollama
        return [
            client.embeddings(model=self._model, prompt=text)["embedding"]
            for text in texts
        ]
