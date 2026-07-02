"""OCR fallback for scanned PDFs (AI Personal OS).

Recovers text from PDFs that have no extractable text layer by rasterizing each
page and running Tesseract over the images — the ``ocr`` step of the file
lifecycle (Design Doc §A5; PRD §9 locks OCR to Tesseract). Invoked only when the
text-layer parser (``aipos.parsing``) comes back empty, so a scanned document
still reaches ``ready`` with real text instead of an empty chunk.

No SQL, no chunking, no persistence. Callers depend on the ``OcrEngine``
protocol, so tests inject a deterministic fake instead of requiring Tesseract
and a PDF rasterizer to be installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

# Rasterization resolution. 300 DPI is the accepted sweet spot for Tesseract
# accuracy on document scans without paying the memory cost of higher settings.
DEFAULT_DPI = 300

# PDF user space is defined at 72 units per inch; scale = DPI / 72 renders a
# page at the requested resolution.
_PDF_BASE_DPI = 72


@runtime_checkable
class OcrEngine(Protocol):
    """Extracts text from a scanned (image-only) PDF."""

    def ocr_pdf(self, path: Path) -> str:
        ...


class TesseractOcr:
    """OcrEngine backed by Tesseract, rasterizing pages with pypdfium2.

    Fully offline and local. ``pypdfium2`` (a self-contained wheel — no Poppler
    or other system binary) and ``pytesseract`` are imported lazily so this
    module and the app load even when they are absent; a missing rasterizer or
    Tesseract binary surfaces when ``ocr_pdf`` is called, which the ingestion
    coordinator records as a file failure (mirrors ``OllamaEmbedder`` and
    ``LanceVectorStore``).
    """

    def __init__(self, *, dpi: int = DEFAULT_DPI, language: str = "eng") -> None:
        self._dpi = dpi
        self._language = language

    def ocr_pdf(self, path: Path) -> str:
        """Return the OCR'd text of every page, joined by newlines."""
        import pypdfium2 as pdfium
        import pytesseract

        scale = self._dpi / _PDF_BASE_DPI
        pages_text: list[str] = []
        document = pdfium.PdfDocument(str(path))
        try:
            for page in document:
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil()
                try:
                    pages_text.append(
                        pytesseract.image_to_string(image, lang=self._language)
                    )
                finally:
                    image.close()
                    bitmap.close()
                    page.close()
        finally:
            document.close()
        return "\n".join(pages_text)
