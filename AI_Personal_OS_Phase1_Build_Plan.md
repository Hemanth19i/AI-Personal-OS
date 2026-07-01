# Phase 1 Build Plan — AI Personal OS

An ordered ticket list to take Phase 1 from nothing to the MVP done-definition:
*a user can drop a document, have it indexed locally, ask questions, receive cited answers, and
understand why those answers were produced.*

**Sequencing principle:** every ticket ends with something you can **run and see**. No ticket
depends on something not yet built. Build the spine first (ingest → store → retrieve → answer),
then add the graph, explainability, and UI polish. Resist building Core Services scaffolding before
you have a reason to.

**Suggested stack for Phase 1:** Python core + SQLite + **LanceDB** (locked, ADR-015) + Ollama for
the LLM, accessed through a lightweight Model Manager. Defer Tauri/React UI until Milestone 5 — use
a CLI until then so you're testing logic, not fighting a UI.

---

## Milestone 0 — Project skeleton

**T0.1 — Repo + environment**
Create the repo, virtual environment, dependency file, and a README stub. Add a `main.py` that
prints "AI Personal OS — alive". *Done when:* `python main.py` runs.

**T0.2 — Config + paths**
Define a config (watched folder path, data directory, model names). Create the data directory
structure on first run. *Done when:* the app creates its data dirs and reads a config file.

**T0.3 — SourceAdapter interface + FolderSource stub**
Define the `SourceAdapter` contract (`Scan/Parse/Watch/Metadata/Delete`, per ADR-008) and a
`FolderSource` class implementing it — stubs are fine at this point, real logic lands in M1/M2.
*Done when:* `FolderSource` exists, satisfies the interface, and is imported (not yet called) by
the watcher code you're about to write in T1.2.

---

## Milestone 1 — Ingest one file into SQLite *(your "tonight" target)*

**T1.1 — SQLite schema + connection**
Create the `files` table per Design Doc A4: `id, workspace_id, path, hash, status, error,
created_at, updated_at`. Status is the state machine value (`pending` to start); `workspace_id` is
hardcoded to `"default"` in Phase 1 (no multi-workspace UI yet). Add a thin data-access function
layer (don't let the rest of the app write SQL directly — this is ADR-006 in miniature). *Done
when:* you can insert and read a file row, including its `workspace_id`, from a quick test.

**T1.2 — Folder watcher**
Use `watchdog` to watch the configured folder. On a new file, print its path. Implements
`FolderSource.Watch()` from T0.3. *Done when:* dropping a file into the folder prints its path in
the terminal.

**T1.3 — Write-completion guard**
Before processing, wait until the file size is stable (stops changing) so you never read a
half-copied file. *Done when:* copying a large file in only triggers processing once the copy
finishes.

**T1.4 — Hash + register**
On a stable new file: compute SHA-256, check SQLite for that hash. If new, insert a row with status
`pending`. If seen, skip. *Done when:* dropping a PDF creates exactly one `pending` row; dropping
the same file again creates nothing.

> 🎯 **This is your first real milestone.** Drop a PDF → a row appears in SQLite → drop it again →
> nothing. That's a working, demonstrable ingestion front door. Ship this before anything else.

---

## Milestone 2 — Process a file into searchable chunks

**T2.1 — Text extraction (PDF / TXT / Markdown)**
Add parsers for PDF (text layer), TXT, and Markdown — `FolderSource.Parse()` from T0.3. Update
status `pending → parsing → parsed`. *Done when:* a dropped file of any of the three types has its
text extracted and logged.

**T2.2 — Chunking**
Split extracted text into overlapping chunks, keeping page/offset metadata. Store chunks in a
`chunks` table (`id, file_id, text, page, position`). Status → `chunked`. *Done when:* you can list
the chunks for a file with their page numbers.

**T2.3 — Local embeddings**
Introduce a lightweight `ModelManager` that wraps Ollama for both the embedding model and (later,
T3.3) the LLM — just enough abstraction to swap models by name, no more. Embed each chunk with a
local model (e.g. nomic-embed) through it. *Done when:* each chunk has a vector (log the dimensions
to confirm).

**T2.4 — Vector store**
Write embeddings into **LanceDB** keyed to chunk IDs, behind a minimal Index Manager exposing only
`index()` and `reindex()` (PRD §6.9 — advanced index operations are deferred). Status → `ready`.
*Done when:* the vector DB reports the right number of vectors after ingesting a file.

**T2.5 — OCR fallback for scanned PDFs**
When a PDF has no extractable text layer, run it through Tesseract before chunking. This is an
ingestion-time fallback inside the `parsing`/`ocr` states (Design Doc A5) — not a reasoning-time
concern. *Done when:* a scanned (image-only) PDF reaches `ready` with real extracted text, not an
empty chunk.

> 🎯 **Milestone 2 result:** drop a PDF, TXT, or Markdown file — including a scanned PDF via OCR —
> and it goes all the way to `ready` with vectors stored. The full lifecycle (minus the graph) runs
> end to end.

---

## Milestone 3 — Ask a question, get an answer (vector RAG)

**T3.1 — Semantic retrieval**
Given a query, embed it and retrieve the top-K chunks from the vector DB. *Done when:* a CLI command
`ask "..."` prints the most relevant chunks with their source file + page.

**T3.2 — Cross-encoder reranker**
Re-rank T3.1's candidate chunks with a local cross-encoder before they reach the context builder
(Design Doc A6's pipeline: retrieval → reranker → context builder). *Done when:* `ask "..."` prints
the reranked order and you can see it differ from raw vector-similarity order on at least one
query.

**T3.3 — Answer generation with citations**
Feed the reranked chunks + the question to the local LLM (Ollama, via the T2.3 Model Manager).
Prompt it to answer **using only the provided context** and to cite which chunks it used. *Done
when:* `ask "..."` returns a written answer plus the source files/pages it drew from.

> 🎯 **Milestone 3 result:** this is a working offline RAG second brain. Drop docs, ask questions,
> get cited answers. If you stopped here you'd already have a demoable project.

---

## Milestone 4 — Add the knowledge graph (the GraphRAG differentiator)

**T4.1 — Entity & relationship extraction**
For each chunk (or document), prompt the local LLM to extract entities and relationships. Start
simple — people, concepts, and "mentions/relates-to" edges. *Done when:* you can print extracted
entities for a document.

**T4.2 — Graph store**
Persist entities and relationships in an embedded graph store (Kùzu) or a simple SQLite-backed graph.
*Done when:* you can query "what connects to entity X?" and get neighbors.

**T4.3 — Graph-aware retrieval**
Extend retrieval: alongside vector hits, pull in graph neighbors of matched entities to enrich
context. *Done when:* a relationship question ("how does X relate to Y?") returns context that
vector search alone would have missed.

**T4.4 — Intent router (heuristic)**
Add the cheap router: short/keyword-style queries take the simple path; relationship/complex queries
take the GraphRAG path; default to the richer path when unsure (ADR-007). *Done when:* simple lookups
are visibly faster than graph queries, and you can log which path was chosen.

> 🎯 **Milestone 4 result:** GraphRAG is real. You can answer relationship questions and you route
> intelligently. This is the technical centerpiece of the project.

---

## Milestone 5 — Explainability + the AI Workspace UI

**T5.1 — Explainability payload**
Make every answer return a structured object: answer, sources, reasoning path (which chunks/edges
were combined — framed per ADR-013, not as the LLM's internal cognition), qualitative confidence,
graph path. *Done when:* the CLI can dump this structure for any answer.

**T5.2 — Desktop shell (Tauri + React)**
Stand up the Tauri app with a single Chat view that calls your existing Core API. *Done when:* you
can ask a question in a window and see the answer.

**T5.3 — The five pillars (progressively)**
Add the UI pillars in priority order: **Chat** (done), **Library** (file list + ingestion status),
**Search**, **Graph Explorer**, **Timeline**. Ship them one at a time. *Done when:* Chat + Library +
Search work; Graph Explorer and Timeline can trail.

**T5.4 — Live status via the event bus**
Introduce the in-process event bus now that there are multiple subscribers worth decoupling
(ADR-016 — this is deliberately the first milestone that builds it, not M1): emit `file.ready`,
have the Library view update reactively with a toast. *Done when:* dropping a file updates the UI
live without a manual refresh.

> 🎯 **Milestone 5 result:** a real app — drop a file in the folder, watch it appear and become
> ready live, ask questions in a chat window, and see why each answer was produced.

---

## Milestone 6 — Make it robust (the "OS" promises)

**T6.1 — Failure philosophy in practice**
Make the state machine recover: a crash mid-ingestion resumes from the last good state; failed files
are marked `failed` and retryable; one bad file never stalls the queue. *Done when:* killing the
process mid-ingest and restarting resumes cleanly.

**T6.2 — Task queue**
Route embedding/OCR/reasoning jobs through a simple local queue so they don't block each other.
*Done when:* ingesting several files at once doesn't freeze querying.

**T6.3 — Backup & export**
Add snapshot/backup, restore, and workspace export. *Done when:* you can export a workspace and
restore it into a clean install.

**T6.4 — System Health view**
Surface RAM, LLM status, queue depth, storage. *Done when:* the UI shows why something is slow.

**T6.5 — Offline validation test**
Disable the network and run the full drop → query → answer flow. *Done when:* everything works with
the network physically off. (This is also your demo-video money shot.)

---

## Milestone 7 — Ship it

**T7.1 — Performance pass**
Measure against the targets: 100-page PDF < 10s index, query < 2s, cold start < 5s, < 2GB RAM. Tune
the worst offender. *Done when:* you've recorded real numbers (even if some targets need Phase-2 work).

**T7.2 — README + architecture docs**
Write the README; link the PRD and ADR. Show the drop → query → explanation flow with a GIF.

**T7.3 — Demo video**
Record the offline end-to-end walkthrough, same as you did for SecureRAG and ZTNA. Add it to the repo.

> ✅ **Phase 1 is DONE** when: a user can drop a document, have it indexed locally, ask questions,
> receive cited answers, and understand why those answers were produced — running fully offline.

---

## How to work through this

- **Build the spine first (M1→M3).** Ingest → store → retrieve → answer. That alone is a real project.
- **Then the differentiator (M4).** The graph is what makes it stand out — but only after the spine works.
- **UI comes late (M5).** Test logic in a CLI first; don't fight React while your retrieval is unproven.
- **One ticket at a time, each ending in something runnable.** If a ticket doesn't produce a visible
  result, it's too big — split it.
- **Don't pre-build Core Services.** Add the event bus, task queue, and managers at the moment you
  have a second consumer that justifies them (M5–M6), not before.

**Start tonight with T1.1 → T1.4:** one folder, one PDF, one row in SQLite.

---

*End of document.*
