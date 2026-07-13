import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { searchDocuments } from "../api/client";
import type { SearchHit } from "../api/types";
import { fileName } from "../library/status";
import { highlight } from "../search/highlight";

type State =
  | { kind: "idle" }
  | { kind: "searching" }
  | { kind: "results"; hits: SearchHit[] }
  | { kind: "error" };

const DEBOUNCE_MS = 220;

/** Search — find a line you half-remember, across your library. Results are
 *  quotations: the matched passage is the anchor, its source named quietly
 *  above. Filter by document; open Ask with the query as context. */
export function Search() {
  const [query, setQuery] = useState("");
  const [state, setState] = useState<State>({ kind: "idle" });
  const [sourceFilter, setSourceFilter] = useState<string>("all");
  const abortRef = useRef<AbortController | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const trimmed = query.trim();
    abortRef.current?.abort();
    if (trimmed.length < 2) {
      setState({ kind: "idle" });
      return;
    }
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ kind: "searching" });
    const timer = window.setTimeout(async () => {
      try {
        const hits = await searchDocuments(trimmed, controller.signal);
        setState({ kind: "results", hits });
        setSourceFilter("all");
      } catch (error) {
        if (!controller.signal.aborted) setState({ kind: "error" });
      }
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [query]);

  const hits = state.kind === "results" ? state.hits : [];
  const sources = Array.from(new Set(hits.map((hit) => hit.file)));
  const shown =
    sourceFilter === "all" ? hits : hits.filter((hit) => hit.file === sourceFilter);

  return (
    <div className="pillar-page search-page">
      <div className="search-field">
        <svg viewBox="0 0 24 24" aria-hidden="true" className="search-icon">
          <circle cx="10.5" cy="10.5" r="6.5" />
          <line x1="15.5" y1="15.5" x2="20.5" y2="20.5" strokeLinecap="round" />
        </svg>
        <input
          type="search"
          value={query}
          autoFocus
          placeholder="Search your documents by meaning…"
          aria-label="Search your documents"
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      {state.kind === "results" && sources.length > 1 && (
        <div className="search-filter" role="tablist" aria-label="Filter by document">
          <button
            type="button"
            role="tab"
            aria-selected={sourceFilter === "all"}
            className={sourceFilter === "all" ? "on" : undefined}
            onClick={() => setSourceFilter("all")}
          >
            All documents
          </button>
          {sources.map((source) => (
            <button
              key={source}
              type="button"
              role="tab"
              aria-selected={sourceFilter === source}
              className={sourceFilter === source ? "on" : undefined}
              onClick={() => setSourceFilter(source)}
            >
              {fileName(source)}
            </button>
          ))}
        </div>
      )}

      {state.kind === "idle" && (
        <p className="search-hint voice">
          Find a line you half-remember — search runs on meaning, not just words.
        </p>
      )}
      {state.kind === "searching" && <p className="search-hint">Searching…</p>}
      {state.kind === "error" && (
        <p className="search-hint">
          Can't reach the engine. Start it with python -m server.
        </p>
      )}
      {state.kind === "results" && shown.length === 0 && (
        <p className="search-hint voice">
          Nothing matched. Try fewer or different words.
        </p>
      )}

      {state.kind === "results" && shown.length > 0 && (
        <div className="search-summary">
          {shown.length} {shown.length === 1 ? "passage" : "passages"}
          {sourceFilter === "all" && sources.length > 0
            ? ` from ${sources.length} of your documents`
            : ""}
        </div>
      )}

      <ul className="search-results">
        {shown.map((hit) => (
          <li className="result" key={hit.chunk_id}>
            <div className="result-src">{fileName(hit.file)}</div>
            <p className="result-quote voice">{highlight(hit.text.trim(), query)}</p>
            <div className="result-actions">
              <button
                type="button"
                className="result-ask"
                onClick={() => navigate("/", { state: { seed: query } })}
              >
                Ask about this ↗
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
