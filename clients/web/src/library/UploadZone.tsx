import { useRef, useState } from "react";

/** Drop-to-add — the study's front door. A drag anywhere over the Library
 *  raises a calm full-panel invitation; a click opens the file picker. */
export function UploadZone({
  onFiles,
  busy,
}: {
  onFiles: (files: File[]) => void;
  busy: boolean;
}) {
  const [over, setOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div
      className={over ? "dropzone over" : "dropzone"}
      onDragOver={(event) => {
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setOver(false);
        onFiles(Array.from(event.dataTransfer.files));
      }}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".pdf,.txt,.md"
        hidden
        onChange={(event) => {
          onFiles(Array.from(event.target.files ?? []));
          event.target.value = "";
        }}
      />
      <button
        type="button"
        className="dropzone-cta"
        onClick={() => inputRef.current?.click()}
        disabled={busy}
      >
        <span className="voice">Drop a document to add it</span>
        <span className="dropzone-sub">PDF — or click to choose</span>
      </button>
    </div>
  );
}
