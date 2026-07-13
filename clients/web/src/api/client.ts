/** Typed client for the Core API (ADR-017) — loopback only.
 *  The contract is the boundary; this module is the only place the web
 *  client knows a URL exists. */

import type {
  AnswerResponse,
  Document,
  HealthResponse,
  SearchHit,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8765";

/** An API error that carries the HTTP status and the engine's detail. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
  }
}

async function readError(response: Response): Promise<never> {
  let detail = `${response.status}`;
  try {
    const body = await response.json();
    if (body && typeof body.detail === "string") detail = body.detail;
  } catch {
    /* non-JSON error body — keep the status */
  }
  throw new ApiError(response.status, detail);
}

async function getSignal<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, { signal });
  if (!response.ok) return readError(response);
  return (await response.json()) as T;
}

function get<T>(path: string): Promise<T> {
  return getSignal<T>(path);
}

export function fetchHealth(): Promise<HealthResponse> {
  return get<HealthResponse>("/health");
}

/** Ask the engine. Abortable so the composer's Stop is real. */
export async function postAsk(
  question: string,
  signal?: AbortSignal,
): Promise<AnswerResponse> {
  const response = await fetch(`${BASE_URL}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
    signal,
  });
  if (!response.ok) return readError(response);
  return (await response.json()) as AnswerResponse;
}

export function fetchDocuments(): Promise<Document[]> {
  return get<Document[]>("/documents");
}

export async function retryDocument(id: number): Promise<Document> {
  const response = await fetch(`${BASE_URL}/documents/${id}/retry`, {
    method: "POST",
  });
  if (!response.ok) return readError(response);
  return (await response.json()) as Document;
}

export function searchDocuments(
  query: string,
  signal?: AbortSignal,
): Promise<SearchHit[]> {
  const params = new URLSearchParams({ q: query, k: "20" });
  return getSignal<SearchHit[]>(`/search?${params}`, signal);
}

/** Upload a document; the engine registers it and begins processing (202). */
export async function uploadDocument(file: File): Promise<Document> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch(`${BASE_URL}/documents`, { method: "POST", body });
  if (!response.ok) return readError(response);
  return (await response.json()) as Document;
}
