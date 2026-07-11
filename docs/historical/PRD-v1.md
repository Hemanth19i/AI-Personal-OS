# ⚠ Historical Document

This document reflects the original Phase 1 planning process. It is preserved unchanged for
historical reference. **Do not use it for new implementation work.**

The current project documentation is:

- [`docs/ROADMAP.md`](../ROADMAP.md) — what we're building
- [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) — how we're building it
- [`docs/IDEAS.md`](../IDEAS.md) — deferred / future work

> **Doc-specific note:** sections describing what's actually been built (ingestion, retrieval,
> GraphRAG, explainability, robustness) remain accurate; sections describing the AI Workspace UI
> (§6.12), System Health view (§6.13), typed Memory (§6.6), and security hardening (§6.18) describe
> intended-but-not-yet-built scope — see `ROADMAP.md` and `IDEAS.md` for what's actually true today.

---

# Product Requirements Document — AI Personal OS

**Working title:** AI Personal OS — An offline-first intelligence platform for your personal knowledge.
**Author:** Abhi
**Status:** Draft v1.3
**Last updated:** June 2026

> **AI Personal OS is an offline-first intelligence platform that continuously transforms
> personal information into structured, searchable, explainable knowledge while keeping
> complete ownership of data on the user's device.**
>
> It is *not* an AI chatbot. It is a platform that continuously organizes, understands, and
> reasons over a user's personal knowledge — entirely locally.
>
> **Documents are inputs. Knowledge is the product.** Files are what the user feeds in;
> structured, searchable, explainable knowledge is what the system produces.

---

## 1. Overview

AI Personal OS turns all of a person's scattered information — PDFs, notes, voice memos,
browser bookmarks, chat exports — into a single, queryable, continuously-understood knowledge
base. Everything is ingested, processed, and reasoned over on the user's own machine. No cloud,
no API keys, no data leaving the device.

The user interacts in natural language: *"What was that startup idea I had six months ago?"*,
*"Summarize everything I learned about quantum computing,"* *"Which of my documents contradict
each other?"* The system retrieves and reasons over the user's own knowledge — and shows its work.

Core differentiators: (1) **GraphRAG** retrieval combining a knowledge graph with vector search,
(2) an **event-driven architecture** keeping subsystems decoupled, (3) **explainable answers**
with sources and reasoning paths, and (4) a strict **offline-first, privacy-first** guarantee.

---

## 1a. Product principles

These guide every design decision and every future trade-off:

- **Local-first** — the device is the platform; the cloud is never required.
- **Explainable by default** — answers come with their evidence, always.
- **Modular architecture** — subsystems are independent and replaceable.
- **Privacy over convenience** — when they conflict, privacy wins.
- **Fast over feature-rich** — a responsive core beats a sprawling one.
- **Simple workflows before automation** — make the manual path excellent first.

**Scalability principle:** the architecture is designed so additional data sources, retrieval
strategies, and AI capabilities can be introduced **without requiring changes to existing
subsystems.**

---

## 2. Problem statement

People accumulate knowledge across a dozen disconnected tools, almost none of it searchable by
*meaning*. Existing tools either require the cloud and surrender privacy, only do keyword search,
or lock data into proprietary formats. There is no clean, fully-offline platform that understands
relationships across everything you own and can explain its reasoning.

---

## 3. Goals and non-goals

### Goals
- Ingest multiple file types automatically and keep them continuously up to date.
- Answer natural-language questions grounded in the user's data, with citations and a visible
  reasoning path.
- Surface *relationships* across sources, not just matching passages.
- Run fully offline on consumer hardware.
- Work across desktop and mobile, syncing locally between a user's own devices *(Phase 3 — Phase 1
  ships desktop-only; see §10)*.

### Non-goals (for v1)
- No cloud sync, multi-user collaboration, or team features.
- No autonomous multi-agent orchestration (Phase 2).
- Not a note-taking *editor* — it understands existing files; it doesn't replace Obsidian/Notion
  as an authoring tool.
- No mobile client or local device sync in v1 — both are Phase 3 (see §6.14, §10, open questions).
- No versioned knowledge graph, calibrated numeric confidence, or learned intent router in v1.
- **Data-source plugins:** the *interface* (`SourceAdapter`) is defined in v1; only one local source
  ships — `FolderSource`, covering PDF, TXT, and Markdown. Audio/voice-memo transcription, GitHub,
  Email, Drive, OneDrive, and Photos sources are Phase 3 plugins.

---

## 4. Target users

- **Primary:** Knowledge workers, researchers, students with large personal document collections
  who care about privacy.
- **Secondary:** Developers and power users wanting a hackable, local-first knowledge platform.
- **Builder's use case:** Flagship portfolio project demonstrating GraphRAG, event-driven design,
  local LLM integration, explainability, and cross-platform delivery.

---

## 5. User stories

1. I drop a PDF into a watched folder and within seconds it becomes searchable.
2. I ask a question in plain English and get an answer with citations to source files and pages.
3. I ask how two ideas relate, and the system traces the connection through the knowledge graph.
4. I can see *why* the system answered — its sources, reasoning path, and graph path.
5. I can see the status of every file and retry failures.
6. I trust that nothing I ingest is ever sent off my device.

---

## 6. Functional requirements

### 6.1 Ingestion
- Watch folders for new, changed, deleted files.
- Wait for writes to complete before processing (no half-written files).
- Deduplicate by content hash (SHA-256).
- Parse PDF, TXT, and Markdown files; OCR scanned PDFs with no text layer. *(Audio/speech-to-text
  is deferred past Phase 1 — see §10.)*
- Chunk into overlapping passages, preserving source location (page, offset).

### 6.2 Data Source Plugin Interface
Every data source — local or remote — implements a common contract rather than being a special
case:

```
Scan()      → enumerate available items
Parse()     → extract content
Watch()     → detect changes
Metadata()  → return source/item metadata
Delete()    → handle removal
```

v1 ships a single local source through this interface — a watched folder handling PDF, TXT, and
Markdown, implemented as `FolderSource` (the only Phase 1 `SourceAdapter`). Audio/voice-memo
transcription, GitHub, Email, Google Drive, OneDrive, and Photos become **plugins** later (Phase 3)
with no special-casing.

### 6.3 Knowledge Processing Layer
Does far more than "extraction": OCR, speech-to-text, entity & relationship extraction, metadata,
classification, embeddings, summaries.

### 6.4 File lifecycle (state machine)
```
Pending → Parsing → OCR → Chunking → Embedding → Knowledge Extraction → Verification → Ready
                                                                                  └→ Failed
```
On failure, the file resumes from its last good state.

### 6.5 Core Services *(platform, not intelligence)*
Memory isn't intelligence; workspace isn't intelligence. These are platform services:
- **Memory** (typed — see 6.6)
- **Workspace**
- **Model Manager** (Phase 1: a lightweight wrapper around Ollama abstracting the embedding model
  and the LLM, introduced at Build Plan T2.3 — not a general hot-swap UI)
- **Storage**
- **Event Bus**
- **Index Manager** (see 6.9)
- **Task Queue** (see 6.10)

### 6.6 Memory (typed)
- **Conversation memory** — dialogue history/context.
- **Knowledge memory** — facts derived from ingested data.
- **Workspace memory** — project/session state.
- **Preference memory** — settings and learned preferences.

### 6.7 Intelligence Engine
Strictly the reasoning/retrieval concerns: **Retrieval, Graph Traversal, Reranking, Context
Builder, Reasoning, Citation Builder.**

**Intent Router (don't force every query through GraphRAG):**
```
User Question → Intent Router → { Simple lookup | Keyword | Semantic | GraphRAG | Hybrid }
```
v1 uses cheap **heuristics** (query length, keyword patterns) with a safe default of "when unsure,
use the richer path." A learned router is a later upgrade — a wrong route on a local model
silently degrades answers, so v1 favors predictable over clever.

**Retrieval Strategy Layer (extensible):**
```
Retrieval Strategy → { Simple | Semantic | Graph | Hybrid | Agent (future) }
```

**Retrieval pipeline (when the richer path is chosen):**
```
Vector Search → Keyword Search → Graph Traversal → Cross-Encoder Reranker → Context Builder → LLM
```

### 6.8 Explainability
Every answer exposes:
```
Answer → Sources → Reasoning Path → Confidence (qualitative) → Graph Path
```
v1 confidence is **qualitative (high / medium / low)** from retrieval/graph/reranker/model signals.
Calibrated numeric confidence is Phase 2 — a precise-looking but uncalibrated number misleads.

**What "Reasoning Path" means:** it describes *how the system combined retrieved evidence* — which
sources were retrieved, how they were ranked, and which graph connections were traversed. It does
**not** expose or claim to reproduce the internal reasoning process of the language model itself.
This keeps the feature technically honest.

### 6.9 Index Manager
A dedicated manager for index operations (not just "file → index"). **Phase 1 scope is
intentionally minimal — Index and Re-index only:**
- **Phase 1:** Index, Re-index
- **Later phases:** Optimize index, Repair index, Delete index, Re-embed / migrate models
  (re-embedding when the embedding model changes)

### 6.10 AI Task Queue
All heavy AI work flows through a queue so jobs don't block each other:
```
Task Queue → { Embedding | OCR | Speech | Reasoning | Summaries }
```

### 6.11 Event bus
- In-process pub/sub backbone.
- **Design rule:** event bus *only* for asynchronous notifications and background processing.
  Synchronous request/response (retrieval, reasoning, inference) stays **direct service calls**.
- Every event logged for an auditable trail.

### 6.12 User interface — "AI Workspace"
*(Renamed from "Command Center UI.")* Cross-platform: desktop (Tauri + React), mobile
(Flutter / React Native). **Five UI pillars:**
```
Search | Chat | Graph Explorer | Timeline | Library
```
Plus an answer view exposing sources, reasoning path, and graph path; and live updates driven by
bus events.

### 6.13 System Health Monitoring
Users should know *why* something is slow:
```
System Health → GPU | RAM | Embedding Queue | LLM Status | Storage | Background Jobs
```

### 6.14 Sync (local only) — Phase 3
Sync between a user's own devices over LAN / P2P. Desktop is source of truth; mobile is a
periodically-synced replica (avoids SQLite concurrent-write conflicts). **Not built in Phase 1** —
Phase 1 is desktop-only; see §10.

### 6.15 Backup & recovery
Automatic snapshots, manual backup, restore, workspace export.

### 6.16 Offline updates
No internet means updates ship as packages:
```
Offline Update Package → Import → Verify → Install
```
Covers both **app updates** and **model updates**.

### 6.17 Storage
- **Vector DB** — LanceDB (locked for Phase 1, ADR-015) for embeddings.
- **Knowledge graph** for entities/relationships.
- **SQLite — the OS's brain:** file/chunk metadata, hashes, ingestion state, tags, user
  preferences, workspace state, settings, search history, conversation history, app state.
- **File system** for original files. Nothing leaves the device.

### 6.18 Security & privacy
- AES encryption at rest
- Secure credential vault
- Permission manager
- Optional biometric lock
- **Workspace isolation & independence:** each workspace fully owns its **graph, vector index,
  memory, and settings**, plus its own permissions and encryption key. This means any workspace
  can be exported, backed up, encrypted, or deleted **cleanly and independently** of the others.

---

## 7. Non-functional requirements

- **Privacy:** 100% offline. No network calls for core functionality. Hard rule.
- **Performance (concrete targets):**
  - 100-page PDF indexed in **< 10 seconds**
  - Query latency **< 2 seconds**
  - Cold startup **< 5 seconds**
  - Memory usage **< 2 GB** during normal operation

  *(Targets are for typical consumer hardware and will be validated/tuned during Phase 1; they
  exist to give engineering concrete goals, not as contractual guarantees.)*
- **Portability:** Windows, macOS, Linux; Android, iOS.
- **Observability:** Event log + System Health give a complete picture of behavior.

### 7.1 Failure philosophy

Reliability is an architectural principle, not an afterthought:

- **Never lose original files** — inputs are sacred and never mutated in place.
- **Never corrupt indexes** — index writes are atomic; a crash leaves a consistent state.
- **Failed jobs remain retryable** — nothing fails permanently without an explicit path to retry.
- **Partial ingestion never blocks the system** — one bad file doesn't stall the queue.
- **Every failure is recoverable** — via the per-file state machine and backups.

### 7.2 Testing strategy

- **Unit tests** — individual components (parsers, chunker, retrieval strategies).
- **Integration tests** — subsystem interactions across the event bus and Core API.
- **End-to-end ingestion tests** — drop a file, assert it becomes queryable.
- **Offline validation tests** — verify zero network calls with the network disabled.
- **Recovery tests** — kill the process mid-ingestion and assert clean resume; restore from backup.

---

## 8. Architecture summary

```
Data sources (via Plugin Interface) → Ingestion → Knowledge Processing Layer
                                                          │
                                          ┌───────────────┴───────────────┐
                                     Knowledge Graph                   Vector DB
                                          └───────────────┬───────────────┘
                                                          │
   ┌─────────────────────────┐              ┌─────────────┴─────────────┐
   │      Core Services      │  ◄────────►   │    Intelligence Engine    │
   │  Memory · Workspace ·   │              │  Intent Router · Retrieval │
   │  Model Mgr · Storage ·  │              │  Strategy · Graph · Rerank │
   │  Event Bus · Index Mgr ·│              │  Context · Reasoning ·     │
   │  Task Queue             │              │  Citations · Explainability│
   └─────────────────────────┘              └─────────────┬─────────────┘
                                                          │
                                          Event bus (async notifications)
                                                          │
                                               AI Workspace (UI)
                                Search · Chat · Graph Explorer · Timeline · Library
                                                          │
                                              Local Storage Layer
```

**Core Services are platform infrastructure; the Intelligence Engine is reasoning/retrieval.**
The event bus carries asynchronous notifications; synchronous queries are direct calls.

### 8.1 Layered API boundaries

Even as a desktop app, the layers talk through defined boundaries — the UI never reaches directly
into SQLite or the vector DB:

```
UI  →  Core API  →  Platform Services  →  Storage
```

This keeps storage engines swappable (e.g. changing vector DB) without touching the UI, and is
what makes the modularity principle real rather than aspirational.

---

## 9. Tech stack (proposed)

| Layer | Choice |
|---|---|
| Desktop shell | Tauri + React |
| Mobile | Flutter or React Native |
| Backend / core | Python (or Rust within Tauri) |
| Model Manager / LLM runtime | Ollama abstraction (Llama / Mistral / Qwen / Gemma) |
| Embeddings | Local model (e.g. nomic-embed) |
| Vector DB | **LanceDB** (locked for Phase 1 — ADR-015; ChromaDB documented only as a fallback, not implemented) |
| Knowledge graph | Embedded graph store (e.g. Kùzu) or SQLite-backed graph |
| Reranker | Local cross-encoder |
| Metadata / app state | SQLite |
| File watching | watchdog (Python) or notify (Rust) |
| OCR | Tesseract |
| Speech-to-text | Local Whisper variant |
| Task queue | Local job queue (in-process / SQLite-backed) |
| Event bus | In-process pub/sub (asyncio / pyee, or tokio broadcast) |
| Encryption | AES at rest |

---

## 10. Phased roadmap

### Phase 1 — Flagship MVP (ship this)
Ingestion (one local `FolderSource` covering PDF/TXT/Markdown, via the `SourceAdapter` plugin
interface) → Knowledge Processing → graph + vector → Intelligence Engine (heuristic intent router +
retrieval pipeline + explainability) → AI Workspace with the five pillars. Includes Core Services
(typed memory, a lightweight Model Manager, a minimal Index Manager [Index/Re-index only], Task
Queue, and an Event Bus introduced at Milestone 5 — see ADR-016), SQLite app-state, System Health,
backup/export, and offline update import. **Desktop-only** — mobile and local sync are Phase 3.

> **MVP done-definition:** Phase 1 is complete when a user can drop a document, have it indexed
> locally, ask questions, receive cited answers, and understand *why* those answers were produced.
> Nothing more is required to call Phase 1 shipped.

### Phase 2 — Agentic + trust layer
Agent orchestrator & tool manager; Agent retrieval strategy; learned intent router; calibrated
numeric confidence; versioned knowledge graph with timeline ("how has my understanding of AI
evolved since January?"); full security hardening.

### Phase 3 — Reach & extensibility
Mobile parity, local sync, additional data-source plugins (audio/voice-memo transcription, GitHub,
Email, Drive, OneDrive, Photos), automation recipes, packaging/installers, and a public
**Plugin SDK**.

---

## 11. Success metrics

- **Indexing:** 100-page PDF indexed in < 10 seconds.
- **Query latency:** answers returned in < 2 seconds.
- **Startup:** cold start < 5 seconds.
- **Footprint:** < 2 GB memory during normal operation.
- **Correctness:** answers include correct citations and a verifiable reasoning path.
- **Resilience:** clean recovery from a mid-ingestion crash and from a restored backup.
- **Privacy:** end-to-end demo runs offline with the network physically disabled.
- **(Portfolio):** README + demo video showing file-drop → query → explanation.

---

## 12. Open questions / risks

- **Mobile LLM inference** — hard on phones; deferred to Phase 3 along with mobile/sync generally
  (§10), where mobile is likely a thin LAN client.
- **Local LLM vs. agentic complexity** — weaker at multi-step orchestration; agents are Phase 2.
- **Intent routing on local models** — can misroute and silently degrade answers; v1 stays
  heuristic with a safe default.
- **Knowledge graph extraction quality** — may need a hybrid rules + LLM approach.
- **Confidence calibration** — genuinely hard; v1 stays qualitative on purpose.
- **Scope creep** — the central risk. The phased roadmap exists to keep Phase 1 shippable; resist
  pulling Phase 2/3 features forward.

---

*End of document.*
