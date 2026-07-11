# Model comparison — AI Personal OS (M7.1)

_Same pipeline, same fixture (`fixtures/fictional_company.pdf`), same 3 questions.
Only the LLM changed. Embeddings: nomic-embed-text throughout._

**Machine:** RTX 3060 Laptop (6 GB, driver 610.47) · Ryzen 9 5900HX (8c/16t) · 15.4 GB RAM · Ollama 0.31.1 · 2026-07-11.

PRD targets: 100-page ingest <10s, query <2s. (This fixture is ~5 chunks, not 100
pages — use per-chunk extraction time to project the 100-page number; see the
T7.1 report for the arithmetic.)

| Model | status | ingest | extract/chunk | query avg | correct | edges | processor |
|---|---|---|---|---|---|---|---|
| `llama3.1` (baseline) | ready | 143.2s | 28.22s | 3.67s | 3/3 | 38 | `25%/75% CPU/GPU` |
| `llama3.2:3b` | ready | 29.6s | 5.88s | 0.95s | 3/3 | 36 | `100% GPU` |
| `qwen2.5:3b` | ready | 30.4s | 6.04s | 0.99s | 3/3 | 34 | `100% GPU` |
| `gemma3:4b` | ready | 50.6s | 9.84s | 1.87s | 3/3 | 37 | `100% GPU` |

Grounding / citations (measured — see per-model files):

| Model | grounded | citations | note |
|---|---|---|---|
| `llama3.1` | ✅ | 1–3 | follows `USED_CHUNKS:` footer |
| `llama3.2:3b` | ❌ | 0 | emits `USED CHUNKS:` (space) → footer parser misses it; correct answers, **broken citations** |
| `qwen2.5:3b` | ✅ | 3 | follows footer; citations intact |
| `gemma3:4b` | ✅ | 5 | follows footer; most citations |

Objective winners (measured):
- **Fastest ingest / query:** `llama3.2:3b` (29.6s / 0.95s) — but see the citation defect.
- **Most citations / richest extraction:** `gemma3:4b` (5 cites, 12 entities / 15 relationships).
- **Best speed + grounding together:** `qwen2.5:3b` (0.99s, grounded, 3 cites).
- **All four:** 3/3 answers correct.

Quality (extraction depth, answer phrasing) is judged from the per-model sample
sections — see each `results/<model>.md`. This file is objective metrics only;
the recommendation and rationale are in `winner.md`.
