"""PDF text extraction for AI Personal OS.

Extracts the text layer from a PDF and nothing else — no OCR (that lives in
``aipos.ocr`` and the coordinator invokes it as a fallback), no chunking, no
persistence. Raises if the file cannot be read as a PDF so the ingestion
coordinator can mark the file failed (Build Plan, text extraction).
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


def parse_pdf(path: Path) -> str:
    """Return the concatenated text of a PDF's pages.

    Raises if ``path`` is not a readable PDF. A valid PDF with no text layer
    (e.g. a scanned image) returns an empty string; OCR is a later ticket.
    """
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)
