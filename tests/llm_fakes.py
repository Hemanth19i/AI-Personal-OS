"""In-memory LLMs for tests (no Ollama required)."""

from __future__ import annotations


class FakeLLM:
    """Returns a canned response and records the prompts it was given."""

    def __init__(self, response: str = "") -> None:
        self._response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._response


class FailingLLM:
    """Always raises, to exercise the generation failure path."""

    def generate(self, prompt: str) -> str:
        raise RuntimeError("LLM backend unavailable")
