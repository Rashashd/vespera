"""Pydantic request/response schemas for classify and embed endpoints (FR-003/FR-005b)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelVersion(BaseModel):
    """Per-artifact version stamp included in every response result (D9/FR-005b)."""

    name: str
    version: str
    sha256: str


# ---------------------------------------------------------------------------
# Classify
# ---------------------------------------------------------------------------


class ClassifyRequest(BaseModel):
    """POST /classify request body — batch ≤ 128 texts."""

    texts: list[str] = Field(..., max_length=128)


class ClassificationResult(BaseModel):
    """Single classification result: raw confidence + default-cutoff decision."""

    confidence: float = Field(..., ge=0.0, le=1.0)
    # confidence >= 0.5; callers may re-threshold the raw confidence (FR-001)
    is_adverse: bool
    model_version: ModelVersion


class ClassifyResponse(BaseModel):
    """POST /classify response — one result per input, in order."""

    model_version: ModelVersion
    results: list[ClassificationResult]


# ---------------------------------------------------------------------------
# Embed
# ---------------------------------------------------------------------------


class EmbedRequest(BaseModel):
    """POST /embed request body — batch ≤ 128 texts."""

    texts: list[str] = Field(..., max_length=128)


class EmbeddingResult(BaseModel):
    """Single embedding result: 768-dim L2-normalized vector."""

    embedding: list[float] = Field(..., description="768-dim L2-normalized vector")
    model_version: ModelVersion


class EmbedResponse(BaseModel):
    """POST /embed response — one vector per input, in order."""

    model_version: ModelVersion
    dim: int = 768
    results: list[EmbeddingResult]
