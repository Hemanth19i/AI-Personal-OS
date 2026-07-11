# Model benchmark — `llama3.2:3b`

_Fixture: `fixtures/fictional_company.pdf` · embeddings: nomic-embed-text · same pipeline, LLM swapped._

## Status
- ingest status: **ready**, chunks: 5, extraction errors: 0

## Hardware / fit (while model resident)
- `ollama ps`: `llama3.2:3b a80c4f17acd5 2.6 GB 100% GPU 4096 4 minutes from now`
- GPU memory used (total): 3950 MiB
- Ollama server RSS: 72 MB
- Benchmark app-process peak WS: 128 MB

## Ingest
- total: **29.63s**  (PRD target for 100 pages: <10s)
- extraction: 29.41s over 5 calls = **5.88s/chunk**
- embedding: 0.17s = 0.034s/chunk
- graph edges persisted: 36

## Query  (avg total 0.95s · correctness 3/3)
| # | strategy | total | llm_gen | grounded | cites | correct |
|---|---|---|---|---|---|---|
| 1 | semantic | 0.93s | 0.86s | False | 0 | ✅ |
| 2 | semantic | 1.00s | 0.96s | False | 0 | ✅ |
| 3 | semantic | 0.92s | 0.88s | False | 0 | ✅ |

## Sample extraction (chunk 0)
```
entities (9): Dr. Elena Vasquez[person], Marcus Chen[person], Priya Nair[person], Aurora Lab[concept], Kestrel Institute[concept], Meridian Project[concept], Lumen[concept], GraphCore[concept], VectorStore[concept]
relationships (11):
  Dr. Elena Vasquez --collaborates--> Aurora Lab
  Kestrel Institute --locates--> Aurora Lab
  Elena Vasquez --leads--> Marcus Chen
  Meridian Project --builds--> Lumen
  Priya Nair --writes--> GraphCore
  Marcus Chen --maintains--> VectorStore
  Kestrel Institute --collaborates--> Beacon
  James Okafor --worked_with--> Elena Vasquez
  Aurora Lab --uses--> Lumen
  Priya Nair --reports_to--> Aurora Lab
  Priya Nair --joins--> Kestrel Institute
```

## Sample answers (judge quality here)
**Q1: Who designed the knowledge graph module?**  
_0.93s · grounded=False · correct=✅_

> Priya Nair.

USED CHUNKS:
3,5

**Q2: What does the VectorStore module depend on?**  
_1.00s · grounded=False · correct=✅_

> The Kestrel embedding model.

USED CHUNKS:
5

**Q3: Who directs the Aurora Lab?**  
_0.92s · grounded=False · correct=✅_

> James Okafor.

USED CHUNKS:
1,3
