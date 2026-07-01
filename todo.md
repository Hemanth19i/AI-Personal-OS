# AI Personal OS — TODO

Phase 1 task tracker. Check things off as you go. Each task is small enough to finish in one sitting
and ends in something you can run. Build top-to-bottom; don't skip ahead.

**Reference docs:** PRD v1.3 (Tech Stack is PRD §9 — no separate file) · ADR · Design Doc · Build Plan
**MVP done =** drop a doc → indexed locally → ask questions → cited answers → see *why*, fully offline.

---

## 🎯 Tonight (the only thing that matters right now)

- [ ] **T1.1** Create `files` table in SQLite (`id, workspace_id, path, hash, status, error, created_at, updated_at`; `workspace_id` hardcoded to `"default"`)
- [ ] **T1.2** Watch a folder with `watchdog`; print the path of any new file
- [ ] **T1.3** Wait for write-completion (size-stability) before processing
- [ ] **T1.4** Hash (SHA-256) + insert a `pending` row; skip if hash already seen

> ✅ Win condition: drop a PDF → one row appears → drop it again → nothing happens.

---

## Milestone 0 — Skeleton

- [ ] **T0.1** Repo + venv + deps file + `main.py` that runs
- [ ] **T0.2** Config (watched folder, data dir, model names) + create data dirs on first run
- [ ] **T0.3** `SourceAdapter` interface (Scan/Parse/Watch/Metadata/Delete) + `FolderSource` stub

## Milestone 1 — Ingest one file into SQLite

- [ ] **T1.1** SQLite schema (incl. `workspace_id`, `error`) + thin data-access layer (no raw SQL elsewhere)
- [ ] **T1.2** Folder watcher (`watchdog`)
- [ ] **T1.3** Write-completion guard
- [ ] **T1.4** Hash + register (dedup)

## Milestone 2 — Process into searchable chunks

- [ ] **T2.1** Text extraction: PDF / TXT / Markdown (`pending → parsing → parsed`)
- [ ] **T2.2** Chunking with page/offset metadata → `chunks` table (`→ chunked`)
- [ ] **T2.3** Local embeddings (nomic-embed) for each chunk, via a lightweight Model Manager
- [ ] **T2.4** Write vectors to LanceDB keyed by `chunk_id`, behind a minimal Index Manager (index/reindex only) (`→ ready`)
- [ ] **T2.5** OCR fallback (Tesseract) for scanned PDFs with no text layer

> ✅ Win: drop a PDF/TXT/Markdown file — including a scanned PDF — and it reaches `ready` with vectors stored.

## Milestone 3 — Ask a question (vector RAG)

- [ ] **T3.1** Semantic retrieval: embed query → top-K chunks → print with source+page
- [ ] **T3.2** Cross-encoder reranker on the top-K chunks before context building
- [ ] **T3.3** Answer with citations via Ollama (answer from context only, cite chunks)

> ✅ Win: a working offline RAG second brain via CLI. This alone is demoable.

## Milestone 4 — Knowledge graph (the differentiator)

- [ ] **T4.1** Entity + relationship extraction per doc (people, concepts, relates-to)
- [ ] **T4.2** Persist entities/edges in Kùzu (or SQLite-backed graph)
- [ ] **T4.3** Graph-aware retrieval (pull graph neighbors into context)
- [ ] **T4.4** Heuristic intent router (simple vs. graph; default to richer path when unsure)

> ✅ Win: relationship questions work; routing is visible in logs.

## Milestone 5 — Explainability + UI

- [ ] **T5.1** Structured `AnswerResult` (answer, sources, reasoning_path, confidence, graph_path)
- [ ] **T5.2** Tauri + React shell with a single Chat view calling the Core API
- [ ] **T5.3** UI pillars in order: Chat → Library → Search → (Graph Explorer) → (Timeline)
- [ ] **T5.4** Introduce event bus; Library updates live on `file.ready` (toast)

> ✅ Win: drop a file, watch it go ready live, ask in a window, see why.

## Milestone 6 — Robustness

- [ ] **T6.1** State-machine recovery: resume after crash; failed files retryable; one bad file never stalls
- [ ] **T6.2** Task queue so embedding/OCR/reasoning don't block each other
- [ ] **T6.3** Backup / restore / workspace export
- [ ] **T6.4** System Health view (RAM, LLM status, queue depth, storage)
- [ ] **T6.5** Offline validation: full flow with the network physically off

## Milestone 7 — Ship

- [ ] **T7.1** Performance pass vs targets (100p PDF <10s, query <2s, cold start <5s, <2GB RAM)
- [ ] **T7.2** README + link the phase docs; GIF of drop → query → explanation
- [ ] **T7.3** Demo video (offline end-to-end), add to repo

> ✅ **PHASE 1 DONE** when the MVP done-definition is met, fully offline.

---

## Working rules (pin these)

- [ ] One task at a time; each ends in something runnable. If it doesn't, split it.
- [ ] Persist the next `status` **before** doing the work (crash-safe).
- [ ] UI never touches storage directly — always via Core API.
- [ ] Models only through the Model Manager.
- [ ] Index Manager: Index/Re-index only in Phase 1 — no optimize/repair/migrate yet.
- [ ] Event bus = notifications only; queries are direct calls.
- [ ] Event bus doesn't exist until M5 — M1–M4 use direct writes (ADR-016).
- [ ] Never mutate original files in place.
- [ ] Don't pre-build Core Services before something needs them.

---

## Parking lot (Phase 2/3 — do NOT start these now)

- [ ] Agent orchestrator, tool manager, automation rules
- [ ] Learned intent router; calibrated numeric confidence
- [ ] Versioned knowledge graph + "how my understanding evolved" timeline
- [ ] Mobile app + bidirectional sync
- [ ] Audio/voice-memo transcription (Whisper) — additional `SourceAdapter` implementation
- [ ] Remote data-source plugins (GitHub, Email, Drive, OneDrive, Photos) + Plugin SDK
- [ ] Full security hardening (biometric lock, etc.)

---

*Keep this file in the repo root. Update it as you build.*
