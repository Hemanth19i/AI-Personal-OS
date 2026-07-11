# AI Personal OS

An offline-first intelligence platform that turns your personal files (PDF, TXT,
Markdown) into structured, searchable, explainable knowledge — entirely on your
own device. No cloud, no API keys, no data leaving the machine.

> **Documents are inputs. Knowledge is the product.**

AI Personal OS is a fully offline, local-first personal knowledge system. All
processing — including OCR, embeddings, retrieval, graph extraction, and answer
generation — runs on your own machine.

This repository is a phase-based build against a frozen set of contract
documents. Phase 1 is a desktop-only flagship MVP: drop a document, have it
indexed locally, ask questions, receive cited answers, and understand *why*
those answers were produced.

## Status

**Phase 1 is feature-complete via the CLI**, and its MVP done-definition is met
end to end: drop a PDF/TXT/Markdown file (including scanned PDFs via OCR) into
the watched folder → it's hashed, parsed, chunked, embedded, vector-indexed, and
entity/relationship-extracted into a local knowledge graph, reaching `ready` →
then `python -m aipos.cli ask "..."` answers questions grounded in that corpus,
with citations, a GraphRAG-aware retrieval path, and a full explainability trace
(`--explain`).

Shipped: ingestion + processing (M0–M2), vector RAG (M3), knowledge graph /
GraphRAG (M4), explainability (M5-Explainability), crash recovery, background
task queue, and workspace export/import (M6.1–M6.3), offline validation (M6.5),
and a model-evaluation performance pass (M7.1). The default generation model is
**`qwen2.5:3b`**, chosen by that evaluation (see [Performance](#performance)).
**Architecture Freeze v1.0** is in effect — see
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

**Not built (deliberately deferred, not forgotten):** the desktop UI
(Tauri+React), the event bus, and the System Health view. See
[`docs/ROADMAP.md`](docs/ROADMAP.md) for the current state and why, and
[`docs/IDEAS.md`](docs/IDEAS.md) for what's deferred. Known functional gaps are
listed under [Known limitations](#known-limitations).

## Documentation

| Document | Purpose |
|---|---|
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Current implementation roadmap — what's built, what's next, and why the plan diverged from the original |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Current architectural rules (the boundaries binding on new code) |
| [`docs/IDEAS.md`](docs/IDEAS.md) | Deferred ideas and future work — possibilities, not commitments |
| [`benchmarks/`](benchmarks/) | Reproducible performance + model-evaluation harness and results |
| [`todo.md`](todo.md) | Living task tracker |
| [`docs/historical/`](docs/historical/) | Original Phase 1 planning documents (PRD, ADR, Design Doc, Build Plan) — frozen, for history only |

Start with [`docs/ROADMAP.md`](docs/ROADMAP.md); it links out to everything else
and explains the current state in full.

## Requirements

- **Python 3.11+** (developed and tested on 3.13).
- **[Ollama](https://ollama.com)** — the local model runtime. Its daemon must be
  running, and two models must be pulled (see below). This is a separate system
  install, not a Python package.
- **Tesseract** — only needed to OCR *scanned* PDFs (image-only, no text layer).
  Text PDFs, TXT, and Markdown do not need it.

Everything runs locally; no network connection is required once the models are
pulled (see [Offline validation](#offline-validation)).

## Installation & quick start

### 1. Install and start Ollama, then pull the models

Install the Ollama runtime for your OS from <https://ollama.com/download> (or
`winget install Ollama.Ollama` on Windows, `brew install ollama` on macOS,
`curl -fsSL https://ollama.com/install.sh | sh` on Linux). With the Ollama
daemon running, pull the two models the app uses by default:

```bash
ollama pull qwen2.5:3b        # generation LLM (answers + entity extraction)
ollama pull nomic-embed-text  # embeddings
```

(To use a different generation model, change `[models] llm` in `config.toml`
after first run — e.g. `gemma3:4b` for higher-quality output. See
[Performance](#performance).)

### 2. (Optional) Install Tesseract for scanned-PDF OCR

- Windows: `winget install --id UB-Mannheim.TesseractOCR`
- Debian/Ubuntu: `apt install tesseract-ocr`

### 3. Set up the Python environment

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 4. Run it

```bash
python main.py
```

On first run it creates `config.toml`, the `data/` directory, and the SQLite
database, prints its readiness banner, then watches the configured folder until
you stop it with Ctrl+C:

```
AI Personal OS — alive
```

Drop a PDF, TXT, or Markdown file into `data/watched/`. Once its write completes
it is hashed, registered, and processed through to `ready` (dropping the same
content again is skipped). Then ask a question:

```bash
python -m aipos.cli ask "What are the main themes in my documents?" --explain
```

## CLI reference

The watcher (`python main.py`) handles ingestion. Everything else is the `aipos`
CLI, invoked as `python -m aipos.cli <command>`:

| Command | Description |
|---|---|
| `ask "<question>"` | Answer a question from the indexed corpus, with citations. |
| `ask "<question>" --explain` | As above, plus the reasoning trace (strategy, retrieval/graph/rerank counts, grounding, confidence, evidence). |
| `retry <file_id>` | Re-run a file that previously failed ingestion. |
| `export <path>` | Export the workspace (database + vector store) to a `.zip` archive. |
| `import <path>` | Import a workspace archive into a clean install. |

## Performance

Phase 1's performance was validated by a committed, reproducible model
evaluation (roadmap M7.1). On the reference machine (NVIDIA RTX 3060 Laptop,
6 GB VRAM; Ryzen 9 5900HX; Ollama 0.31.1), the default **`qwen2.5:3b`** fits
entirely in VRAM (100% GPU), answers queries in **~1.0 s** (meets the `< 2 s`
target), and keeps grounding and citations intact while scoring 3/3 on the
benchmark's ground-truth questions.

- Full comparison and rationale: [`benchmarks/results/winner.md`](benchmarks/results/winner.md)
  and [`benchmarks/results/comparison.md`](benchmarks/results/comparison.md).
- Re-run against any model: see [`benchmarks/README.md`](benchmarks/README.md).

Performance is model- and hardware-dependent; on a machine where the chosen
model doesn't fit in VRAM, inference falls back partly to CPU and slows
significantly. `gemma3:4b` is the documented higher-quality (but ~2× slower)
alternative.

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

## Running the tests

```bash
python -m unittest discover -s tests
```

The default suite is dependency-free: every external backend (Ollama, LanceDB,
Tesseract) is covered by injected fakes, so it runs anywhere Python runs.

## Known limitations

Phase 1 is CLI-only and deliberately scoped. Current known gaps:

- **No desktop UI, event bus, or System Health view** — deferred, not built
  (see [`docs/IDEAS.md`](docs/IDEAS.md)). The CLI is the complete Phase 1
  interface.
- **Large-document indexing is not yet fast.** Query latency meets the `< 2 s`
  target, but entity extraction runs one LLM call per chunk, so indexing a
  ~100-page document takes on the order of minutes, not the `< 10 s` target.
  Reducing that is future work.
- **`llama3.2:3b` is not a supported generation model.** It is faster but emits
  the citation footer without the required `USED_CHUNKS:` format, so answers
  come back ungrounded with no citations. Use `qwen2.5:3b` (default) or
  `gemma3:4b`.
- **Citations reference chunk ids and source files, not page numbers.** Page
  data is captured at ingest but not yet surfaced on answer sources, and the
  explainability `graph_path` is a relationship count rather than a full
  traversed-edge list.

## License

MIT — see [`LICENSE`](LICENSE).
