# AI Personal OS — TODO

Phase 1 task tracker. Check things off as you go.

**Canonical plan:** [`docs/ROADMAP.md`](docs/ROADMAP.md) — read that first for the *why*
behind anything below. This file is just the checklist view of it.
**Reference docs:** [`docs/historical/`](docs/historical/) (frozen v1 PRD/ADR/Design
Doc/Build Plan) · [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (binding rules) ·
[`docs/IDEAS.md`](docs/IDEAS.md) (deferred scope)
**MVP done =** drop a doc → indexed locally → ask questions → cited answers → see *why*, fully
offline. **Met as of Milestone 6.3, via the CLI.**

---

## Milestone 0 — Skeleton

- [x] **T0.1** Repo + venv + deps file + `main.py` that runs
- [x] **T0.2** Config (watched folder, data dir, model names) + create data dirs on first run
- [x] **T0.3** `SourceAdapter` interface (Scan/Parse/Watch/Metadata/Delete) + `FolderSource` stub

## Milestone 1 — Ingest one file into SQLite

- [x] **T1.1** SQLite schema (incl. `workspace_id`, `error`) + thin data-access layer (no raw SQL elsewhere)
- [x] **T1.2** Folder watcher (`watchdog`)
- [x] **T1.3** Write-completion guard
- [x] **T1.4** Hash + register (dedup)

## Milestone 2 — Process into searchable chunks

- [x] **T2.1** Text extraction: PDF / TXT / Markdown (`pending → parsing → parsed`)
- [x] **T2.2** Chunking with page/offset metadata → `chunks` table (`→ chunked`)
- [x] **T2.3** Local embeddings (nomic-embed) for each chunk, via a lightweight Model Manager
- [x] **T2.4** Write vectors to LanceDB keyed by `chunk_id`, behind a minimal Index Manager (index/reindex only) (`→ ready`)
- [x] **T2.5** OCR fallback (Tesseract) for scanned PDFs with no text layer *(repo T2.7)*

## Milestone 3 — Ask a question (vector RAG)

- [x] **T3.1** Semantic retrieval: embed query → top-K chunks → print with source+page
- [x] **T3.2** Reranker on the top-K chunks before context building *(shipped as `LexicalReranker`,
      not a cross-encoder — deliberate, see Roadmap v2 §2; `Reranker` protocol allows swap-in later)*
- [x] **T3.3** Answer with citations via Ollama (answer from context only, cite chunks)

## Milestone 4 — Knowledge graph (the differentiator)

- [x] **T4.1** Entity + relationship extraction per doc (people, concepts, relates-to)
- [x] **T4.2** Persist entities/edges *(shipped SQLite-backed, not Kùzu — deliberate, see Roadmap v2 §2)*
- [x] **T4.3** Graph-aware retrieval (pull graph neighbors into context)
- [x] **T4.4** Heuristic intent router *(Semantic/Graph only — Keyword/Simple/Hybrid deferred, see `docs/IDEAS.md`)*

## Milestone 5 — split into two (see Roadmap v2 §2 for why)

### M5-Explainability — ✅ done

- [x] **T5.1** Structured `Explanation` (strategy, retrieval/graph/rerank counts, grounding, confidence, evidence)
- [x] CLI exposes it via `ask --explain`

### M5-UI — ⊘ not started, not scheduled (tracked in `docs/IDEAS.md`, not here)

- [ ] Tauri + React shell with a single Chat view calling the Core API
- [ ] UI pillars in order: Chat → Library → Search → (Graph Explorer) → (Timeline)
- [ ] Event bus; Library updates live on `file.ready` (toast)

## Milestone 6 — Robustness

- [x] **T6.1** State-machine recovery: resume after crash; failed files retryable; one bad file never stalls
- [x] **T6.2** Task queue so embedding/OCR/reasoning don't block each other
- [x] **T6.3** Backup / restore / workspace export
- [x] **T6.5** Offline validation: loopback-only socket guard + opt-in real-backend E2E
      (`AIPOS_RUN_OFFLINE_E2E=1`); manual network-off procedure documented in README
- [ ] **T6.4** System Health view *(⊘ BLOCKED on M5-UI + Event Bus — see Roadmap v2 §2)*

> **Architecture Freeze v1.0** takes effect once M6 closes (T6.5 done) — see
> [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). From then on, new work extends the
> existing architecture rather than redesigning it.

## Milestone 7 — Ship

- [ ] **T7.1** Performance pass vs targets (100p PDF <10s, query <2s, cold start <5s, <2GB RAM)
- [ ] **T7.2** README + link the phase docs; GIF of drop → query → explanation
- [ ] **T7.3** Demo video (offline end-to-end), add to repo

> Scoped to the CLI surface unless M5-UI is deliberately reopened.

---

## Working rules (pin these)

- [ ] One task at a time; each ends in something runnable. If it doesn't, split it.
- [ ] Persist the next `status` **before** doing the work (crash-safe).
- [ ] UI never touches storage directly — always via Core API.
- [ ] Models only through the Model Manager (shipped as `embedding.py`/`llm.py` — see `docs/IDEAS.md`
      on why no unified class was built).
- [ ] Index Manager: Index/Re-index only in Phase 1 — no optimize/repair/migrate yet.
- [ ] Event bus doesn't exist yet — see M5-UI above. Direct writes/calls everywhere until it does.
- [ ] Never mutate original files in place.
- [ ] Don't pre-build Core Services before something needs them.
- [ ] Small, contained fixes (e.g. a missing field on a citation) are bugfixes — don't give them
      milestone numbers. Reserve entries in this file for real scope.

---

## Parking lot (Phase 2/3 — do NOT start these now)

- [ ] Agent orchestrator, tool manager, automation rules
- [ ] Learned intent router; calibrated numeric confidence
- [ ] Versioned knowledge graph + "how my understanding evolved" timeline
- [ ] Mobile app + bidirectional sync
- [ ] Audio/voice-memo transcription (Whisper) — additional `SourceAdapter` implementation
- [ ] Remote data-source plugins (GitHub, Email, Drive, OneDrive, Photos) + Plugin SDK
- [ ] Full security hardening (biometric lock, etc.) — see `docs/IDEAS.md`

---

*Keep this file in the repo root. Update it as you build. For the narrative behind any line above,
read `docs/ROADMAP.md` first.*
