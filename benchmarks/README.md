# Benchmarks — AI Personal OS

Reproducible performance + model-evaluation harness (roadmap **M7.1 — Model
Evaluation & Performance Benchmark**). This is measurement tooling, not part of
the application: it only calls the public API, so it touches none of the
[Architecture Freeze v1.0](../docs/ARCHITECTURE.md) boundaries. The app code is
never modified to run a benchmark.

## Why this exists

The T7.1 benchmark showed the pipeline's only slow part is **LLM inference** —
parsing, chunking, storage, retrieval, graph expansion, and reranking are all
sub-millisecond-to-low-second. The dominant cost is entity extraction (one LLM
call per chunk) and answer generation. On the reference machine, `llama3.1:8b`
overflowed 6 GB of VRAM and ran partly on CPU (~45s/chunk). So the highest-value
lever is **which local model** we run, not the architecture. This harness makes
that choice evidence-based and repeatable.

## Layout

```
benchmarks/
├── benchmark_models.py     # the harness
├── fixtures/
│   └── fictional_company.pdf   # the fixed corpus (regenerable)
├── results/                # generated: one .md per model + comparison.md
└── README.md
```

## The fixture

`fictional_company.pdf` is a **fictional** company/knowledge-system story. The
entities and relationships are invented, so a model cannot answer from
pretraining — it must use the retrieved context. That makes this a fair test of
*retrieval + reasoning*, not memorised facts. Three questions have known
ground-truth answers, giving an objective correctness check (`Priya Nair` /
`Kestrel embedding model` / `James Okafor`) alongside the human-judged samples.

Regenerate it from the corpus text in `benchmark_models.py`:

```bash
python benchmarks/benchmark_models.py --regen-fixture
```

## Running

From the repo root, with the project venv and a running Ollama daemon that has
the models pulled:

```bash
python benchmarks/benchmark_models.py llama3.2:3b qwen2.5:3b gemma3:4b
```

Each model writes `results/<model>.md` (hardware/fit, ingest, query, correctness,
sample extraction, sample answers) and a combined `results/comparison.md`.

## What is and isn't scored

- **Measured objectively:** ingest time, extraction time/chunk, embedding
  time/chunk, per-query retrieval/LLM/total latency, GPU/CPU split (`ollama ps`),
  GPU memory, Ollama-server RSS, entities/relationships extracted, answer
  correctness vs. ground truth, grounding + citation counts.
- **NOT scored automatically:** extraction *quality* and answer *quality*. There
  is no honest offline quality score, so each model's real extraction and answer
  text is captured verbatim in its results file for a human to judge. The final
  model choice combines the objective metrics with that human read.

The default model for the app lives in [`config.toml`](../config.toml)
(`[models] llm`); changing it is the entire "fix" this ticket exists to inform.
