"""Text chunking for AI Personal OS.

Splits extracted text into overlapping, ordered chunks and nothing else — no
embeddings, no persistence (Design Doc §A5, the ``chunking`` lifecycle step).
Splitting is deterministic and offline: identical input and parameters always
produce identical chunks.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_CHUNK_SIZE = 1000  # characters per chunk
DEFAULT_OVERLAP = 200  # characters shared between consecutive chunks


@dataclass(frozen=True)
class Chunk:
    """One ordered slice of a document's text."""

    index: int
    text: str


def chunk_text(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Split ``text`` into ordered, overlapping chunks.

    Consecutive chunks advance by ``chunk_size - overlap`` characters and share
    ``overlap`` characters. Whitespace inside a chunk is preserved verbatim.
    Text with no non-whitespace content yields no chunks.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not 0 <= overlap < chunk_size:
        raise ValueError("overlap must be in the range [0, chunk_size)")

    if not text.strip():
        return []

    step = chunk_size - overlap
    chunks: list[Chunk] = []
    start = 0
    while True:
        chunks.append(Chunk(index=len(chunks), text=text[start : start + chunk_size]))
        if start + chunk_size >= len(text):
            break  # this chunk reached the end; a further window would be redundant
        start += step
    return chunks
