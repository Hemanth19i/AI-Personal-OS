"""Data source adapters for AI Personal OS.

Defines the ``SourceAdapter`` contract (ADR-008, Design Doc §A2a) and its only
Phase 1 implementation, ``FolderSource``.

As of T1.2, ``FolderSource`` implements ``watch()`` — detecting newly created
files in a local folder via watchdog and reporting each path to a callback.
T1.3 adds a write-completion guard: each detected file is passed through
``wait_until_stable`` before being forwarded, so half-written files are never
reported. The remaining interface methods (scan/parse/metadata/delete) are
still stubs; they arrive in later milestones. Remote sources (GitHub, Email,
Drive, ...) are Phase 3 implementations of this same interface.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from aipos.stability import DEFAULT_POLL_INTERVAL, DEFAULT_TIMEOUT, wait_until_stable

logger = logging.getLogger(__name__)


class SourceAdapter(ABC):
    """Uniform contract every data source implements (ADR-008).

    A source enumerates its items, extracts their content, reports metadata,
    watches for changes, and handles removal. Keeping every source behind one
    interface is what lets new sources be added later without special-casing
    existing code.
    """

    @abstractmethod
    def scan(self) -> list[Path]:
        """Enumerate the items currently available from this source."""

    @abstractmethod
    def parse(self, item: Path) -> str:
        """Extract the text content of a single item."""

    @abstractmethod
    def watch(self, on_file: Callable[[Path], None]) -> None:
        """Begin detecting new items, calling ``on_file`` with each new path."""

    @abstractmethod
    def metadata(self, item: Path) -> Mapping[str, object]:
        """Return metadata for a single item."""

    @abstractmethod
    def delete(self, item: Path) -> None:
        """Handle removal of a single item."""


class _NewFileHandler(FileSystemEventHandler):
    """watchdog handler that forwards newly created file paths to a callback.

    Only ``on_created`` is handled, and directory events are ignored, so each
    new file yields a single trigger. (Files moved/renamed into the folder fire
    ``on_moved`` and are out of scope for this detection ticket.)
    """

    def __init__(self, on_file: Callable[[Path], None]) -> None:
        self._on_file = on_file

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._on_file(Path(event.src_path))


class FolderSource(SourceAdapter):
    """A local watched folder — the only Phase 1 source.

    Owns folder watching: ``watch()`` starts a background watchdog observer
    that reports each newly created file once it has finished being written
    (T1.2 detection + T1.3 write-completion guard); ``stop()`` shuts it down
    cleanly. scan/parse/metadata/delete remain stubs for later milestones.

    ``poll_interval`` and ``timeout`` tune the write-completion guard.
    """

    def __init__(
        self,
        root: Path,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._root = root
        self._observer: Observer | None = None
        self._poll_interval = poll_interval
        self._timeout = timeout

    @property
    def root(self) -> Path:
        """The local folder this source represents."""
        return self._root

    def scan(self) -> list[Path]:
        raise NotImplementedError("FolderSource.scan arrives in Milestone 1")

    def parse(self, item: Path) -> str:
        raise NotImplementedError("FolderSource.parse arrives in Milestone 2")

    def watch(self, on_file: Callable[[Path], None]) -> None:
        """Start watching the folder (recursively) for newly created files.

        Non-blocking: the observer runs in a background thread until ``stop()``
        is called. Raises if already watching.
        """
        if self._observer is not None:
            raise RuntimeError("FolderSource is already watching")
        observer = Observer()
        observer.schedule(
            _NewFileHandler(self._guarded(on_file)), str(self._root), recursive=True
        )
        observer.start()
        self._observer = observer
        logger.info("Watching %s for new files", self._root)

    def _guarded(self, on_file: Callable[[Path], None]) -> Callable[[Path], None]:
        """Wrap ``on_file`` so a file is forwarded only after writes finish.

        A file whose size never stabilizes within the timeout is logged and
        skipped (never forwarded).
        """

        def forward(path: Path) -> None:
            if wait_until_stable(
                path, poll_interval=self._poll_interval, timeout=self._timeout
            ):
                on_file(path)
            else:
                logger.warning(
                    "File never stabilized within %.1fs; skipping: %s",
                    self._timeout,
                    path,
                )

        return forward

    def stop(self) -> None:
        """Stop watching and join the observer thread. Safe to call when idle."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            logger.info("Stopped watching %s", self._root)

    def metadata(self, item: Path) -> Mapping[str, object]:
        raise NotImplementedError("FolderSource.metadata arrives in Milestone 1")

    def delete(self, item: Path) -> None:
        raise NotImplementedError("FolderSource.delete arrives in Milestone 1")
