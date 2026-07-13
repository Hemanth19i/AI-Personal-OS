import type { AnswerResponse } from "../api/types";

/** The signature: evidence in the margin, pinned to the brass rule.
 *  Notes are the answer's real sources (number · file · quote); the foot
 *  carries the Explanation's observable facts — confidence, verification,
 *  strategy. Always visible once the answer lands; never a popup. */

const CONFIDENCE_DOT: Record<string, string> = {
  high: "var(--ready)",
  medium: "var(--proc)",
  low: "var(--pend)",
  none: "var(--pend)",
};

function fileName(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

export function EvidenceMargin({ result }: { result: AnswerResponse }) {
  const { sources, explanation } = result;
  const confidence = explanation.confidence.toLowerCase();

  return (
    <aside className="margin" aria-label="Evidence for this answer">
      {sources.length === 0 && (
        <div className="mnote">
          <span className="mnum">—</span>
          <span className="mquote">No citations — nothing in your documents supported an answer.</span>
        </div>
      )}
      {sources.map((source, index) => (
        <div className="mnote" key={source.chunk_id}>
          <span className="mnum">{index + 1} —</span>
          <span className="mref">{fileName(source.file)}</span>
          <span className="mquote">“{source.snippet}”</span>
        </div>
      ))}
      <div className="mfoot">
        <div className="mline">
          <span
            className="dot"
            style={{ background: CONFIDENCE_DOT[confidence] ?? "var(--pend)" }}
          />
          {confidence === "none"
            ? "No confidence — nothing to answer from"
            : `${confidence[0].toUpperCase()}${confidence.slice(1)} confidence`}
        </div>
        {explanation.evidence.total_citations > 0 && (
          <div className="mline verified">
            ✓ {explanation.evidence.verified_citations} /{" "}
            {explanation.evidence.total_citations} citations verified
          </div>
        )}
        <div className="mline muted">
          {explanation.strategy === "graph" ? "Graph path" : "Semantic"} ·{" "}
          {explanation.retrieved_count} chunks
          {explanation.graph_expanded
            ? ` · ${explanation.graph_relation_count} edges`
            : ""}
        </div>
      </div>
    </aside>
  );
}
