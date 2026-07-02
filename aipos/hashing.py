"""SHA-256 hashing utility for AI Personal OS.

Computes a file's SHA-256 digest and nothing else — no database access, no
registration logic. Used to give each ingested file a content identity
(Build Plan T1.4).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK_SIZE = 65536  # read in 64 KiB blocks so large files don't load into memory


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of the file at ``path``."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()
