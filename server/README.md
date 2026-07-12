# Core API (W1)

The local client boundary for AI Personal OS (ADR-017): a loopback-only HTTP
service wrapping the frozen engine. The contract is the boundary; HTTP is the
first transport.

## Layering

```
React / desktop / mobile clients        (clients/*)
        │  HTTP, 127.0.0.1 only
        ▼
Core API                                (server/ — contract in schemas.py)
        │  plain Python calls, same as cli.py
        ▼
AnswerService · ingest · backup         (aipos/ — frozen engine)
        │
        ▼
RoutedRetriever → SemanticRetriever/GraphExpander → LexicalReranker → LLM
        │
        ▼
SQLiteStorage (all SQL) · LanceVectorStore (all LanceDB)
```

The contract is deliberately a **local contract for our own clients** — it
mirrors the engine's models field-for-field rather than promising public-API
stability (see `schemas.py`'s docstring). The CLI and folder watcher remain
valid peers of the same engine underneath.

## Run

From the repo root, with the project venv:

```bash
pip install -r server/requirements.txt
python -m server            # http://127.0.0.1:8765 — loopback only
```

Interactive docs (OpenAPI) at `http://127.0.0.1:8765/docs`.

## Endpoints (W1 — existing engine capabilities only)

| Route | Wraps |
|---|---|
| `GET /health` | config + storage sizes |
| `POST /ask` | `AnswerService.answer` (full `Explanation` included) |
| `GET /documents` · `GET /documents/{id}` · `GET /documents/{id}/chunks` | storage reads |
| `POST /documents/{id}/retry` | `ingest.retry_file` |
| `GET /search?q=&k=` | `SemanticRetriever.retrieve` |
| `GET /graph/edges` · `GET /graph/entity?name=` | graph reads |
| `GET /workspace/export` · `POST /workspace/import` | `aipos.backup` |

## Tests

```bash
python -m unittest discover -s server/tests -t .
```

No Ollama, LanceDB, or Tesseract required — all backends are fakes. The
engine's own suite (`tests/`) is unchanged and still dependency-free.
