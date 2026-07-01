"""Write-completion guard for AI Personal OS.

A newly detected file may still be mid-write (a large copy in progress).
``wait_until_stable`` polls the file's size and reports it stable only once the
size stops changing across consecutive polls, so downstream steps never read a
half-written file (PRD failure philosophy; Build Plan T1.3).

Size polling — not a fixed sleep — is used: small files pass in about one poll
interval, large copies are waited out, and a file whose size never settles
within the timeout is reported unstable so the caller can skip it.
"""

from __future__ import annotations

import time
from pathlib import Path

DEFAULT_POLL_INTERVAL = 0.5  # seconds between size checks
DEFAULT_TIMEOUT = 30.0  # seconds to wait for the size to settle


def wait_until_stable(
    path: Path,
    *,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    timeout: float = DEFAULT_TIMEOUT,
) -> bool:
    """Return True once ``path``'s size is unchanged between two consecutive polls.

    Returns False if the size never settles within ``timeout`` seconds, or if
    the file becomes unreadable (e.g. removed) while waiting. Detection is
    size-based only, which is the T1.3 scope.
    """
    deadline = time.monotonic() + timeout
    last_size = -1
    while time.monotonic() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size == last_size:
            return True
        last_size = size
        time.sleep(poll_interval)
    return False
