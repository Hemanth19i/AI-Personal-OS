import type { ReactNode } from "react";

/** Wrap each query term in the passage with a brass-tinted mark — the matched
 *  words are what the eye should land on. Case-insensitive. */
export function highlight(text: string, query: string): ReactNode {
  const terms = query
    .toLowerCase()
    .split(/\s+/)
    .filter((term) => term.length >= 2);
  if (terms.length === 0) return text;

  const termSet = new Set(terms);
  const escaped = terms.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const parts = text.split(new RegExp(`(${escaped.join("|")})`, "gi"));

  return parts.map((part, index) =>
    termSet.has(part.toLowerCase()) ? (
      <mark key={index}>{part}</mark>
    ) : (
      <span key={index}>{part}</span>
    ),
  );
}
