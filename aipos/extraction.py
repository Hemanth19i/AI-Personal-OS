"""Entity & relationship extraction for AI Personal OS (T4.1).

Turns document text into a structured set of entities and relationships and
nothing else — no SQL, no storage, no persistence, no retrieval, no graph. The
runtime backend is the *existing* local LLM (Design Doc §A2 Knowledge
Processing; PRD §6.3): this module depends on the ``LLM`` protocol from
``aipos.llm`` and reuses ``OllamaLLM`` rather than introducing a new backend.

This is the ``extracting`` step of the file lifecycle (Design Doc §A5):
``… → embedding → extracting → ready``. The ingestion coordinator
(``aipos.ingest``) invokes it after embedding; a failure here is recorded and
isolated exactly like an OCR or embedding failure. Callers depend on the
``EntityExtractor`` protocol, so tests inject a deterministic fake instead of
requiring a running Ollama service, and a later hybrid/rule-based extractor can
drop in without touching the coordinator (ADR-002's "hybrid rules + LLM" note).

Scope is strictly T4.1: extraction produces in-memory ``ExtractionResult``
objects. Persisting them to the frozen ``entities``/``edges`` tables is T4.2 and
is intentionally absent here (see Remaining Technical Debt).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from aipos.llm import LLM

logger = logging.getLogger(__name__)

# Default entity type when the model omits one — keeps the record well-formed
# without guessing. "Start simple": people and concepts (Build Plan T4.1).
_DEFAULT_ENTITY_TYPE = "unknown"


@dataclass(frozen=True)
class Entity:
    """A named thing found in the text: its surface name and a coarse type.

    ``type`` is a free-form label the model assigns (e.g. "person",
    "concept"); it is not a controlled vocabulary in Phase 1.
    """

    name: str
    type: str


@dataclass(frozen=True)
class Relationship:
    """A directed edge between two entity names with a relation label.

    ``source`` and ``target`` are entity *names* (not ids) — id assignment
    belongs to persistence (T4.2), which this module does not do.
    """

    source: str
    target: str
    relation: str


@dataclass(frozen=True)
class ExtractionResult:
    """The entities and relationships extracted from one body of text."""

    entities: list[Entity]
    relationships: list[Relationship]


@runtime_checkable
class EntityExtractor(Protocol):
    """Extracts entities and relationships from a body of text."""

    def extract(self, text: str) -> ExtractionResult:
        ...


# The extraction prompt. The model is pinned to strict JSON so the response is
# machine-parseable; the parser below is tolerant of the ways a local model
# still deviates (prose preambles, code fences, malformed entries).
_INSTRUCTIONS = (
    "You extract a knowledge graph from text. Identify the key entities "
    "(people and concepts) and the relationships between them.\n"
    "Rules:\n"
    "- Output ONLY a single JSON object. No prose, no code fences.\n"
    '- Shape: {"entities": [{"name": str, "type": str}], '
    '"relationships": [{"source": str, "target": str, "relation": str}]}\n'
    '- "type" is a short label such as "person" or "concept".\n'
    '- "relation" is a short verb phrase such as "mentions" or "relates_to".\n'
    "- source and target must be names that appear in the entities list.\n"
    "- If nothing can be extracted, output "
    '{"entities": [], "relationships": []}.'
)


class LLMEntityExtractor:
    """EntityExtractor backed by the existing local LLM (via the LLM protocol).

    Prompts the injected model for a JSON graph and parses it into an
    ``ExtractionResult``. It never raises on a malformed model response —
    unparseable output yields an empty result — so the only failure that
    reaches the coordinator is the backend itself being unavailable (mirroring
    ``OllamaEmbedder`` / ``TesseractOcr``), which the coordinator records as a
    file failure.
    """

    def __init__(self, llm: LLM) -> None:
        self._llm = llm

    def extract(self, text: str) -> ExtractionResult:
        """Extract entities and relationships from ``text``.

        Returns an empty result — without calling the LLM — when ``text`` has
        no non-whitespace content, consistent with the other read guards in the
        codebase. Duplicate entities and relationships are removed, preserving
        first-seen order.
        """
        if not text.strip():
            return ExtractionResult(entities=[], relationships=[])
        raw = self._llm.generate(_build_prompt(text))
        return _parse_response(raw)


def _build_prompt(text: str) -> str:
    """Build the extraction prompt for ``text`` (pure and deterministic)."""
    return f"{_INSTRUCTIONS}\n\nText:\n{text}\n\nJSON:"


def _parse_response(raw: str) -> ExtractionResult:
    """Parse a model response into an ``ExtractionResult``, tolerating garbage.

    A missing, non-JSON, or wrongly-shaped response yields an empty result;
    individual malformed entries are skipped rather than failing the whole
    parse. Entities and relationships are de-duplicated, first occurrence kept.
    """
    payload = _extract_json_object(raw)
    if payload is None:
        logger.debug("Extraction response was not parseable JSON; returning empty")
        return ExtractionResult(entities=[], relationships=[])
    return ExtractionResult(
        entities=_parse_entities(payload.get("entities")),
        relationships=_parse_relationships(payload.get("relationships")),
    )


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    """Return the JSON object embedded in ``raw``, or None if there isn't one.

    Local models often wrap JSON in prose or ``` fences, so we scan for the
    outermost ``{ … }`` span rather than requiring the whole response to be
    JSON.
    """
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_entities(raw: Any) -> list[Entity]:
    if not isinstance(raw, list):
        return []
    entities: list[Entity] = []
    seen: set[tuple[str, str]] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = _clean_str(item.get("name"))
        if not name:
            continue  # an entity with no name is meaningless — skip it
        entity_type = _clean_str(item.get("type")) or _DEFAULT_ENTITY_TYPE
        key = (name, entity_type)
        if key in seen:
            continue
        seen.add(key)
        entities.append(Entity(name=name, type=entity_type))
    return entities


def _parse_relationships(raw: Any) -> list[Relationship]:
    if not isinstance(raw, list):
        return []
    relationships: list[Relationship] = []
    seen: set[tuple[str, str, str]] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        source = _clean_str(item.get("source"))
        target = _clean_str(item.get("target"))
        relation = _clean_str(item.get("relation"))
        if not source or not target or not relation:
            continue  # an edge needs both endpoints and a label
        key = (source, target, relation)
        if key in seen:
            continue
        seen.add(key)
        relationships.append(
            Relationship(source=source, target=target, relation=relation)
        )
    return relationships


def _clean_str(value: Any) -> str:
    """Return a trimmed string for ``value`` if it is a string, else ''."""
    return value.strip() if isinstance(value, str) else ""
