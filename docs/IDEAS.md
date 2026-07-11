# Ideas — Deferred / Optional Scope

> **Ideas are intentionally NOT commitments.**
> Items in this document may never be implemented. Only [`ROADMAP.md`](ROADMAP.md) defines planned
> work. Treat everything below as "possible someday," not "promised."

Work that's real, documented in the frozen contract docs, and not obsolete — but not on
`ROADMAP.md` because none of it blocks Phase 1's MVP done-definition, and none of it should be
started without a deliberate decision to reopen that scope. Nothing here is scheduled.

## M5-UI — the desktop shell

The other half of the original Build Plan's Milestone 5 (`BuildPlan-v1.md` T5.2–T5.4):

- **T5.2 — Tauri + React desktop shell.** A single Chat view calling the existing Core
  API (`AnswerService`, `ingest`, `backup` — all already dependency-injectable and UI-agnostic).
- **T5.3 — Five UI pillars.** Chat → Library → Search → Graph Explorer → Timeline, per
  `DesignDoc-v1.md` Part B. Chat and Library are the highest-value pair; Graph Explorer is the
  highest-*impact* screen (it's what visually sells GraphRAG) but can trail.
- **T5.4 — Event bus.** Per ADR-016, this has no reason to exist until the UI is a real subscriber.
  Building the UI is what would justify building this — not the other way around.

**Trigger to reopen:** a decision that Phase 1 needs a GUI, not just a CLI. Until then, `cli.py`'s
`ask`/`retry`/`export`/`import` remain the only client of the Core API layer.

## M6.4 — System Health view

`PRD-v1.md` §6.13 / `DesignDoc-v1.md` §B8: RAM, LLM status, embedding queue depth, storage, surfaced
in a UI panel fed by `health.changed` events. Blocked on M5-UI + Event Bus (see dependency chain in
`ROADMAP.md` §6). Could theoretically be re-scoped as a CLI `status`/`health` command instead of a
UI panel — that would be a deliberate re-scope decision (changes what a contract doc says the feature
is), not a default substitution the way `retry`/`export` were.

## Cross-encoder reranker

Replace `LexicalReranker` with a real local cross-encoder (`PRD-v1.md` §9). The `Reranker` protocol
in `reranking.py` already supports this as a drop-in — no retrieval or answering code would need to
change. Per `ARCHITECTURE.md`, `LexicalReranker` is the accepted permanent implementation
unless a concrete quality problem justifies the swap — this isn't "debt to pay down," it's an
available upgrade with no current trigger.

## Full intent-router taxonomy

`intent.py` only routes Semantic/Graph. `PRD-v1.md` §6.7's full taxonomy (Simple, Keyword, Hybrid)
needs retrieval engines Phase 1 never built (a keyword/BM25 index, a hybrid combiner). Low priority —
the current heuristic's safe-default-to-richer-path behavior (ADR-007) already covers the cases these
would optimize for; they'd mainly buy latency, not new capability.

## Entity/edge provenance

Extracted entities/edges (`extraction.py`, T4.1) aren't linked back to the chunk or file they came
from — flagged as debt at the time of T4.1. Would let the Graph Explorer (if M5-UI is built) show
"this relationship came from these documents," and would let `Explanation.graph_path` (see below)
actually list traversed entities/edges with their source.

## `Explanation.graph_path` as a real traversed-edge list

`DesignDoc-v1.md` §A7 specifies `graph_path: [ entities/edges traversed ]`. The shipped `Explanation`
only carries `graph_expanded: bool` and `graph_relation_count: int` — a count, not a path. Depends
loosely on entity/edge provenance above to be fully meaningful (a path without provenance can name
edges but not which document backs them).

## Typed Memory

`PRD-v1.md` §6.5/§6.6: conversation, knowledge, workspace, and preference memory as a named Core
Service. Zero tables, zero code today — `storage.py` only has `files`/`chunks`/`entities`/`edges`;
`DesignDoc-v1.md` §A4's `workspaces`/`conversations`/`messages`/`preferences`/`app_state` tables were
never created. No current consumer needs this (single workspace, no conversation history UI, no
learned preferences) — same "don't build it before something needs it" principle that's governed
every other deferred item here.

## Security hardening

`PRD-v1.md` §6.18: AES encryption at rest, credential vault, permission manager, biometric lock. Note
this section sits in mild tension with `ADR-v1.md` ADR-014, which frames "full security hardening" as
Phase 2 scope — worth resolving which is authoritative if this is ever picked up, not just implementing
§6.18 literally.

## Offline update packages

`PRD-v1.md` §6.16 (Import → Verify → Install for app/model updates, ADR-011). **Never had a Build Plan
ticket at all** — this is a gap between the PRD and the original Build Plan itself, predating any
implementation decision. If picked up, it needs a new roadmap ticket defined from scratch, not a
"missing implementation" of an existing one.

## Named `ModelManager` / `IndexManager` abstractions

`PRD-v1.md` §6.5/§6.9 name these as components. What exists instead: `embedding.py`/`Embedder` and
`llm.py`/`LLM` as two parallel protocol-based modules (functionally the Model Manager, just not a
single class), and indexing happens implicitly through `VectorStore.add()` (functionally the Index
Manager's `index()`, no separate class). **Not planned** — the current shape is simpler and achieves
the same behavior; building the named abstractions would be structure for its own sake with no
functional gain. Listed here only so the naming difference is documented, not because it's queued
work.
