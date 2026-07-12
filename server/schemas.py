"""The Core API contract (ADR-017): request/response payload shapes.

These models — not HTTP — are the architectural boundary clients depend on.
Every field mirrors a value the engine already computes; nothing here is
invented, renamed, or enriched. ``Explanation``'s fields are carried verbatim
(ADR-013: evidence combination, never model cognition), and ``confidence``
stays the qualitative string the engine produces (ADR-012).

Contract philosophy (deliberate): this is a **local contract for our own
clients** (web/desktop/mobile), not a stable public API — we own both sides,
so mirroring the engine's models is the intended tradeoff: zero translation
drift, and the explainability payload reaches clients unfiltered. If an
engine dataclass gains a field, adding it here is a conscious, reviewed
choice, made milestone-by-milestone. Public/third-party stability guarantees
would be a different philosophy and require a new ADR before adopting.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# -- ask ----------------------------------------------------------------------


class AskRequest(BaseModel):
    question: str = Field(min_length=1, description="The question to answer")
    k: int = Field(default=5, ge=1, le=50, description="Top-k chunks to retrieve")


class SourceModel(BaseModel):
    """A cited chunk, exactly as ``aipos.answering.Source``."""

    chunk_id: int
    file: str
    snippet: str


class EvidenceModel(BaseModel):
    """Citation-integrity verification, as ``EvidenceVerification`` (T5.3)."""

    verified: bool
    reason: str
    verified_citations: int
    total_citations: int


class ExplanationModel(BaseModel):
    """The reasoning trace, field-for-field from ``aipos.explainability.Explanation``."""

    timestamp: str
    strategy: str
    reason: str
    retrieved_count: int
    graph_expanded: bool
    graph_relation_count: int
    reranked_count: int
    llm_consulted: bool
    grounded: bool
    citation_count: int
    confidence: str
    evidence: EvidenceModel


class AnswerResponse(BaseModel):
    answer: str
    sources: list[SourceModel]
    grounded: bool
    explanation: ExplanationModel


# -- documents ------------------------------------------------------------------


class DocumentModel(BaseModel):
    """A file row, as ``aipos.storage.FileRecord``."""

    id: int
    workspace_id: str
    path: str
    hash: str
    status: str
    error: str | None
    created_at: str
    updated_at: str


class ChunkModel(BaseModel):
    """A persisted chunk, as ``aipos.storage.ChunkRecord``."""

    id: int
    index: int
    text: str


class RetryResponse(BaseModel):
    id: int
    status: str


# -- search ---------------------------------------------------------------------


class SearchHit(BaseModel):
    """One retrieved chunk, as ``aipos.retrieval.RetrievalResult``."""

    chunk_id: int
    text: str
    score: float


# -- graph ----------------------------------------------------------------------


class EntityModel(BaseModel):
    """A graph node, as ``aipos.storage.EntityRecord``."""

    id: int
    name: str
    type: str


class EdgeModel(BaseModel):
    """A graph edge, as ``aipos.storage.EdgeRecord``."""

    id: int
    source_entity_id: int
    target_entity_id: int
    relation: str
    weight: int


class EntityPageResponse(BaseModel):
    """An entity plus its direct neighbours — the client's entity page."""

    entity: EntityModel
    neighbors: list[EntityModel]


# -- system ----------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    version: str
    embedding_model: str
    llm_model: str
    database_bytes: int
    vector_store_bytes: int
    offline: bool = True


class MessageResponse(BaseModel):
    detail: str
