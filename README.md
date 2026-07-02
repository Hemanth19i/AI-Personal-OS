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

Phase 1 — **Milestone 1 complete** (T0.1–T1.4). The ingestion front door works
end to end: a folder is watched, each new file is held until its write
completes, then hashed (SHA-256) and registered in SQLite, skipping files whose
content is already registered. Milestone 2 (parsing → chunks → vectors) is next.
See the Build Plan for the ticket list.

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

