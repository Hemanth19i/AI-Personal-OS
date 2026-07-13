/** The file-lifecycle state machine, mapped to The Study's four status buckets.
 *  Status is a dot + a plain word — never colour alone, never a banner. */

import type { Document } from "../api/types";

export type Bucket = "ready" | "processing" | "pending" | "failed";

const PROCESSING = new Set([
  "parsing",
  "ocr",
  "chunking",
  "embedding",
  "extracting",
  "verifying",
]);

export function bucketOf(status: string): Bucket {
  if (status === "ready") return "ready";
  if (status === "failed") return "failed";
  if (status === "pending") return "pending";
  if (PROCESSING.has(status)) return "processing";
  return "pending";
}

export const BUCKET_COLOR: Record<Bucket, string> = {
  ready: "var(--ready)",
  processing: "var(--proc)",
  pending: "var(--pend)",
  failed: "var(--fail)",
};

/** A human label for a raw status ("embedding" → "Understanding…"). */
export function statusLabel(status: string): string {
  switch (status) {
    case "ready":
      return "Ready";
    case "failed":
      return "Failed";
    case "pending":
      return "Waiting";
    case "parsing":
      return "Reading…";
    case "ocr":
      return "Reading (OCR)…";
    case "chunking":
      return "Chunking…";
    case "embedding":
      return "Understanding…";
    case "extracting":
      return "Extracting…";
    case "verifying":
      return "Verifying…";
    default:
      return status;
  }
}

export function fileName(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

export function anyProcessing(documents: Document[]): boolean {
  return documents.some(
    (d) => bucketOf(d.status) === "processing" || bucketOf(d.status) === "pending",
  );
}
