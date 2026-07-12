import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Newsreader is self-hosted (bundled at build time) — a runtime font CDN
// fetch would violate offline-first (ADR-001).
import "@fontsource/newsreader/400.css";
import "@fontsource/newsreader/500.css";
import "@fontsource/newsreader/600.css";
import "@fontsource/newsreader/400-italic.css";
import "./theme/study.css";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
