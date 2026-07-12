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
