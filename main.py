"""Entry point for AI Personal OS.

Phase 1 skeleton. On startup it loads configuration (generating a default
config file on first run), ensures the local data directories exist, and
initializes the SQLite storage layer (creating the database and schema on
first run). It then starts watching the configured folder and runs until
interrupted (Ctrl+C); each completed file is hashed and registered in SQLite.
A fresh clone can run ``python main.py`` with no manual setup. Further
behaviour (parsing, retrieval, reasoning) is introduced in later milestones
per the Build Plan.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from aipos.config import load_config
from aipos.embedding import OllamaEmbedder
from aipos.ingest import process_file
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

    # Storage stays open for the watch lifetime so completed files can be
    # registered; it is closed in the finally below.
    db_path = database_path(config)
    storage = SQLiteStorage(db_path)
    storage.connect()
    logger.info("SQLite storage initialized at %s (files table ensured)", db_path)

    # Watch the configured folder; each file that passes the write-completion
    # guard is registered and (if a PDF) parsed, chunked, persisted, and
    # embedded (T1.4 + T2.2..T2.5). FolderSource owns the watching and knows
    # nothing of hashing, parsing, embedding, or storage.
    embedder = OllamaEmbedder(config.embedding_model)
    source = FolderSource(config.watched_folder)
    source.watch(lambda path: process_file(path, storage, embedder))

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
        storage.close()


if __name__ == "__main__":
    main()
