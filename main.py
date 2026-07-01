"""Entry point for AI Personal OS.

Phase 1 skeleton. On startup it loads configuration (generating a default
config file on first run), ensures the local data directories exist, and
initializes the SQLite storage layer (creating the database and schema on
first run). It then starts watching the configured folder and runs until
interrupted (Ctrl+C), logging each newly created file. A fresh clone can run
``python main.py`` with no manual setup. Real behaviour (ingestion, retrieval,
reasoning) is introduced in later milestones per the Build Plan.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from aipos.config import load_config
from aipos.paths import database_path, ensure_app_directories
from aipos.sources import FolderSource
from aipos.storage import SQLiteStorage

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

    # Initialize storage: connect (creating the database and files table on
    # first run) and close cleanly. No data is inserted here.
    db_path = database_path(config)
    with SQLiteStorage(db_path):
        logger.info("SQLite storage initialized at %s (files table ensured)", db_path)

    # Start watching the configured folder for new files (T1.2). FolderSource
    # owns the watching; main only starts it, reports each path, and stops it
    # cleanly on shutdown. No ingestion happens here — detection only.
    source = FolderSource(config.watched_folder)
    source.watch(lambda path: logger.info("New file detected: %s", path))

    # flush=True: stdout is block-buffered when piped, and the process then
    # blocks in the watch loop, so flush the readiness banner immediately.
    print("AI Personal OS — alive", flush=True)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        source.stop()


if __name__ == "__main__":
    main()
