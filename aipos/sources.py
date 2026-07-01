"""Data source adapters for AI Personal OS.

Defines the ``SourceAdapter`` contract (ADR-008, Design Doc §A2a) and its only
Phase 1 implementation, ``FolderSource``.

As of T1.2, ``FolderSource`` implements ``watch()`` — detecting newly created
files in a local folder via watchdog and reporting each path to a callback.
The remaining interface methods (scan/parse/metadata/delete) are still stubs;
they arrive in later milestones. Remote sources (GitHub, Email, Drive, ...)
are Phase 3 implementations of this same interface.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

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

    Owns folder watching (ticket T1.2): ``watch()`` starts a background
    watchdog observer that reports each newly created file; ``stop()`` shuts it
    down cleanly. scan/parse/metadata/delete remain stubs for later milestones.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._observer: Observer | None = None

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
        observer.schedule(_NewFileHandler(on_file), str(self._root), recursive=True)
        observer.start()
        self._observer = observer
        logger.info("Watching %s for new files", self._root)

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
