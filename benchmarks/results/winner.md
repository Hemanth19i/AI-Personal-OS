# Recommended default model — AI Personal OS (M7.1)

**Decision (2026-07-11): the default generation model is `qwen2.5:3b`.**
Reference machine: RTX 3060 Laptop (6 GB VRAM), Ryzen 9 5900HX, 15.4 GB RAM, Ollama 0.31.1.
Evidence: [`comparison.md`](comparison.md) and the per-model files in this directory.

## The four models and why each sits where it does

### ✅ Recommended default — `qwen2.5:3b`
The best *engineering* tradeoff, not the fastest by a hair, but the only model that is
fast **and** keeps the project's core guarantees intact:
- **0.99 s** average query — meets the PRD `< 2 s` target.
- **100% GPU** (2.2 GB) — fits entirely in 6 GB VRAM; no CPU offload.
- **Grounded answers with citations intact** (3 citations/query) — preserves the
  explainability/evidence-verification feature that is central to this project.
- **3/3** benchmark questions correct.
- ~5× faster per-chunk extraction than the previous default (6.04 s vs 28.22 s).

### 🅰 Quality alternative — `gemma3:4b`
The nicest outputs: richest extraction (12 entities / 15 relationships with precise
types), best answer phrasing, most citations (5/query), grounded. But **~2× slower**
(1.87 s query — right at the PRD limit; 50.6 s ingest on the fixture). Keep it as an
opt-in "highest quality" model, not the default.

### ❌ Not recommended (as default) — `llama3.2:3b`
Fastest of all (0.95 s query, 29.6 s ingest) and 3/3 correct — **but it breaks
citations**. It ends answers with `USED CHUNKS:` (a space) instead of the exact
`USED_CHUNKS:` the footer parser requires, so every answer came back
`grounded=False` with **0 citations**. For a project whose differentiators are
grounding, citations, and evidence verification, silently losing citations is a hard
no, regardless of speed. (A future parser-leniency bugfix could recover it — tracked
as a follow-up, not done here.)

### 📌 Legacy / reference — `llama3.1:8b`
The previous default. Grounds correctly and extracts richly, but **overflows 6 GB
VRAM** (5.6 GB → 25%/75% CPU/GPU split), making it the slowest by far: 143 s ingest,
28.22 s/chunk, and **3.67 s query — fails the `< 2 s` target**. Kept only as the
performance baseline these measurements are compared against.

## What the switch fixes (and doesn't)

- **Query `< 2 s`: now MET** — `qwen2.5:3b` at 0.99 s vs `llama3.1`'s 3.67 s FAIL.
- **100-page ingest `< 10 s`: still not met by a model swap alone** — extraction is
  one LLM call per chunk (~6 s/chunk on the fast models), so a ~341-chunk 100-page
  document is still on the order of tens of minutes. Closing that target needs a
  separate change to reduce the number of extraction calls (a future ticket), or
  accepting it as the PRD's explicitly-soft target.

## Reproduce / revisit

Re-run any time (e.g. when a newer model appears) against the same fixture:

```bash
python benchmarks/benchmark_models.py qwen2.5:3b <new-model>
```

Tag `perf-baseline-v1.0` marks the measurements above as the v1.0 baseline.
