# Roadmap v2 — AI Personal OS

**Status:** Canonical. Supersedes `docs/historical/BuildPlan-v1.md` for sequencing decisions from
Milestone 5 onward. M0–M4 and M6.1–M6.3 needed no correction — see §1.

**Last reconciled:** 2026-07-11, against repository state at commit `39f2f72` (tag `milestone-6.3`,
372 tests passing), by full comparison of git history against `BuildPlan-v1.md`, `PRD-v1.md`,
`DesignDoc-v1.md`, and `ADR-v1.md`.

This document is self-contained: it explains *why* the plan changed, not just *what* changed, so a
future reader doesn't need to dig through commit history or old conversations to understand the
current architecture's shape.

---

## 1. Completed milestones (unchanged from the original plan)

M0 (skeleton), M1 (ingest→SQLite), M2 (chunks/vectors/OCR), M3.1/M3.3 (retrieval + cited answers),
M4 (knowledge graph — extraction, persistence, graph-aware retrieval, intent router), M6.1 (crash
recovery), M6.2 (task queue), M6.3 (backup/export) all shipped matching the original Build Plan's
ticket numbering and scope, verified against every commit body and the annotated tags
`milestone-2`, `milestone-4`, `milestone-6.1`, `milestone-6.2`, `milestone-6.3`. No correction needed
for any of these — they're recorded here only so this document is a complete picture on its own.

Two small, deliberate substitutions happened inside otherwise-matching milestones (kept — see §2 for why):
- **M3.2 reranker** is `LexicalReranker` (query-term overlap), not a cross-encoder.
- **M4.2 graph store** is SQLite (`entities`/`edges` tables in `storage.py`), not Kùzu.

## 2. Why the plan diverged

### M5 was split, not completed as originally scoped

The original Build Plan's M5 bundled four tickets: T5.1 (explainability payload), T5.2 (Tauri+React
desktop shell), T5.3 (five UI pillars), T5.4 (event bus). Only T5.1's *scope* was actually built —
the repo's own git history relabels T5.1/T5.2/T5.3 as three explainability sub-tickets (reasoning
trace, qualitative confidence, structural evidence verification; see `explainability.py`), none of
which touch UI or the event bus.

**Why:** every ticket after M4 needed *something* to stand in for the not-yet-built UI, and the
project consistently chose to substitute a CLI command and keep shipping rather than stop to build
Tauri+React. This is stated explicitly, at the time, in three separate commit messages:

- T6.1 (`5b27810`): *"the CLI stands in for the Library UI's not-yet-built Retry button."*
- T6.2 (`cebaf88`): *"No event bus... the frozen event bus (Build Plan T5.4) was never built in this
  project."*
- T6.3 (`ecbad4e`): *"the CLI stands in for the not-yet-built Workspace switcher's export/restore
  actions."*

This was a good engineering call, not a shortcut: it kept every milestone demoable through a CLI
without fighting a UI while retrieval/graph/explainability were still unproven, exactly matching the
Build Plan's own stated principle *("test logic in a CLI first; don't fight React while your
retrieval is unproven")* — just applied further than the original plan anticipated. The mistake was
never writing the decision back into a doc, which is what this reconciliation fixes.

**Resolution:** M5 is retroactively split into two milestones (§3).

### Why CLI replaced the UI at every later milestone

Same reasoning as above, applied consistently: `ask`, `retry`, `export`/`import` are all Core-API-shaped
CLI commands that do exactly what the corresponding not-yet-built UI action would do, wired through
the same dependency-injected service layer the UI would eventually call. This kept the layered
boundary (UI → Core API → Platform Services → Storage, ADR-006) intact — the CLI *is* a valid client
of that boundary, so when the real UI is eventually built it slots in alongside the CLI rather than
replacing an ad-hoc shortcut.

### Why the Event Bus is still deferred

ADR-016 (in `docs/historical/ADR-v1.md`) fixed the event bus to Milestone 5, specifically gated on
the UI existing as "a real subscriber" — the whole point being not to build pub/sub infrastructure
before a second consumer justifies it. Since the UI was never built, the event bus correctly has no
reason to exist yet either. The repo is *more* consistent with ADR-016 today than it would be if the
bus had been built on schedule with no UI to subscribe to it. This isn't drift — it's the ADR working
as designed.

### Why SQLite replaced Kùzu for the graph store

`DesignDoc-v1.md` §A4/§9 and `PRD-v1.md` §9 both listed Kùzu *or* SQLite-backed as open options for
Phase 1's graph store — this was never a locked decision the way LanceDB was (ADR-015). `storage.py`
chose SQLite to avoid a second storage engine for a Phase 1 that already has SQLite as its
metadata/app-state store (ADR-009): one less engine to run, one less connection lifecycle to manage,
and `entities`/`edges` fit naturally as ordinary tables alongside `files`/`chunks`. This is a legitimate
choice within the documented option space, not a deviation from a locked decision.

### Why `LexicalReranker` exists instead of a cross-encoder

`PRD-v1.md` §9 and the Build Plan named "a local cross-encoder" for T3.2. Shipping one in Phase 1
means a model download and a new dependency for a component whose only job is to prove the
reranked order can differ from raw vector order (the ticket's actual done-condition). `LexicalReranker`
does that with zero dependencies, is deterministic and instantly testable, and sits behind the same
`Reranker` protocol a real cross-encoder would — so replacing it later is a drop-in, not a rewrite.
Per project convention (see `docs/historical` note on this), this stays as the permanent Phase 1
implementation, not a placeholder to schedule — see `ARCHITECTURE.md`.

### Why System Health (T6.4) is blocked

`DesignDoc-v1.md` §B8 specifies System Health as a UI panel ("Health glance... opens the System
Health panel") fed by `health.changed` events over the event bus. Both the panel and the bus it would
run on are M5-UI scope, which doesn't exist. T6.4 isn't obsolete — it's real PRD scope (§6.13) — it's
just correctly sequenced after infrastructure that hasn't been built, and re-scoping it to a CLI
stand-in (the way T6.1/T6.3 did for their UI actions) is a decision to make deliberately when M5-UI
is revisited, not by default.

## 3. Current position

_Updated 2026-07-11: M6.5 and M7.1 shipped; Architecture Freeze v1.0 now in effect._

```
✓ M0    Project skeleton
✓ M1    Ingest one file into SQLite
✓ M2    Process into searchable chunks
✓ M3    Vector RAG (retrieval, lexical reranker, cited answers)
✓ M4    Knowledge graph / GraphRAG (Semantic + Graph strategies)
✓ M5-Explainability   Explanation / confidence / evidence verification
⊘ M5-UI               Tauri+React shell, five pillars, Event Bus — NOT STARTED, NOT SCHEDULED
✓ M6.1  Crash-safe resume and retry
✓ M6.2  Background task queue
✓ M6.3  Manual workspace export/import
✓ M6.5  Offline validation test          (tag milestone-6.5)
⊘ M6.4  System Health view              — BLOCKED on M5-UI + Event Bus
──────────────────────────────────────────────────────────
  Architecture Freeze v1.0 — IN EFFECT (M6 closed) — see ARCHITECTURE.md
──────────────────────────────────────────────────────────
✓ M7.1  Model evaluation & performance benchmark  (tag perf-baseline-v1.0; default → qwen2.5:3b)
──────────────────────────────────────────────────────────  ← current position
  M7.2  Documentation & release readiness  — in progress
  M7.3  Demo video (offline end-to-end)
        (M7 scoped to the CLI surface unless M5-UI reopens)
```

**Phase 1's own MVP done-definition** — *"a user can drop a document, have it indexed locally, ask
questions, receive cited answers, and understand why those answers were produced"* — **is met today**,
via the CLI. The UI was always the *how*, not a precondition of *whether* Phase 1 is done. M6 is now
closed; M5-UI/M6.4 remain a distinct, optional second track (§5). What's left of Phase 1 is
release polish: M7.2 (docs) and M7.3 (demo video).

## 4. Remaining mandatory work

- **M7.2 — Documentation & release readiness.** README install/quick-start (Ollama + model pulls),
  current status, CLI reference, benchmark link, known limitations; `LICENSE`; this roadmap and
  `todo.md` kept current. Documentation only — no code, no architecture change.
- **M7.3 — Demo video.** Offline end-to-end walkthrough, added to the repo.

M6.5 (offline validation) and M7.1 (model evaluation → `qwen2.5:3b` default) are **done** — see
`../benchmarks/results/winner.md` for the model decision. Everything else either has a hard
dependency (M5-UI → M6.4) or is optional (§5). Small, contained fixes (citation `page` field not
surfacing in `Source`; `graph_path` being a count rather than a traversed-edge list; the
`llama3.2:3b` `USED_CHUNKS` footer-format incompatibility surfaced in M7.1) are bugfixes, not
roadmap items — track and fix them directly, don't give them milestone numbers.

## 5. Optional / future work

Tracked in [`IDEAS.md`](IDEAS.md), not this roadmap, because none of it blocks Phase 1's
done-definition and none of it should be started without a deliberate decision to reopen that scope:

- M5-UI (Tauri+React, five pillars, Event Bus)
- M6.4 (System Health view — depends on M5-UI)
- Full intent-router taxonomy (Keyword/Simple/Hybrid strategies)
- Entity/edge provenance
- Typed Memory (conversation/knowledge/workspace/preference)
- Security hardening (AES at rest, credential vault, biometric lock)
- Offline update packages (`PRD-v1.md` §6.16 — never had a Build Plan ticket at all, a pre-existing
  gap between the PRD and the original Build Plan, not an implementation miss)

## 6. Dependencies

```
M6.4 (System Health)  →  M5-UI  →  Event Bus
```

Nothing else in §4/§5 has a dependency — each item is independently startable against the current
CLI/backend architecture.

## 7. Documentation map

| Question | Where to look |
|---|---|
| What's built, and why it works the way it does | This document + the repository itself |
| What rules are currently binding on new code | `ARCHITECTURE.md` |
| What's intentionally deferred | `IDEAS.md` |
| Why a past architectural decision was made | `docs/historical/ADR-v1.md` (still authoritative, relocated not retired) |
| What the original plan looked like before reality diverged | `docs/historical/BuildPlan-v1.md`, `PRD-v1.md`, `DesignDoc-v1.md` |
