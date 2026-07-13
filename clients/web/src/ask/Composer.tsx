import { useEffect, useRef, useState } from "react";

/** The ask input. Enter sends, Shift+Enter breaks a line; while an answer is
 *  in flight the send key becomes a real Stop (aborts the request). A `seed`
 *  (e.g. arriving from Search) pre-fills the draft without auto-sending — the
 *  reader still chooses to ask. */
export function Composer({
  busy,
  seed,
  onAsk,
  onStop,
}: {
  busy: boolean;
  seed?: string;
  onAsk: (question: string) => void;
  onStop: () => void;
}) {
  const [draft, setDraft] = useState(seed ?? "");
  const areaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (seed) {
      setDraft(seed);
      const area = areaRef.current;
      if (area) area.focus();
    }
  }, [seed]);

  const submit = () => {
    const question = draft.trim();
    if (!question || busy) return;
    setDraft("");
    onAsk(question);
  };

  return (
    <div className="composer">
      <textarea
        ref={areaRef}
        value={draft}
        rows={1}
        placeholder="Ask anything about your documents…"
        aria-label="Ask anything about your documents"
        onChange={(event) => {
          setDraft(event.target.value);
          const area = areaRef.current;
          if (area) {
            area.style.height = "auto";
            area.style.height = `${Math.min(area.scrollHeight, 160)}px`;
          }
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
      />
      {busy ? (
        <button type="button" className="send stop" onClick={onStop} aria-label="Stop answering">
          ■
        </button>
      ) : (
        <button
          type="button"
          className="send"
          onClick={submit}
          disabled={!draft.trim()}
          aria-label="Send question"
        >
          ↑
        </button>
      )}
    </div>
  );
}
