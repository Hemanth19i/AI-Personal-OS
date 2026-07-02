"""In-memory OCR engines for tests (no Tesseract or rasterizer required)."""

from __future__ import annotations

from pathlib import Path


class RecordingOcr:
    """Returns a fixed text and records every path it was asked to OCR.

    Lets a test both assert what OCR recovered and check whether OCR ran at
    all (a PDF with a real text layer must never reach it).
    """

    def __init__(self, text: str = "") -> None:
        self._text = text
        self.calls: list[Path] = []

    def ocr_pdf(self, path: Path) -> str:
        self.calls.append(path)
        return self._text


class FailingOcr:
    """Always raises, to exercise the OCR failure path."""

    def ocr_pdf(self, path: Path) -> str:
        raise RuntimeError("OCR backend unavailable")
