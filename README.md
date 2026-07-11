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

Phase 1's MVP done-definition is **met**, end to end, via the CLI: drop a PDF/TXT/Markdown file
(including scanned PDFs via OCR) into the watched folder → it's hashed, parsed, chunked, embedded,
vector-indexed, and entity/relationship-extracted into a local knowledge graph, reaching `ready` —
then `python -m aipos.cli ask "..."` answers questions grounded in that corpus, with citations, a
GraphRAG-aware retrieval path, and a full explainability trace (`--explain`). Crash recovery, a
background task queue, and manual workspace export/import are all in place (Milestones 0–4, 5's
explainability half, and 6.1–6.3).

**Not yet built:** the desktop UI (Tauri+React), the event bus, and the System Health view — these
were deliberately deferred, not forgotten. See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the
current state and why, and [`docs/IDEAS.md`](docs/IDEAS.md) for what's deferred.

OCR requires the Tesseract binary installed on the system (Windows:
`winget install --id UB-Mannheim.TesseractOCR`; Debian/Ubuntu:
`apt install tesseract-ocr`); the Python packages come from `requirements.txt`.

## Documentation

| Document | Purpose |
|---|---|
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Current implementation roadmap — what's built, what's next, and why the plan diverged from the original |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Current architectural rules (the boundaries binding on new code) |
| [`docs/IDEAS.md`](docs/IDEAS.md) | Deferred ideas and future work — possibilities, not commitments |
| [`todo.md`](todo.md) | Living task tracker |
| [`docs/historical/`](docs/historical/) | Original Phase 1 planning documents (PRD, ADR, Design Doc, Build Plan) — frozen, for history only |

Start with [`docs/ROADMAP.md`](docs/ROADMAP.md); it links out to everything else and explains the
current state in full.

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

The default suite is dependency-free: every external backend (Ollama, LanceDB,
Tesseract) is covered by injected fakes, so it runs anywhere Python runs.

## Offline validation

The offline guarantee (nothing leaves the device — loopback to the local
Ollama daemon is allowed, anything else is not) is validated two ways:

**Automated (opt-in).** A socket-guard end-to-end test drives the real
pipeline — real SQLite, LanceDB, Ollama, and Tesseract, no fakes — while
blocking and recording any connection to a non-loopback host. It requires a
running Ollama daemon with the models named in `config.toml` pulled, plus the
Tesseract binary:

```bash
# Windows (PowerShell):
$env:AIPOS_RUN_OFFLINE_E2E = "1"; python -m unittest tests.test_offline_validation
# macOS / Linux:
AIPOS_RUN_OFFLINE_E2E=1 python -m unittest tests.test_offline_validation
```

The guard's own positive-control tests (proving it really blocks off-device
connections) run as part of the default suite with no external dependencies.

**Manual (network physically off).** The unconditional backstop: disable the
machine's network adapter (or unplug/turn off Wi-Fi), then run the full flow —
start `python main.py`, drop a PDF into `data/watched/`, wait for it to reach
`ready`, and ask a question with `python -m aipos.cli ask "..."`. Everything
works identically with the network off; the only network-capable component,
Ollama, is a local daemon reached over loopback.

