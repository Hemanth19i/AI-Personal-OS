"""Filesystem layout for AI Personal OS.

Path *values* are defined in one place (``AppConfig``); directory *creation*
happens in one place (here). The SQLite database location lives here too (its
consumer — the application bootstrap — exists as of T1.1). Vector-store and
graph locations are added by their owning components in later milestones.
"""

from __future__ import annotations

import logging
from pathlib import Path

from aipos.config import AppConfig
from aipos.storage import DATABASE_FILENAME

logger = logging.getLogger(__name__)


def ensure_app_directories(config: AppConfig) -> None:
    """Create the application's data directories if they do not exist.

    Idempotent: safe to call on every startup.
    """
    for directory in (config.data_dir, config.watched_folder):
        directory.mkdir(parents=True, exist_ok=True)
        logger.debug("Ensured directory exists: %s", directory)


def database_path(config: AppConfig) -> Path:
    """Absolute path to the SQLite database file, inside the data directory."""
    return config.data_dir / DATABASE_FILENAME
