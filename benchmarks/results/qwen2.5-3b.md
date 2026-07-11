# Model benchmark — `qwen2.5:3b`

_Fixture: `fixtures/fictional_company.pdf` · embeddings: nomic-embed-text · same pipeline, LLM swapped._

## Status
- ingest status: **ready**, chunks: 5, extraction errors: 0

## Hardware / fit (while model resident)
- `ollama ps`: `qwen2.5:3b 357c53fb659c 2.2 GB 100% GPU 4096 4 minutes from now`
- GPU memory used (total): 5832 MiB
- Ollama server RSS: 63 MB
- Benchmark app-process peak WS: 129 MB

## Ingest
- total: **30.39s**  (PRD target for 100 pages: <10s)
- extraction: 30.19s over 5 calls = **6.04s/chunk**
- embedding: 0.16s = 0.031s/chunk
- graph edges persisted: 34

## Query  (avg total 0.99s · correctness 3/3)
| # | strategy | total | llm_gen | grounded | cites | correct |
|---|---|---|---|---|---|---|
| 1 | semantic | 0.96s | 0.89s | True | 3 | ✅ |
| 2 | semantic | 1.03s | 0.99s | True | 3 | ✅ |
| 3 | semantic | 0.99s | 0.95s | True | 3 | ✅ |

## Sample extraction (chunk 0)
```
entities (8): Dr. Elena Vasquez[person], Marcus Chen[person], Priya Nair[person], Elena Vasquez[person], Kestrel Institute[concept], Aurora Lab[concept], Portland[location], James Okafor[person]
relationships (13):
  Dr. Elena Vasquez --is_same_as--> Elena Vasquez
  Kestrel Institute --located_in--> Portland
  James Okafor --collaborates_with--> Aurora Lab
  Elena Vasquez --worked_on--> Beacon
  Priya Nair --inspired_by--> GraphCore
  Dr. Elena Vasquez --reports_to--> Priya Nair
  Dr. Elena Vasquez --leads_research_team--> Marcus Chen
  Elena Vasquez --builds--> Lumen
  Marcus Chen --maintains--> VectorStore module
  Priya Nair --designed--> Knowledge graph module
  Kestrel Institute --collaborates_with--> Aurora Lab
  Elena Vasquez --inspired_by--> GraphCore
```

## Sample answers (judge quality here)
**Q1: Who designed the knowledge graph module?**  
_0.96s · grounded=True · correct=✅_

> Priya Nair

**Q2: What does the VectorStore module depend on?**  
_1.03s · grounded=True · correct=✅_

> The VectorStore module depends on the Kestrel embedding model.

**Q3: Who directs the Aurora Lab?**  
_0.99s · grounded=True · correct=✅_

> James Okafor directs the Aurora Lab.
