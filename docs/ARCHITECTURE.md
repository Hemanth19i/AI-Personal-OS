# Architecture Freeze v1.0

**Status: IN EFFECT** — Milestone 6 is closed (T6.1–T6.3 and T6.5 shipped; T6.4 intentionally
deferred, blocked on M5-UI — see [`ROADMAP.md`](ROADMAP.md)).

Architecture Freeze v1.0 is now in effect. Future work should focus on features, reliability,
performance, documentation, and user experience. Architectural changes require a new ADR.

The architectural shape of AI Personal OS is settled. From here forward, work on this
repository should **extend** this architecture, not redesign it. New tickets are features,
bugfixes, performance work, or polish — not restructuring.

## Frozen boundaries

- **SQL only in `storage.py`.** No other module writes SQL or touches the SQLite connection directly.
- **LanceDB only in `vector_store.py`.** No other module imports `lancedb`.
- **`ingest.py` remains the sole write coordinator** for the file lifecycle.
- **Constructor dependency injection everywhere.** No globals, no singletons, no service locators.
- **Protocol-first abstractions.** New backends (embedder, LLM, reranker, OCR engine, task queue,
  retriever) implement an existing `Protocol` rather than special-casing callers.
- **`Explanation` (`explainability.py`) is the explainability extension point.** New observable
  facts about how an answer was produced get added as `Explanation` fields, not a parallel mechanism.
- **`GraphRetriever` / `RoutedRetriever` remain the retrieval strategy seam.** New retrieval
  strategies (Keyword, Hybrid, Agent) implement `Retriever`, not fork the read path.
- **`TaskQueue` (`task_queue.py`) remains the infrastructure boundary for background work.** It stays
  domain-agnostic — no ingestion-specific knowledge leaks into it.
- **No event bus, no UI, until a real second consumer exists.** ADR-016's own test still applies:
  don't build pub/sub infrastructure before something needs it.

## What "frozen" means in practice

- These boundaries are the default answer to "where does this new code go?" — not a debate to
  reopen per ticket.
- **Breaking any boundary above requires a new ADR** in `docs/historical/ADR-v1.md` (ADR-017+),
  following that document's existing immutable-record convention — explain what's changing and why,
  don't edit history.
- This freeze governs *structure*, not *scope*. Building the deferred UI, event bus, typed Memory,
  or security hardening (see [`IDEAS.md`](IDEAS.md)) is still open — but when built, it must fit
  inside these boundaries (e.g., the UI calls a Core API, never SQLite or LanceDB directly), not
  reshape them.
- If a genuinely new boundary is needed (e.g., a second storage engine, a plugin registry), that's
  exactly the kind of decision that gets a new ADR before code, not after.

## Source of truth

- **What's built:** the repository itself, plus [`ROADMAP.md`](ROADMAP.md) for the reconciled
  current-state narrative.
- **What's still intended but not built:** [`IDEAS.md`](IDEAS.md).
- **Why past decisions were made:** `docs/historical/ADR-v1.md` (still authoritative for rationale,
  relocated not retired).
- **What the original plan looked like before implementation diverged:**
  `docs/historical/BuildPlan-v1.md`, `PRD-v1.md`, `DesignDoc-v1.md` — frozen, for history only.

---

## Architecture Freeze v1.0

**In effect as of Milestone 6 closing** (tag `milestone-6.5`).

The architectural boundaries above are considered stable. The foundation is no longer in flux.

Future work should focus on:

- Features
- Reliability
- Performance
- UX
- Documentation

**Breaking any of these architectural boundaries requires a new ADR** (ADR-017+ in
`docs/historical/ADR-v1.md`). Extend the architecture; don't redesign it.
