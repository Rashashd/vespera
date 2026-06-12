"""Pydantic boundary schemas for the RAG retrieval endpoint (spec 7)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.embedding.enums import ChunkType
from app.ingestion.enums import SourceReliability


class RetrieveRequest(BaseModel):
    """POST /clients/{client_id}/search request body (FR-001/FR-009/FR-019)."""

    query: str = Field(..., min_length=1, max_length=1024)
    top_k: int = Field(10, ge=1, le=50)
    chunk_types: list[ChunkType] | None = None
    source_reliabilities: list[SourceReliability] | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None

    @field_validator("query")
    @classmethod
    def query_non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("query must not be blank")
        return v


class RetrievedPassage(BaseModel):
    """One ranked passage with full provenance and position anchor (FR-011/FR-012)."""

    chunk_id: int
    document_id: int
    ordinal: int
    chunk_type: str
    section: str | None
    text: str
    score: float
    rank: int
    source_reliability: str
    title: str | None
    external_id: str
    date: datetime | None
    sources: list[str]


class CorroborationSource(BaseModel):
    """One distinct source document contributing to the corroboration count (FR-013–015)."""

    document_id: int
    title: str | None
    external_id: str
    date: datetime | None
    source_reliability: str
    sources: list[str]
    passage_chunk_ids: list[int]


class RetrieveResponse(BaseModel):
    """POST /clients/{client_id}/search response (FR-014/FR-015/FR-023)."""

    query_hash: str
    embedder_version: str
    results: list[RetrievedPassage]
    corroboration_count: int
    corroboration_sources: list[CorroborationSource]
