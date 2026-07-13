import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { postAsk } from "../api/client";
import { AnswerBlock, type Exchange } from "../ask/AnswerBlock";
import { Composer } from "../ask/Composer";

/** The heart of AI Personal OS: the annotated page.
 *  A session-local thread (conversation persistence is a future engine
 *  capability); each exchange renders as question → revealing answer →
 *  evidence margin. Auto-scroll follows the answer but yields the moment
 *  the reader scrolls up. */
export function Ask() {
  const [thread, setThread] = useState<Exchange[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const deskRef = useRef<HTMLDivElement>(null);
  const busy = thread.some((exchange) => exchange.kind === "asking");

  // "Ask about this" from Search arrives as router state, pre-filling the
  // composer (never auto-sending — the reader chooses).
  const location = useLocation();
  const seed = (location.state as { seed?: string } | null)?.seed;

  // Follow the growing answer only while the reader is already near the foot.
  useEffect(() => {
    const desk = deskRef.current;
    if (!desk) return;
    const nearBottom =
      desk.scrollHeight - desk.scrollTop - desk.clientHeight < 120;
    if (nearBottom) desk.scrollTop = desk.scrollHeight;
  });

  const ask = async (question: string) => {
    const controller = new AbortController();
    abortRef.current = controller;
    setThread((current) => [...current, { kind: "asking", question }]);
    try {
      const result = await postAsk(question, controller.signal);
      setThread((current) =>
        current.map((exchange) =>
          exchange.kind === "asking" && exchange.question === question
            ? { kind: "answered", question, result }
            : exchange,
        ),
      );
    } catch (error) {
      const aborted = controller.signal.aborted;
      setThread((current) =>
        current.map((exchange) =>
          exchange.kind === "asking" && exchange.question === question
            ? {
                kind: "failed",
                question,
                message: aborted
                  ? "Stopped."
                  : "The engine couldn't answer. Check that it's running (python -m server) and try again.",
              }
            : exchange,
        ),
      );
      if (!aborted) console.error(error);
    } finally {
      abortRef.current = null;
    }
  };

  return (
    <div className="ask-desk">
      <div className="ask-scroll" ref={deskRef}>
        <div className="sheet">
          {thread.length === 0 && (
            <div className="pillar-empty">
              <h1>Welcome back.</h1>
              <p>Ask anything about your documents.</p>
            </div>
          )}
          {thread.map((exchange, index) => (
            <AnswerBlock key={index} exchange={exchange} />
          ))}
        </div>
      </div>
      <Composer
        busy={busy}
        seed={seed}
        onAsk={ask}
        onStop={() => abortRef.current?.abort()}
      />
    </div>
  );
}
