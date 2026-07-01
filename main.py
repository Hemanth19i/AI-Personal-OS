"""Entry point for AI Personal OS.

Phase 1 skeleton. On startup it loads configuration (generating a default
config file on first run) and ensures the local data directories exist, then
prints a liveness banner. Real behaviour (ingestion, retrieval, reasoning) is
introduced in later milestones per the Build Plan.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from aipos.config import load_config
from aipos.paths import ensure_app_directories

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent


def main() -> None:
    """Bootstrap the application and print the liveness banner."""
    # Force UTF-8 output: on Windows, stdout defaults to a legacy code page
    # (e.g. cp1252) which mangles the em dash in a UTF-8 terminal.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = load_config(PROJECT_ROOT)
    ensure_app_directories(config)
    logger.info("Data directory: %s", config.data_dir)
    logger.info("Watched folder: %s", config.watched_folder)

    print("AI Personal OS — alive")


if __name__ == "__main__":
    main()
