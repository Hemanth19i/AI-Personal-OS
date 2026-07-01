"""Application configuration for AI Personal OS.

Phase 1 config (Build Plan T0.2): the local data directory, the watched folder,
and the model names. Values are read from a TOML file at the project root; on
first run a default file is generated. TOML is read with the standard-library
``tomllib`` (Python 3.11+), so no third-party dependency is introduced.

Path values may be relative in the file (resolved against the project root) or
absolute. All paths are exposed here, in one place, so the rest of the codebase
never hardcodes filesystem locations.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "config.toml"

# Fallback values used when an existing config file omits a key. The generated
# default file (below) mirrors these.
_DEFAULT_DATA_DIR = "data"
_DEFAULT_WATCHED_FOLDER = "data/watched"
_DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
_DEFAULT_LLM_MODEL = "llama3.1"


@dataclass(frozen=True)
class AppConfig:
    """Resolved, absolute application configuration."""

    data_dir: Path
    watched_folder: Path
    embedding_model: str
    llm_model: str


def load_config(project_root: Path) -> AppConfig:
    """Load configuration, generating a default file on first run.

    Args:
        project_root: Directory the config file lives in and relative paths
            resolve against.

    Returns:
        The resolved application configuration.
    """
    config_path = project_root / CONFIG_FILENAME
    if not config_path.exists():
        config_path.write_text(_DEFAULT_CONFIG_TOML, encoding="utf-8")
        logger.info("Created default configuration at %s", config_path)

    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    return _from_raw(raw, project_root)


def _from_raw(raw: dict, project_root: Path) -> AppConfig:
    models = raw.get("models", {})
    return AppConfig(
        data_dir=_resolve(project_root, raw.get("data_dir", _DEFAULT_DATA_DIR)),
        watched_folder=_resolve(
            project_root, raw.get("watched_folder", _DEFAULT_WATCHED_FOLDER)
        ),
        embedding_model=models.get("embedding", _DEFAULT_EMBEDDING_MODEL),
        llm_model=models.get("llm", _DEFAULT_LLM_MODEL),
    )


def _resolve(project_root: Path, value: str) -> Path:
    """Resolve a config path value to an absolute path."""
    path = Path(value)
    return (path if path.is_absolute() else project_root / path).resolve()


_DEFAULT_CONFIG_TOML = """\
# AI Personal OS — configuration
# Paths may be relative (resolved against the project root) or absolute.

# Local data directory. Everything the app generates lives here.
data_dir = "data"

# Folder watched for documents to ingest (PDF, TXT, Markdown).
watched_folder = "data/watched"

# Local model names (consumed later: embeddings at T2.3, the LLM at T3.3).
[models]
embedding = "nomic-embed-text"
llm = "llama3.1"
"""
