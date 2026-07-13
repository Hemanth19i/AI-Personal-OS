import { useEffect, useRef, useState } from "react";
import type { AnswerResponse } from "../api/types";
import { EvidenceMargin } from "./EvidenceMargin";

/** One exchange on the page: the question (brass tick), the answer in the
 *  reading voice, and — after the answer has fully landed — its margin.
 *
 *  The reveal is honest: the engine returns the complete answer (~1s); we
 *  render the *real* text progressively under the caret for the designed
 *  reading experience, and the evidence appears only after the last word
 *  (evidence-after-answer). True token streaming is a future engine ticket.
 */

export type Exchange =
  | { kind: "asking"; question: string }
  | { kind: "answered"; question: string; result: AnswerResponse }
  | { kind: "failed"; question: string; message: string };

const REVEAL_CHARS_PER_TICK = 3;
const REVEAL_TICK_MS = 14;

function useReveal(text: string): { visible: string; done: boolean } {
  const [count, setCount] = useState(0);
  const reduced = useRef(
    window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );

  useEffect(() => {
    setCount(reduced.current ? text.length : 0);
    if (reduced.current) return;
    const timer = window.setInterval(() => {
      setCount((current) => {
        if (current >= text.length) {
          window.clearInterval(timer);
          return current;
        }
        return Math.min(current + REVEAL_CHARS_PER_TICK, text.length);
      });
    }, REVEAL_TICK_MS);
    return () => window.clearInterval(timer);
  }, [text]);

  return { visible: text.slice(0, count), done: count >= text.length };
}

function RevealedAnswer({ result }: { result: AnswerResponse }) {
  const { visible, done } = useReveal(result.answer);
  return (
    <div className="page">
      <div
        className={result.grounded ? "answer-text" : "answer-text ungrounded"}
        aria-live="polite"
      >
        {visible.split(/\n{2,}/).map((paragraph, index) => (
          <p key={index}>{paragraph}</p>
        ))}
        {!done && <span className="caret" aria-hidden="true" />}
      </div>
      {done && <EvidenceMargin result={result} />}
    </div>
  );
}

export function AnswerBlock({ exchange }: { exchange: Exchange }) {
  return (
    <article className="exchange">
      <div className="ask-q">{exchange.question}</div>
      {exchange.kind === "asking" && (
        <div className="thinking" aria-label="Answering">
          <span /><span /><span />
        </div>
      )}
      {exchange.kind === "answered" && <RevealedAnswer result={exchange.result} />}
      {exchange.kind === "failed" && (
        <div className="ask-error">
          <p>{exchange.message}</p>
        </div>
      )}
    </article>
  );
}
