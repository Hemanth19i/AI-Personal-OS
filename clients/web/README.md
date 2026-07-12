# AI Personal OS — web client

"The Study", in a browser. W2 ships the shell only: the three pillars
(Ask · Search · Library), The Study's frozen tokens (light + lamplight dark),
and a typed client proving React → Core API → `/health`. Screens land one
milestone at a time (W3 Ask, W4 Library, W5 Search, …).

## Run

Two processes, both loopback-only:

```bash
# 1. the Core API (repo root, project venv)
python -m server

# 2. the web client
cd clients/web
npm install
npm run dev        # http://127.0.0.1:5173
```

The top bar's Offline chip goes green when the engine answers `/health`;
"Engine not running" means start `python -m server`.

Newsreader is self-hosted via `@fontsource` — no runtime font CDN (ADR-001).
