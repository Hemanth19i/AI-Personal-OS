# Model benchmark — `llama3.1`

_Fixture: `fixtures/fictional_company.pdf` · embeddings: nomic-embed-text · same pipeline, LLM swapped._

## Status
- ingest status: **ready**, chunks: 5, extraction errors: 0

## Hardware / fit (while model resident)
- `ollama ps`: `llama3.1:latest 46e0c10c039e 5.6 GB 25%/75% CPU/GPU 4096 4 minutes from now`
- GPU memory used (total): 5550 MiB
- Ollama server RSS: 70 MB
- Benchmark app-process peak WS: 127 MB

## Ingest
- total: **143.18s**  (PRD target for 100 pages: <10s)
- extraction: 141.11s over 5 calls = **28.22s/chunk**
- embedding: 1.54s = 0.307s/chunk
- graph edges persisted: 38

## Query  (avg total 3.67s · correctness 3/3)
| # | strategy | total | llm_gen | grounded | cites | correct |
|---|---|---|---|---|---|---|
| 1 | semantic | 3.16s | 2.91s | True | 1 | ✅ |
| 2 | semantic | 3.07s | 2.99s | True | 3 | ✅ |
| 3 | semantic | 4.77s | 2.18s | True | 2 | ✅ |

## Sample extraction (chunk 0)
```
entities (13): Dr. Elena Vasquez[person], The Meridian Project[concept], Kestrel Institute[concept], Elena Vasquez[person], Marcus Chen[person], Priya Nair[person], Lumen[concept], GraphCore[concept], Aurora Lab[concept], James Okafor[person], Beacon[concept], VectorStore[concept], Kestrel embedding model[concept]
relationships (12):
  Dr. Elena Vasquez --founded_by--> The Meridian Project
  Elena Vasquez --builds--> Lumen
  Priya Nair --designed--> GraphCore
  Marcus Chen --maintains--> VectorStore
  Priya Nair --uses--> GraphCore
  The Meridian Project --builds--> Lumen
  Kestrel Institute --collaborates_with--> Aurora Lab
  James Okafor --directed_by--> Aurora Lab
  Elena Vasquez --worked_on_project--> Beacon
  Priya Nair --reports_to--> Dr. Elena Vasquez
  Marcus Chen --joined--> Kestrel Institute
  Priya Nair --joined--> Kestrel Institute
```

## Sample answers (judge quality here)
**Q1: Who designed the knowledge graph module?**  
_3.16s · grounded=True · correct=✅_

> Priya Nair.

USED_CHUNKS:
1,2
OR

**Q2: What does the VectorStore module depend on?**  
_3.07s · grounded=True · correct=✅_

> The VectorStore module depends on the Kestrel embedding model.

**Q3: Who directs the Aurora Lab?**  
_4.77s · grounded=True · correct=✅_

> James Okafor.
