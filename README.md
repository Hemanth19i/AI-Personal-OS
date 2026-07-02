# AI Personal OS

An offline-first intelligence platform that turns your personal files (PDF, TXT,
Markdown) into structured, searchable, explainable knowledge — entirely on your
own device. No cloud, no API keys, no data leaving the machine.

> **Documents are inputs. Knowledge is the product.**

This repository is being built in phases against a frozen set of contract
documents. Phase 1 is a desktop-only flagship MVP: drop a document, have it
indexed locally, ask questions, receive cited answers, and understand *why*
those answers were produced.

## Status

Phase 1 — **Milestone 2 complete** (T0.1–T2.7). The full ingestion lifecycle
runs end to end: a watched folder holds each new file until its write completes,
then hashes (SHA-256) and registers it in SQLite (skipping already-seen
content). A registered PDF is parsed — falling back to Tesseract OCR when it has
no text layer (a scanned document) — chunked, embedded via a local Ollama model,
and its vectors written to LanceDB keyed by chunk id, reaching `ready`. Next up
is Milestone 3 (ask a question, get a cited answer). See the Build Plan for the
ticket list.

OCR requires the Tesseract binary installed on the system (Windows:
`winget install --id UB-Mannheim.TesseractOCR`; Debian/Ubuntu:
`apt install tesseract-ocr`); the Python packages come from `requirements.txt`.

## Contract documents

These are the single source of truth for the architecture and scope:

- [Product Requirements](AI_Personal_OS_PRD.md)
- [Architecture Decision Records](AI_Personal_OS_ADR.md)
- [Design Document](AI_Personal_OS_Design_Doc.md)
- [Phase 1 Build Plan](AI_Personal_OS_Phase1_Build_Plan.md)
- [TODO](todo.md)

## Getting started

Requires Python 3.13.

```bash
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
python main.py
```

On startup it creates `config.toml`, the `data/` directory, and the SQLite
database on first run, prints its readiness banner, then watches the configured
folder until you stop it with Ctrl+C:

```
AI Personal OS — alive
```

Drop a PDF, TXT, or Markdown file into `data/watched/` and it is registered in
the database once its write completes; dropping the same content again is
skipped.

## Running the tests

```bash
python -m unittest discover -s tests
```

