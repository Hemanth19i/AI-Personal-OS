"""Data source adapters for AI Personal OS.

Defines the ``SourceAdapter`` contract (ADR-008, Design Doc §A2a) and its only
Phase 1 implementation, ``FolderSource``.

This ticket (T0.3) establishes the architecture only. The interface methods are
stubs: real behaviour — walking the folder, parsing files, watching for changes
— arrives in Milestone 1/2. Remote sources (GitHub, Email, Drive, ...) are
Phase 3 implementations of this same interface and are out of scope here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path


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
    def watch(self) -> None:
        """Begin detecting changes to this source's items."""

    @abstractmethod
    def metadata(self, item: Path) -> Mapping[str, object]:
        """Return metadata for a single item."""

    @abstractmethod
    def delete(self, item: Path) -> None:
        """Handle removal of a single item."""


class FolderSource(SourceAdapter):
    """A local watched folder — the only Phase 1 source.

    Represents a folder into which the user drops documents (PDF, TXT,
    Markdown). T0.3 only wires up the class and its root path; each interface
    method is implemented in a later milestone (scan/watch/metadata/delete in
    Milestone 1, parse in Milestone 2).
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        """The local folder this source represents."""
        return self._root

    def scan(self) -> list[Path]:
        raise NotImplementedError("FolderSource.scan arrives in Milestone 1")

    def parse(self, item: Path) -> str:
        raise NotImplementedError("FolderSource.parse arrives in Milestone 2")

    def watch(self) -> None:
        raise NotImplementedError("FolderSource.watch arrives in Milestone 1")

    def metadata(self, item: Path) -> Mapping[str, object]:
        raise NotImplementedError("FolderSource.metadata arrives in Milestone 1")

    def delete(self, item: Path) -> None:
        raise NotImplementedError("FolderSource.delete arrives in Milestone 1")
