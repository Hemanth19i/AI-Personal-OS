"""Deterministic in-memory embedders for tests (no Ollama required)."""

from __future__ import annotations

import hashlib


class DeterministicEmbedder:
    """Maps text to a stable vector via SHA-256.

    Identical text yields an identical vector; different text yields a
    (practically always) different vector — the properties a real embedder
    such as nomic-embed also has.
    """

    def __init__(self, dim: int = 8) -> None:
        self._dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [byte / 255.0 for byte in digest[: self._dim]]


class RecordingEmbedder:
    """Records each batch of texts it is asked to embed."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[0.0] for _ in texts]


class FailingEmbedder:
    """Always raises, to exercise the embedding failure path."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding backend unavailable")
