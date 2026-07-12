import { useEffect, useState } from "react";
import { fetchHealth } from "../api/client";
import type { HealthResponse } from "../api/types";

type EngineState =
  | { kind: "checking" }
  | { kind: "ok"; health: HealthResponse }
  | { kind: "unreachable" };

/** Top chrome. The Offline chip is a *fact*, not a control (Design Candidate):
 *  a steady green dot when the local engine answers /health; a quiet notice —
 *  never an alarm — when it doesn't. This is W2's proof: React → Core API. */
export function TopBar() {
  const [engine, setEngine] = useState<EngineState>({ kind: "checking" });

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const check = async () => {
      try {
        const health = await fetchHealth();
        if (!cancelled) setEngine({ kind: "ok", health });
      } catch {
        if (!cancelled) {
          setEngine({ kind: "unreachable" });
          timer = window.setTimeout(check, 10_000); // quiet retry
        }
      }
    };
    void check();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, []);

  return (
    <header className="topbar">
      <span className="title">The Study</span>
      <span className="spacer" />
      {engine.kind === "ok" && (
        <>
          <span className="chip fact" title="Everything runs on this device">
            <span className="dot" style={{ background: "var(--ready)" }} />
            Offline
          </span>
          <span
            className="chip"
            title={`Engine v${engine.health.version} · ${engine.health.llm_model}`}
          >
            {engine.health.llm_model}
          </span>
        </>
      )}
      {engine.kind === "checking" && (
        <span className="chip fact">
          <span className="dot" style={{ background: "var(--pend)" }} />
          Checking engine…
        </span>
      )}
      {engine.kind === "unreachable" && (
        <span
          className="chip"
          title="Start the Core API: python -m server"
        >
          <span className="dot" style={{ background: "var(--pend)" }} />
          Engine not running
        </span>
      )}
    </header>
  );
}
