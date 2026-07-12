"""Core API tests (W1).

A separate suite from ``tests/`` so the engine's default suite stays exactly
as it is; run from the repo root with:

    python -m unittest discover -s server/tests -t .

Dependency-light: needs ``fastapi``/``httpx`` (server/requirements.txt) but no
Ollama, no LanceDB, no Tesseract — every backend is a fake, reusing the
engine suite's fakes where they exist.
"""
