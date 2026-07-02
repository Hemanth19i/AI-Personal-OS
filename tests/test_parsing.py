"""Behaviour tests for PDF text extraction."""

import tempfile
import unittest
from pathlib import Path

from aipos.parsing import parse_pdf
from tests.pdf_fixtures import make_text_pdf, write_blank_pdf


class ParsePdfTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_extracts_text_from_pdf(self) -> None:
        pdf = self.root / "doc.pdf"
        pdf.write_bytes(make_text_pdf("Hello World"))
        self.assertIn("Hello World", parse_pdf(pdf))

    def test_blank_pdf_returns_empty_text(self) -> None:
        pdf = self.root / "blank.pdf"
        write_blank_pdf(pdf)
        self.assertEqual(parse_pdf(pdf).strip(), "")

    def test_corrupted_pdf_raises(self) -> None:
        pdf = self.root / "bad.pdf"
        pdf.write_bytes(b"this is not a pdf at all")
        with self.assertRaises(Exception):
            parse_pdf(pdf)


if __name__ == "__main__":
    unittest.main()
