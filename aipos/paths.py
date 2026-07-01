"""Filesystem layout for AI Personal OS.

Path *values* are defined in one place (``AppConfig``); directory *creation*
happens in one place (here). Phase 1 (Build Plan T0.2) needs only the data
directory and the watched folder. Storage-engine locations (SQLite, vector
store, graph) are added by their owning components in later milestones.
"""

from __future__ import annotations

import logging

from aipos.config import AppConfig

logger = logging.getLogger(__name__)


def ensure_app_directories(config: AppConfig) -> None:
    """Create the application's data directories if they do not exist.

    Idempotent: safe to call on every startup.
    """
    for directory in (config.data_dir, config.watched_folder):
        directory.mkdir(parents=True, exist_ok=True)
        logger.debug("Ensured directory exists: %s", directory)
