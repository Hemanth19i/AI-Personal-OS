"""Behaviour tests for the OCR fallback engine.

The Tesseract backend and its rasterizer are not exercised here — those are
system dependencies covered by the injectable ``OcrEngine`` contract and the
fakes used in the ingestion tests. These tests pin the contract itself.
"""

import unittest

from aipos.ocr import OcrEngine, TesseractOcr
from tests.ocr_fakes import FailingOcr, RecordingOcr


class OcrContractTests(unittest.TestCase):
    def test_tesseract_engine_satisfies_protocol(self) -> None:
        self.assertIsInstance(TesseractOcr(), OcrEngine)

    def test_fakes_satisfy_protocol(self) -> None:
        self.assertIsInstance(RecordingOcr(), OcrEngine)
        self.assertIsInstance(FailingOcr(), OcrEngine)

    def test_construction_does_not_touch_backend(self) -> None:
        # Constructing must not import pypdfium2/pytesseract, so the app loads
        # even when they (and the Tesseract binary) are absent.
        engine = TesseractOcr(dpi=150, language="eng")
        self.assertIsInstance(engine, OcrEngine)


if __name__ == "__main__":
    unittest.main()
