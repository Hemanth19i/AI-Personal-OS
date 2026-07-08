"""Grounded prompt construction for AI Personal OS.

A single pure function that turns a question plus the reranked candidate chunks
into the prompt string handed to the LLM (Design Doc §A6, the Context Builder).
Nothing else — no LLM calls, no retrieval, no storage, no dependency injection.

The prompt pins the model to the supplied context and requires it to end with a
deterministic ``USED_CHUNKS`` footer naming the 1-based chunk numbers it relied
on (or ``NONE``), which the citation builder parses instead of scraping
free-form ``[1]`` markers.
"""

from __future__ import annotations

from aipos.retrieval import RetrievalResult
from aipos.storage import GraphRelation

# The exact marker the answer must end with; the citation builder splits on it.
USED_CHUNKS_HEADER = "USED_CHUNKS:"

# Heading for the optional graph-context block (T4.3). Framed as supporting
# context only: the model may use it to reason about relationships, but
# citations still come from the numbered chunks above it.
_GRAPH_CONTEXT_HEADER = (
    "Related facts from the knowledge graph "
    "(supporting context only; cite only the numbered context above):"
)

_INSTRUCTIONS = (
    "You are a careful assistant answering strictly from the provided context.\n"
    "Rules:\n"
    "- Answer ONLY using the numbered context below. Never use outside knowledge.\n"
    "- If the answer is not contained in the context, say you don't know.\n"
    "- Do not invent sources or facts.\n"
    "After your answer, on a new line, output exactly:\n"
    f"{USED_CHUNKS_HEADER}\n"
    "<comma-separated numbers of the context chunks you used, e.g. 1,3>\n"
    "or, if you could not answer from the context:\n"
    f"{USED_CHUNKS_HEADER}\n"
    "NONE"
)


def build_prompt(
    question: str,
    chunks: list[RetrievalResult],
    graph_context: list[GraphRelation] | None = None,
) -> str:
    """Build the grounded prompt for ``question`` over ``chunks``.

    Chunks are presented in the given (reranked) order and numbered from 1; those
    1-based numbers are the citation keys the model echoes in the ``USED_CHUNKS``
    footer. ``graph_context`` (T4.3) is optional supporting context — relationship
    triples rendered as plain facts, never numbered and never cited. When it is
    absent (the default) the prompt is byte-identical to the pre-T4.3 prompt. The
    function is pure and deterministic — identical inputs yield an identical prompt.
    """
    context_blocks = [
        f"[{position}] {chunk.text}"
        for position, chunk in enumerate(chunks, start=1)
    ]
    context = "\n\n".join(context_blocks) if context_blocks else "(no context)"
    return (
        f"{_INSTRUCTIONS}\n\n"
        f"Context:\n{context}\n\n"
        f"{_graph_block(graph_context)}"
        f"Question: {question}\n\n"
        "Answer:"
    )


def _graph_block(graph_context: list[GraphRelation] | None) -> str:
    """Render the graph-context section, or '' when there is none."""
    if not graph_context:
        return ""
    lines = "\n".join(
        f"- {relation.source} {relation.relation} {relation.target}"
        for relation in graph_context
    )
    return f"{_GRAPH_CONTEXT_HEADER}\n{lines}\n\n"
