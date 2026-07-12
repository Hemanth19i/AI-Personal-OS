/** Typed client for the Core API (ADR-017) — loopback only.
 *  The contract is the boundary; this module is the only place the web
 *  client knows a URL exists. */

import type { HealthResponse } from "./types";

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8765";

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`);
  if (!response.ok) {
    throw new Error(`${path} failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export function fetchHealth(): Promise<HealthResponse> {
  return get<HealthResponse>("/health");
}
