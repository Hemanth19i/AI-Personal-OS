# ⚠ Historical Document

This document reflects the original Phase 1 planning process. It is preserved unchanged for
historical reference. **Do not use it for new implementation work.**

The current project documentation is:

- [`docs/ROADMAP.md`](../ROADMAP.md) — what we're building
- [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) — how we're building it
- [`docs/IDEAS.md`](../IDEAS.md) — deferred / future work

> **Doc-specific note:** Part A (engineering design) is largely accurate for what's built, except
> §A7 (`AnswerResult`/`graph_path` — the shipped shape differs) and §A8 (event taxonomy — none of it
> is live; no event bus exists). **Part B (UI/UX Design) describes a UI that was never built** —
> Tauri+React, the five pillars, and the event bus that would drive live updates are all deferred
> scope (see `IDEAS.md`).

---

# Design Document — AI Personal OS

**Companion to:** PRD v1.3 and the ADR. The PRD says *what* and *why*; this doc says *how*, at the
level of components, contracts, schemas, data flows, and screens. It is the bridge between the
architecture and the Phase 1 build plan.

**Status:** Draft v1.0
**Scope:** Phase 1 (MVP). Phase 2/3 concerns are noted only where they shape a v1 boundary.

---

## Part A — Technical / Engineering Design

### A1. System layers (recap)

```
                 AI Workspace (UI)
                       │
                   Core API            ← single entry point for the UI
          ┌────────────┼────────────┐
   Core Services            Intelligence Engine
   (platform plumbing)      (retrieval + reasoning)
          └────────────┬────────────┘
                  Storage Layer
        (SQLite · Vector DB · Graph · Files)
```

The UI only ever calls the **Core API** (ADR-006). The Core API delegates to Core Services and the
Intelligence Engine, which in turn use the Storage Layer. Nothing upstream touches storage engines
directly.

### A2. Component responsibilities

**Core Services (platform):**
- **Storage** — owns all engine connections; exposes typed data-access methods.
- **Memory** — typed memory (conversation, knowledge, workspace, preference).
- **Model Manager** — a lightweight wrapper (introduced at Build Plan T2.3) abstracting Ollama for
  both the embedding model and the LLM, so models are swappable by name. Deliberately minimal in
  Phase 1 — no hot-swap UI, no multi-model orchestration.
- **Index Manager** — **Phase 1 scope is Index and Re-index only** (ADR — see PRD §6.9). Optimize /
  repair / delete / re-embed / migrate-on-model-change are deferred past Phase 1.
- **Task Queue** — serializes heavy jobs (embedding, OCR, reasoning) so they don't block.
- **Event Bus** — in-process async pub/sub for notifications only.

**Intelligence Engine (reasoning):**
- **Intent Router** — picks a retrieval strategy (heuristic in v1).
- **Retrieval** — vector + keyword + graph traversal.
- **Reranker** — cross-encoder reorders candidates.
- **Context Builder** — assembles the final prompt context.
- **Reasoner** — calls the LLM to produce the answer.
- **Citation Builder** — maps the answer back to sources and builds the explainability payload.

### A2a. Source Adapter (Phase 1 scope)

A minimal implementation of the `SourceAdapter` contract from ADR-008 / PRD §6.2:

```
SourceAdapter (abstract)
  Scan()      → enumerate available items
  Parse()     → extract content
  Watch()     → detect changes
  Metadata()  → return source/item metadata
  Delete()    → handle removal

FolderSource(SourceAdapter)   ← the only Phase 1 implementation
  Scan()     → walk the watched folder
  Parse()    → PDF / TXT / Markdown extraction (+ OCR fallback, see A5)
  Watch()    → wraps watchdog
  Metadata() → path, hash, mtime
  Delete()   → mark file removed, retire its chunks/vectors
```

Future adapters (audio, GitHub, Email, Drive, OneDrive, Photos — all Phase 3) subclass
`SourceAdapter` without touching `FolderSource` or anything upstream of it. Kept intentionally thin
in Phase 1: no plugin registry, no dynamic loading — just one concrete class satisfying the
interface.

### A3. Core API surface (Phase 1)

A small, stable interface the UI/CLI depends on. Signatures are illustrative (Python-style).

```
# Ingestion / library
register_path(folder: str) -> None
list_files(workspace_id) -> list[FileRecord]
get_file_status(file_id) -> FileStatus
retry_file(file_id) -> None

# Query
ask(workspace_id, question: str) -> AnswerResult
search(workspace_id, query: str) -> list[SearchHit]

# Graph
get_entity(entity_id) -> Entity
get_neighbors(entity_id) -> list[Edge]

# Workspace
create_workspace(name) -> Workspace
export_workspace(workspace_id, path) -> None
import_workspace(path) -> Workspace

# System
get_health() -> HealthSnapshot
```

`AnswerResult` is the explainability payload (see A7).

### A4. Data model (SQLite)

```
workspaces(id, name, created_at)

files(
  id, workspace_id, path, hash, status, error,
  created_at, updated_at
)
-- status ∈ {pending, parsing, ocr, chunking, embedding,
--           extracting, verifying, ready, failed}

chunks(
  id, file_id, chunk_index, text, page, position, created_at
)
-- chunk_index = 0-based ordinal position of the chunk within its file
--   (defines chunk ordering). page/position = source location (page number,
--   character offset) for citations; populated once the parser preserves
--   page boundaries (see A2a). Added in T2.4 as an architectural correction.

entities(
  id, workspace_id, name, type, created_at
)

edges(
  id, workspace_id, source_entity_id, target_entity_id,
  relation, weight
)

conversations(id, workspace_id, started_at)
messages(id, conversation_id, role, content, created_at)

preferences(workspace_id, key, value)
app_state(key, value)
```

Vectors live in the vector DB keyed by `chunk_id`. The graph store holds `entities`/`edges` (mirrored
or owned, depending on the graph engine). SQLite is the index that ties everything together.

### A5. The file lifecycle as a state machine

```
pending → parsing → ocr* → chunking → embedding → extracting → verifying → ready
   │                                                                          
   └────────────────────────── (any step) ───────────────────────────► failed (retryable)

* ocr only for scanned PDFs with no text layer
```

Each transition is persisted in `files.status` **before** the work starts, so a crash leaves a known
state to resume from (ADR / Failure Philosophy). `verifying` confirms vectors + entities were written
before marking `ready`.

### A6. Retrieval data flow

```
question
  │
Intent Router ── heuristic: length, keywords, "how/why/relate" → strategy
  │
  ├─ Simple ──► keyword lookup ─────────────────────────────┐
  ├─ Semantic ─► vector search ─────────────────────────────┤
  ├─ Graph ────► entity match → graph traversal ────────────┤
  └─ Hybrid ───► vector + keyword + graph (default when unsure)
                                                            │
                                          candidate chunks + graph context
                                                            │
                                                    Cross-Encoder Reranker
                                                            │
                                                     Context Builder
                                                            │
                                                       Reasoner (LLM)
                                                            │
                                                    Citation Builder
                                                            │
                                                       AnswerResult
```

**Notes:**
- Retrieval is a **synchronous direct call** (ADR-004) — no event bus on this path.
- The router defaults to Hybrid when unsure, trading a little speed for safety (ADR-007).

### A7. The explainability payload (`AnswerResult`)

```
AnswerResult {
  answer: str
  sources: [ { file, page, chunk_id, snippet } ]
  reasoning_path: [ steps describing how evidence was COMBINED ]   # ADR-013
  confidence: "high" | "medium" | "low"                            # qualitative, ADR-012
  graph_path: [ entities/edges traversed, if any ]
  strategy_used: "simple" | "semantic" | "graph" | "hybrid"
}
```

`reasoning_path` is explicitly about evidence combination, not the model's internal cognition.

### A8. Event taxonomy (async only)

| Event | Emitted by | Typical subscribers |
|---|---|---|
| `file.detected` | Watcher | Ingestion |
| `file.parsed` | Parser | (logging) |
| `file.chunked` | Chunker | Embedder, Entity extractor |
| `vectors.indexed` | Embedder | Lifecycle tracker |
| `graph.updated` | Entity extractor | Lifecycle tracker, Graph Explorer |
| `file.ready` | Lifecycle | UI (toast + Library), Automation (Phase 2) |
| `file.failed` | Any step | UI (error state) |
| `health.changed` | Health monitor | System Health view |

Queries (`ask`, `search`) are **not** events — they are request/response.

**Sequencing note (ADR-016):** these events are not live until **Milestone 5**. M1–M4 perform the
same state transitions via direct synchronous writes to `files.status`; M5 adds publish calls on
top of already-working transitions so the UI can subscribe.

### A9. Concurrency & the task queue

Heavy jobs (embedding, OCR, reasoning) run through the **Task Queue** so a burst of ingestion doesn't
freeze querying. v1 can be a simple in-process worker pool with a SQLite-backed job table for
durability. One slow/bad file is isolated to its own job and never stalls the pipeline. **The Task
Queue itself is built in Milestone 6 (T6.2)** — before that, M1–M5 process jobs synchronously and
in-process; per-file isolation (A5) is what keeps one bad file from stalling ingestion until then.

### A10. Workspace independence

Each workspace owns its **graph, vector index, memory, and settings**, plus its own encryption key.
Practically: namespace vector collections and graph stores per workspace, scope every SQLite query by
`workspace_id`, and make export/restore operate on that whole bundle (ADR — workspace independence).

### A11. Offline model & app updates

Updates arrive as packages: **Import → Verify → Install**. The Model Manager validates a model package
(checksum) before registering it. No silent network fetches (ADR-011).

---

## Part B — UI / UX Design

### B1. Design principles (from the product principles)

- **Explainable by default** — every answer can be expanded to show its evidence.
- **Calm, not flashy** — this is a thinking tool; the UI should get out of the way.
- **Status is always visible** — the user always knows what's ingesting, ready, or failed.
- **Privacy is felt** — an always-visible "offline" indicator reassures the user nothing leaves.
- **Fast over rich** — instant responses on simple actions; never block the whole UI on one job.

### B2. The five pillars (primary navigation)

```
┌──────────────────────────────────────────────────────────────┐
│  AI Personal OS                       ● Offline   ⚙  ◔ Health │
├────────────┬─────────────────────────────────────────────────┤
│  ◆ Chat    │                                                  │
│  ◆ Search  │                  (active pillar view)            │
│  ◆ Graph   │                                                  │
│  ◆ Timeline│                                                  │
│  ◆ Library │                                                  │
│            │                                                  │
│  ───────── │                                                  │
│  Workspace ▼                                                  │
└────────────┴─────────────────────────────────────────────────┘
```

Left rail = the five pillars + a workspace switcher. Top bar = an always-on **Offline** indicator,
settings, and a Health glance. Build order: **Chat → Library → Search → Graph → Timeline.**

### B3. Chat (the primary surface)

The main way users interact. A conversation thread; each answer is an **expandable evidence card**.

```
┌─────────────────────────────────────────────┐
│  You:  How does my ZTNA project relate to    │
│        zero-trust principles?                │
│                                              │
│  AI:   [answer text…]                        │
│        ┌─ Why this answer ▾ ────────────────┐│
│        │ Confidence: ● High                 ││
│        │ Sources:  ztna_notes.pdf p.3,7     ││
│        │           architecture.md          ││
│        │ Strategy: Hybrid (graph + vector)  ││
│        │ Graph path: ZTNA → zero-trust →    ││
│        │             least-privilege        ││
│        │ Reasoning: combined 3 passages +   ││
│        │            2 graph edges            ││
│        └────────────────────────────────────┘│
│                                              │
│  [ Ask anything…                        ↵ ]  │
└─────────────────────────────────────────────┘
```

The evidence card is **collapsed by default** (calm), expandable on demand (explainable). Sources are
clickable → open the source file at that page in a preview.

### B4. Library (ingestion status)

The trust surface — shows exactly what the system knows and the state of every file.

```
┌──────────────────────────────────────────────────────┐
│ Library                         + Add folder   ⟳      │
├──────────────────────────────────────────────────────┤
│  ztna_notes.pdf        ● Ready        42 chunks       │
│  securerag_arch.md     ● Ready        18 chunks       │
│  research_notes.md     ◐ Embedding…   (3/12)          │
│  scanned_report.pdf    ◐ OCR…                         │
│  broken_file.pdf       ✕ Failed        [Retry]        │
└──────────────────────────────────────────────────────┘
```

Live-updates via `file.ready` / `file.failed` events. Failed rows expose a **Retry**. A status dot
legend maps to the state machine. This screen is where the file lifecycle becomes visible to the user.

### B5. Search (precise, non-conversational)

For when the user wants to *find*, not *ask*. Returns ranked passages with source + page, plus a
strategy toggle (Auto / Semantic / Keyword) for power users.

```
┌──────────────────────────────────────────────────────┐
│ Search:  least privilege            [Auto ▾]   ⌕      │
├──────────────────────────────────────────────────────┤
│  ztna_notes.pdf · p.7      "…enforce least privilege  │
│                            at every access decision…" │
│  securerag_arch.md         "…scoped tokens follow     │
│                            least-privilege…"          │
└──────────────────────────────────────────────────────┘
```

### B6. Graph Explorer (the differentiator, made visible)

An interactive node-link view of entities and relationships. Click a node → see connections and the
documents it came from. This is the screen that *shows* GraphRAG and makes the project memorable in a
demo. Can trail behind Chat/Library/Search in the build order, but it's a high-impact visual.

```
        (zero-trust)
        /     |      \
  (ZTNA)  (least-priv)  (SecureRAG)
     |                      |
 ztna_notes.pdf       securerag_arch.md
```

### B7. Timeline (knowledge over time)

A chronological view of when knowledge entered the system and how topics grew. In v1 this is an
ingestion timeline ("what did I add, when"). The richer "how my understanding evolved" version depends
on the versioned graph and is Phase 2 — the v1 Timeline lays the visual groundwork.

### B8. Always-present chrome

- **Offline indicator** — a small persistent badge; privacy made tangible. Clicking it explains
  "everything runs on this device."
- **Health glance** — an icon that opens the System Health panel (RAM, LLM status, queue depth,
  storage). Turns "why is this slow?" into an answerable question.
- **Workspace switcher** — switch/create/export workspaces; reinforces workspace independence.

### B9. Key interaction patterns

- **Drop-to-ingest:** the canonical entry. Drop a file in the folder (or drag onto Library) → a row
  appears `pending` → progresses live → toast on `ready`. This is the demo money-shot.
- **Expand-for-evidence:** answers are trustworthy because the evidence is one click away, never forced.
- **Retry, never dead-end:** a failed file always offers a path forward.
- **Non-blocking:** ingesting a big batch never freezes Chat — the task queue keeps querying responsive.

### B10. Visual tone

Calm and focused: generous whitespace, a single restrained accent color, status communicated through
small consistent dots/icons rather than loud banners. The interface should feel like a quiet study, not
a dashboard. (When you build the React UI, pull concrete tokens from the frontend-design skill.)

---

## Part C — How this maps to the build plan

| Build milestone | Design sections it implements |
|---|---|
| M1 Ingest → SQLite | A2a (SourceAdapter/FolderSource), A4, A5 (pending/hash), B4 (Library skeleton) |
| M2 Process → chunks/vectors | A5 (incl. OCR fallback), A9, Storage in A2 |
| M3 Vector RAG | A6 (semantic path + Cross-Encoder Reranker), A7, B3 (Chat) |
| M4 Knowledge graph | A4 (entities/edges), A6 (graph/hybrid), A2 router, B6 |
| M5 Explainability + UI | A7, A3 (Core API), A8 (events), B2–B8 |
| M6 Robustness | A5 (recovery), A9 (queue), A10/A11, B4 retry, B8 health |
| M7 Ship | performance targets, README, demo |

---

*End of document.*
