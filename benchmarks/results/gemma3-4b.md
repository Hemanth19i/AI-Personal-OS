# Model benchmark — `gemma3:4b`

_Fixture: `fixtures/fictional_company.pdf` · embeddings: nomic-embed-text · same pipeline, LLM swapped._

## Status
- ingest status: **ready**, chunks: 5, extraction errors: 0

## Hardware / fit (while model resident)
- `ollama ps`: `gemma3:4b a2af6cc3eb7f 2.9 GB 100% GPU 4096 4 minutes from now`
- GPU memory used (total): 4900 MiB
- Ollama server RSS: 85 MB
- Benchmark app-process peak WS: 130 MB

## Ingest
- total: **50.62s**  (PRD target for 100 pages: <10s)
- extraction: 49.18s over 5 calls = **9.84s/chunk**
- embedding: 1.39s = 0.279s/chunk
- graph edges persisted: 37

## Query  (avg total 1.87s · correctness 3/3)
| # | strategy | total | llm_gen | grounded | cites | correct |
|---|---|---|---|---|---|---|
| 1 | semantic | 1.74s | 1.64s | True | 5 | ✅ |
| 2 | semantic | 1.92s | 1.86s | True | 5 | ✅ |
| 3 | semantic | 1.93s | 1.87s | True | 5 | ✅ |

## Sample extraction (chunk 0)
```
entities (12): Dr. Elena Vasquez[person], Kestrel Institute[organization], Marcus Chen[person], Priya Nair[person], Meridian Project[project], Lumen[system], GraphCore[component], VectorStore[module], Kestrel embedding model[model], Aurora Lab[organization], James Okafor[person], Beacon[project]
relationships (15):
  Dr. Elena Vasquez --founded--> Meridian Project
  Dr. Elena Vasquez --leads--> Marcus Chen
  Marcus Chen --maintains--> VectorStore
  Priya Nair --designed--> GraphCore
  Priya Nair --uses--> Lumen
  Marcus Chen --depends_on--> Kestrel embedding model
  Kestrel Institute --collaborates_with--> Aurora Lab
  James Okafor --directs--> Aurora Lab
  Dr. Elena Vasquez --worked_with--> Marcus Chen
  Dr. Elena Vasquez --studied--> Beacon
  GraphCore --inspired_by--> Beacon
  Lumen --stores--> VectorStore
```

## Sample answers (judge quality here)
**Q1: Who designed the knowledge graph module?**  
_1.74s · grounded=True · correct=✅_

> Priya Nair designed the knowledge graph module.

**Q2: What does the VectorStore module depend on?**  
_1.92s · grounded=True · correct=✅_

> The VectorStore module depends on the Kestrel embedding model.

**Q3: Who directs the Aurora Lab?**  
_1.93s · grounded=True · correct=✅_

> James Okafor directs the Aurora Lab.
