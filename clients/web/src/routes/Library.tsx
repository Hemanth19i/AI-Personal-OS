import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, fetchDocuments, retryDocument, uploadDocument } from "../api/client";
import type { Document } from "../api/types";
import { UploadZone } from "../library/UploadZone";
import {
  BUCKET_COLOR,
  anyProcessing,
  bucketOf,
  fileName,
  statusLabel,
  type Bucket,
} from "../library/status";

type Filter = "all" | Bucket;
const FILTERS: Filter[] = ["all", "ready", "processing", "failed"];

/** Library — the index archetype: every document you have given the study,
 *  and its state. The status dots are the only saturated colour. While
 *  anything is processing the list quietly re-polls, so a dropped document
 *  is seen becoming ready. */
export function Library() {
  const [documents, setDocuments] = useState<Document[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const pollRef = useRef<number | undefined>(undefined);

  const load = useCallback(async () => {
    try {
      const docs = await fetchDocuments();
      setDocuments(docs);
      setError(null);
    } catch {
      setError("Can't reach the engine. Start it with python -m server.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Re-poll only while something is in flight; stop when the library settles.
  useEffect(() => {
    window.clearTimeout(pollRef.current);
    if (documents && anyProcessing(documents)) {
      pollRef.current = window.setTimeout(() => void load(), 2500);
    }
    return () => window.clearTimeout(pollRef.current);
  }, [documents, load]);

  const upload = async (files: File[]) => {
    if (files.length === 0) return;
    setUploading(true);
    setNotice(null);
    for (const file of files) {
      try {
        await uploadDocument(file);
      } catch (err) {
        setNotice(
          err instanceof ApiError && err.status === 409
            ? `${file.name} is already in your library.`
            : `Couldn't add ${file.name}. ${err instanceof ApiError ? err.detail : ""}`,
        );
      }
    }
    setUploading(false);
    await load();
  };

  const retry = async (id: number) => {
    try {
      await retryDocument(id);
    } finally {
      await load();
    }
  };

  const shown = (documents ?? []).filter(
    (d) => filter === "all" || bucketOf(d.status) === filter,
  );

  return (
    <div className="pillar-page">
      <div className="index-head">
        <h1 className="voice">Library</h1>
        <span className="index-count">
          {documents ? `${documents.length} documents` : ""}
        </span>
        <div className="seg" role="tablist" aria-label="Filter documents">
          {FILTERS.map((option) => (
            <button
              key={option}
              type="button"
              role="tab"
              aria-selected={filter === option}
              className={filter === option ? "on" : undefined}
              onClick={() => setFilter(option)}
            >
              {option[0].toUpperCase() + option.slice(1)}
            </button>
          ))}
        </div>
      </div>

      <UploadZone onFiles={upload} busy={uploading} />
      {notice && <div className="index-notice">{notice}</div>}
      {error && <div className="index-notice">{error}</div>}

      {documents !== null && documents.length === 0 && !error && (
        <p className="index-empty voice">
          Your library is empty. Drop a document above to begin.
        </p>
      )}

      <ul className="doc-list">
        {shown.map((document) => {
          const bucket = bucketOf(document.status);
          return (
            <li className="doc-row" key={document.id}>
              <span className="dot" style={{ background: BUCKET_COLOR[bucket] }} />
              <span className="doc-name">{fileName(document.path)}</span>
              <span className={`doc-status bucket-${bucket}`}>
                {statusLabel(document.status)}
              </span>
              {bucket === "failed" && (
                <button
                  type="button"
                  className="doc-retry"
                  onClick={() => void retry(document.id)}
                >
                  Retry
                </button>
              )}
            </li>
          );
        })}
      </ul>

      {documents && documents.length > 0 && (
        <div className="legend" aria-hidden="true">
          <span><span className="dot" style={{ background: "var(--ready)" }} /> ready</span>
          <span><span className="dot" style={{ background: "var(--proc)" }} /> processing</span>
          <span><span className="dot" style={{ background: "var(--pend)" }} /> waiting</span>
          <span><span className="dot" style={{ background: "var(--fail)" }} /> failed</span>
        </div>
      )}
    </div>
  );
}
