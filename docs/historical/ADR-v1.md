# ⚠ Historical Location — but still authoritative

This file was **relocated** here on 2026-07-11 as part of the docs reorganization (Build Plan frozen
→ [`docs/ROADMAP.md`](../ROADMAP.md) canonical). Unlike the other documents in `docs/historical/`,
these decisions are **not retired** — every ADR below (001–016) is still in effect and still governs
new work. This file remains the authoritative record of *why* each decision was made.

The current project documentation is:

- [`docs/ROADMAP.md`](../ROADMAP.md) — what we're building
- [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) — how we're building it (restates the currently-binding
  *rules* derived from these ADRs, in one short page)
- [`docs/IDEAS.md`](../IDEAS.md) — deferred / future work

> **Immutability still applies:** per this document's own convention, records are never edited in
> place — a changed decision gets a new ADR-017+, never an edit to one below. Breaking an
> architectural boundary in `ARCHITECTURE.md` is exactly what a new ADR is for.

---

# Architecture Decision Records — AI Personal OS

This document captures the significant architectural decisions for AI Personal OS, the reasoning
behind each, the alternatives considered, and the consequences. Each record follows a lightweight
ADR format. Records are immutable once accepted — if a decision changes, a new ADR supersedes the
old one rather than editing it in place.

**Status legend:** Proposed · Accepted · Superseded · Deprecated

---

## ADR-001 — Local-first, fully offline architecture

**Status:** Accepted

**Context.** The product's core promise is privacy and data ownership. Users ingest highly
personal material (documents, notes, voice, chats). Competing tools rely on the cloud, which
surrenders privacy and requires connectivity.

**Decision.** All core functionality runs entirely on the user's device. No network calls are
required for ingestion, processing, retrieval, or reasoning. The cloud is never a dependency.

**Alternatives considered.**
- *Cloud-based (e.g. hosted vector DB + hosted LLM):* better model quality and zero local
  resource cost, but breaks the core privacy promise and adds running cost and connectivity needs.
- *Hybrid (local data, cloud LLM):* a middle ground, but any cloud call leaks query content and
  undermines the "nothing leaves your device" guarantee.

**Consequences.**
- (+) Strong, marketable privacy guarantee; works with no internet; no per-user running cost.
- (−) Constrained to local model quality and local hardware limits.
- (−) Must solve offline updates for both app and models (see ADR-011).

---

## ADR-002 — GraphRAG (knowledge graph + vector DB) over vector-only retrieval

**Status:** Accepted

**Context.** Pure vector search retrieves semantically similar passages but misses explicit
relationships ("how does X connect to Y?", "which notes mention this person?"). The product's
value is understanding connections across a user's knowledge, not just matching text.

**Decision.** Combine a knowledge graph (entities + relationships) with a vector database
(semantic embeddings). Retrieval can traverse the graph and rank passages semantically.

**Alternatives considered.**
- *Vector-only RAG:* simpler and faster to build, but cannot answer relationship questions and
  offers weaker explainability.
- *Graph-only:* strong on relationships but poor at fuzzy semantic recall.

**Consequences.**
- (+) Answers relationship questions; richer explainability via graph paths; genuine differentiator.
- (−) More moving parts; entity/relationship extraction quality on a local model needs validation
  (may require a hybrid rules + LLM approach).

---

## ADR-003 — Event-driven architecture with a central in-process event bus

**Status:** Accepted

**Context.** As subsystems multiply (ingestion, embedding, graph extraction, UI, automation),
direct calls between them create tight coupling and a brittle, hard-to-extend system.

**Decision.** Place an event bus at the center. Subsystems publish and subscribe to events rather
than calling each other directly. The bus is **in-process** (e.g. asyncio/pyee or tokio broadcast),
not a heavyweight broker.

**Alternatives considered.**
- *Direct service calls everywhere:* simplest initially, but coupling grows painfully; adding a
  subscriber means editing existing code.
- *External broker (Kafka/RabbitMQ/Redis):* overkill for a single-machine app; adds an operational
  dependency that conflicts with offline-first.

**Consequences.**
- (+) Decoupled subsystems; new subscribers added without touching existing ones; live UI updates;
  full auditable event log.
- (−) Requires discipline about *what* belongs on the bus (see ADR-004).

---

## ADR-004 — Events for async notifications only; synchronous queries stay direct calls

**Status:** Accepted

**Context.** A naive "everything is an event" design makes simple request/response flows (like
"retrieve documents and wait for the answer") awkward and adds latency.

**Decision.** Use the event bus **only** for asynchronous notifications and background processing
(e.g. `file.ready`, `graph.updated`). Keep synchronous request/response paths — retrieval,
reasoning, inference — as **direct service calls**.

**Alternatives considered.**
- *Pure event-driven everything:* conceptually uniform but painful for query/response and adds
  needless latency and complexity.

**Consequences.**
- (+) Low latency where it matters; events where decoupling pays off; clear mental model.
- (−) Developers must consciously classify each interaction as notification vs. query.

---

## ADR-005 — Separate Core Services from the Intelligence Engine

**Status:** Accepted

**Context.** An early design folded memory, workspace, model management, etc. into one
"Intelligence Engine." But memory and workspace are platform plumbing, not reasoning.

**Decision.** Split into two layers. **Core Services** = Memory, Workspace, Model Manager, Storage,
Event Bus, Index Manager, Task Queue. **Intelligence Engine** = Retrieval, Graph Traversal,
Reranking, Context Builder, Reasoning, Citation Builder.

**Alternatives considered.**
- *Single monolithic engine:* fewer boxes on a diagram, but conflates infrastructure with
  reasoning and makes the system harder to reason about and test.

**Consequences.**
- (+) Cleaner separation of concerns; platform services reusable independent of reasoning.
- (−) Slightly more upfront structure.

---

## ADR-006 — Layered API boundaries (UI → Core API → Platform Services → Storage)

**Status:** Accepted

**Context.** Even in a desktop app, letting the UI talk directly to SQLite or the vector DB creates
coupling that makes storage engines impossible to swap later.

**Decision.** Enforce layered boundaries: the UI calls a **Core API**, which calls **Platform
Services**, which call **Storage**. The UI never touches storage engines directly.

**Alternatives considered.**
- *UI talks directly to storage:* faster to prototype, but locks in storage choices and spreads
  data-access logic across the UI.

**Consequences.**
- (+) Storage engines (vector DB, graph store) are swappable; data-access logic is centralized.
- (−) A small amount of indirection/boilerplate.

---

## ADR-007 — Intent router with heuristics in v1 (not every query uses GraphRAG)

**Status:** Accepted

**Context.** Routing every query through full GraphRAG wastes CPU and adds latency for simple
lookups. But an LLM-based intent classifier on a *local* model can misroute and silently degrade
answer quality.

**Decision.** Add an intent router that selects a retrieval strategy (Simple / Keyword / Semantic /
GraphRAG / Hybrid). In v1 it uses **cheap heuristics** (query length, keyword patterns) with a safe
default: **when unsure, take the richer path.** A learned router is deferred to Phase 2.

**Alternatives considered.**
- *Always GraphRAG:* simplest routing, but slow and wasteful for trivial lookups.
- *LLM-based router in v1:* smarter in theory, but unreliable on local models and fails silently.

**Consequences.**
- (+) Faster responses for simple queries; predictable behavior; safe fallback.
- (−) Heuristics are coarse; some queries take the richer path unnecessarily (acceptable trade).

---

## ADR-008 — Data source plugin interface (define in v1, ship few)

**Status:** Accepted

**Context.** Treating each data source (PDF, notes, GitHub, email, Drive…) as a special case leads
to tangled, duplicated code. But building every connector now would explode v1 scope.

**Decision.** Define a uniform data-source contract — `Scan() / Parse() / Watch() / Metadata() /
Delete()` — in v1. Ship only 2–3 local sources through it. Remote sources (GitHub, Email, Drive,
OneDrive, Photos) become **plugins** in Phase 3.

**Alternatives considered.**
- *Special-case each source:* quick per-source, but unmaintainable as sources grow.
- *Build all connectors in v1:* maximal capability, but massive scope and the main threat to shipping.

**Consequences.**
- (+) Clean extension model with near-zero upfront cost; new sources don't touch existing code.
- (−) The interface must be designed carefully now to avoid churn later.

**Scope note (Phase 1 build plan, PRD §6.2):** "2–3 local sources" above was the original range
under consideration; Phase 1 ships exactly **one** — `FolderSource`, covering PDF/TXT/Markdown.
This narrows the Decision's scope, not its architecture — the interface itself is unchanged. Noted
here rather than editing the Decision text above, per this document's immutability rule.

---

## ADR-009 — SQLite as the metadata and application-state store

**Status:** Accepted

**Context.** The system needs durable, queryable storage for file/chunk metadata, ingestion state,
and application state (preferences, workspace, history) — separate from vectors and the graph.

**Decision.** Use SQLite as the system's "brain" for metadata and app state. It is the index/map;
the vector DB holds vectors, the graph holds relationships, and the file system holds originals,
all cross-referenced by IDs and paths.

**Alternatives considered.**
- *Embedded key-value store:* simpler but weaker querying and no relational integrity.
- *A server database (Postgres):* unnecessary operational weight for a local single-machine app.

**Consequences.**
- (+) Zero-install, battle-tested, great tooling, available on every target platform.
- (−) Weak at concurrent writes from multiple devices — which directly drives ADR-010.

---

## ADR-010 — Local sync with desktop as source of truth

**Status:** Accepted

**Context.** Users want their knowledge on both desktop and mobile, but SQLite handles concurrent
writes from multiple devices poorly, risking corruption.

**Decision.** Sync between a user's own devices over LAN / P2P. Treat **desktop as the source of
truth** and **mobile as a periodically-synced replica**, avoiding concurrent-write conflicts.

**Alternatives considered.**
- *Peer-to-peer multi-master sync:* most flexible, but conflict resolution on SQLite is complex and
  error-prone for v1.
- *Cloud sync:* easy conflict handling, but violates ADR-001 (offline-first).

**Consequences.**
- (+) Simple, robust, privacy-preserving sync; no corruption risk from dual writes.
- (−) Mobile is effectively read-mostly; true bidirectional editing is a later concern.

---

## ADR-011 — Offline update packages for app and models

**Status:** Accepted

**Context.** An offline-first product still needs to update its application code and its local
models, but cannot assume an internet connection or an app store.

**Decision.** Ship updates as **offline packages** following an Import → Verify → Install flow,
covering both app updates and model updates.

**Alternatives considered.**
- *Online auto-update:* convenient, but assumes connectivity and conflicts with offline-first.

**Consequences.**
- (+) Updates work with no internet; verification step guards integrity.
- (−) More manual than online auto-update; requires a packaging/verification mechanism.

---

## ADR-012 — Qualitative confidence in v1; calibrated numeric scoring deferred

**Status:** Accepted

**Context.** A numeric confidence score ("87%") is easy to display but hard to make honest. Blending
retrieval, reranker, and model signals into one percentage tends to look precise while being poorly
calibrated, which misleads users on a trust feature.

**Decision.** v1 exposes **qualitative confidence (high / medium / low)**. A calibrated numeric
score is deferred to Phase 2, once it can be validated.

**Alternatives considered.**
- *Numeric score in v1:* looks impressive, but an uncalibrated number erodes trust precisely where
  trust matters most.

**Consequences.**
- (+) Honest signal that doesn't overpromise; faster to ship.
- (−) Less granular than a number; some users may want finer detail (addressed in Phase 2).

---

## ADR-013 — Explainability describes evidence combination, not model cognition

**Status:** Accepted

**Context.** "Reasoning path" could be misread as exposing the LLM's internal thought process, which
is not something the system can truthfully reproduce.

**Decision.** Define the reasoning path as a description of **how the system combined retrieved
evidence** — which sources were retrieved, how they were ranked, which graph connections were
traversed. It explicitly does **not** claim to reproduce the language model's internal reasoning.

**Alternatives considered.**
- *Present model "reasoning" as if it were the LLM's true internal process:* misleading and
  technically indefensible.

**Consequences.**
- (+) Technically honest; defensible to expert scrutiny; still genuinely useful to users.
- (−) Requires careful UI wording so users understand what the path represents.

---

## ADR-014 — Defer autonomous multi-agent orchestration to Phase 2

**Status:** Accepted

**Context.** An agentic core (planner, orchestrator, tool manager) is attractive, but local LLMs are
notably weaker at reliable multi-step orchestration, and the agent layer would dominate the build.

**Decision.** Phase 1 ships a single, well-built GraphRAG retrieval-and-reasoning pipeline. Agent
orchestration, tool management, and automation are deferred to Phase 2, layered onto the existing
event bus.

**Alternatives considered.**
- *Build the full agentic core in v1:* impressive on paper, but slow, unreliable on local models,
  and the single biggest threat to ever shipping.

**Consequences.**
- (+) A shippable, demoable Phase 1; the event bus already makes agents an additive later step.
- (−) v1 is "smart search + reasoning," not yet an autonomous agent (an intentional sequencing).

---

## ADR-015 — LanceDB locked as the Phase 1 vector store

**Status:** Accepted

**Context.** The PRD and Build Plan originally presented ChromaDB and LanceDB as an open choice,
carried unresolved into the first storage ticket (T2.4). An unresolved choice at the first storage
ticket blocks implementation.

**Decision.** LanceDB is the Phase 1 vector store. ChromaDB remains documented as a fallback option
only — it is not implemented in Phase 1 and would require a new decision (and likely a new ADR) to
adopt later.

**Alternatives considered.**
- *ChromaDB:* a comparable local-first embedded vector store; simpler API in places, but no
  functional requirement favors it over LanceDB for Phase 1's needs.
- *Leave undecided until benchmarking:* keeps options open but blocks T2.4 from starting cleanly.

**Consequences.**
- (+) T2.4 and all downstream retrieval code (T3.1+) have one concrete target, no branching logic.
- (−) Switching later means a migration — mitigated by the Index Manager's Re-index operation and
  ADR-006's storage-engine swappability, which already assumes this cost is acceptable.

---

## ADR-016 — Event bus is introduced at Milestone 5, not from the start of Phase 1

**Status:** Accepted

**Context.** ADR-003/ADR-004 establish the event bus as the system's asynchronous backbone, and the
Design Doc's event taxonomy (`file.chunked`, `vectors.indexed`, `graph.updated`, etc.) reads as if
these events fire from the first ingestion milestone. But the Build Plan's sequencing principle is
to avoid building Core Services scaffolding before a second consumer justifies it, and explicitly
defers the event bus to Milestone 5 (T5.4), when the UI becomes a real subscriber to `file.ready`.

**Decision.** Milestones M1–M4 perform file-lifecycle state transitions via **direct, synchronous
writes** to `files.status` (and related tables) — no publish/subscribe involved. The event bus is
introduced at **Milestone 5**, at which point the same state transitions additionally publish
events (`file.ready`, `graph.updated`, etc.) so the UI (Library view) can subscribe. ADR-003/ADR-004
describe the bus's *role* once it exists; this ADR fixes *when* it starts existing.

**Alternatives considered.**
- *Build the event bus in Milestone 0/1:* matches the "central to the architecture" framing
  literally, but there is no subscriber until the UI exists in M5 — pure premature infrastructure.

**Consequences.**
- (+) M1–M4 stay simple (CLI-only, no pub/sub plumbing) while still ending in something runnable.
- (+) When the bus lands in M5, it wraps already-working, already-tested state transitions rather
  than being built and debugged at the same time as the state machine itself.
- (−) The Design Doc's event taxonomy (A8) describes the end-state, not what M1–M4 actually emit —
  readers must cross-reference this ADR to know events aren't live until M5.

---

## Decision index

| ADR | Decision | Status |
|---|---|---|
| 001 | Local-first, fully offline | Accepted |
| 002 | GraphRAG over vector-only | Accepted |
| 003 | Central in-process event bus | Accepted |
| 004 | Events for async only; queries direct | Accepted |
| 005 | Core Services vs. Intelligence Engine | Accepted |
| 006 | Layered API boundaries | Accepted |
| 007 | Heuristic intent router in v1 | Accepted |
| 008 | Data source plugin interface | Accepted |
| 009 | SQLite for metadata & app state | Accepted |
| 010 | Local sync, desktop source of truth | Accepted |
| 011 | Offline update packages | Accepted |
| 012 | Qualitative confidence in v1 | Accepted |
| 013 | Explainability = evidence, not cognition | Accepted |
| 014 | Defer multi-agent to Phase 2 | Accepted |
| 015 | LanceDB locked as Phase 1 vector store | Accepted |
| 016 | Event bus introduced at Milestone 5, not from Phase 1 start | Accepted |

---

*End of document.*
