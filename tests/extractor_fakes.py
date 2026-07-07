"""In-memory entity extractors for tests (no Ollama required)."""

from __future__ import annotations

from aipos.extraction import Entity, ExtractionResult, Relationship


class RecordingExtractor:
    """Returns a fixed result and records every text it was asked to extract.

    Lets a test both assert what extraction produced and check that extraction
    ran (and how many times) during ingestion.
    """

    def __init__(self, result: ExtractionResult | None = None) -> None:
        self._result = result if result is not None else ExtractionResult([], [])
        self.calls: list[str] = []

    def extract(self, text: str) -> ExtractionResult:
        self.calls.append(text)
        return self._result


class FailingExtractor:
    """Always raises, to exercise the extraction failure path."""

    def extract(self, text: str) -> ExtractionResult:
        raise RuntimeError("extraction backend unavailable")


# A small, reusable non-empty result for integration assertions.
SAMPLE_RESULT = ExtractionResult(
    entities=[Entity(name="Alice", type="person"), Entity(name="ZTNA", type="concept")],
    relationships=[Relationship(source="Alice", target="ZTNA", relation="mentions")],
)
