"""Local text generation for AI Personal OS.

Turns a prompt into generated text and nothing else — no SQL, no storage, no
retrieval, no prompt construction. The runtime backend is a local Ollama model
(llama3.1, per PRD §9 and config); the model name is injected, so this module
never reads config or touches storage.

This is the LLM half of the frozen "Model Manager" (Build Plan T2.3/T3.3); the
embedding half lives in ``aipos.embedding`` and mirrors this shape. Callers
depend on the ``LLM`` protocol, so tests can inject a deterministic fake instead
of requiring a running Ollama service.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLM(Protocol):
    """Generates a text completion for a single prompt."""

    def generate(self, prompt: str) -> str:
        ...


class OllamaLLM:
    """LLM backed by a local Ollama model (default: llama3.1).

    Offline and local — it talks only to a local Ollama server, never a cloud
    API. ``ollama`` is imported lazily so the module (and the app) load even
    when the client/server is absent; a missing backend surfaces when
    ``generate`` is called, which the caller surfaces as an answer failure.
    """

    def __init__(self, model: str, *, host: str | None = None) -> None:
        self._model = model
        self._host = host

    def generate(self, prompt: str) -> str:
        import ollama

        client = ollama.Client(host=self._host) if self._host else ollama
        return client.generate(model=self._model, prompt=prompt)["response"]
