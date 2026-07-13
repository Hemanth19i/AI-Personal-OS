/** Core API contract types (mirrors server/schemas.py — the local contract).
 *  W2 carries only what the shell needs; each later milestone adds its own. */

export interface HealthResponse {
  status: string;
  version: string;
  embedding_model: string;
  llm_model: string;
  database_bytes: number;
  vector_store_bytes: number;
  offline: boolean;
}

export interface Source {
  chunk_id: number;
  file: string;
  snippet: string;
}

export interface Evidence {
  verified: boolean;
  reason: string;
  verified_citations: number;
  total_citations: number;
}

export interface Explanation {
  timestamp: string;
  strategy: string;
  reason: string;
  retrieved_count: number;
  graph_expanded: boolean;
  graph_relation_count: number;
  reranked_count: number;
  llm_consulted: boolean;
  grounded: boolean;
  citation_count: number;
  confidence: string;
  evidence: Evidence;
}

export interface AnswerResponse {
  answer: string;
  sources: Source[];
  grounded: boolean;
  explanation: Explanation;
}

export interface Document {
  id: number;
  workspace_id: string;
  path: string;
  hash: string;
  status: string;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface SearchHit {
  chunk_id: number;
  text: string;
  score: number;
  file: string;
}
