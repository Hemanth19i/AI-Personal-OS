"""Run the Core API locally: ``python -m server`` from the repo root.

Binds to loopback only (ADR-001/ADR-017): the API is on-device by
construction. A LAN mode for the mobile companion is a separate, deliberate,
authenticated decision (future ADR) — not a flag here.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from server.app import create_app
from server.wiring import Runtime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def main() -> None:
    parser = argparse.ArgumentParser(prog="server", description="AI Personal OS Core API")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"Port (default {DEFAULT_PORT})"
    )
    args = parser.parse_args()
    app = create_app(Runtime(PROJECT_ROOT))
    uvicorn.run(app, host=LOOPBACK_HOST, port=args.port)


if __name__ == "__main__":
    main()
