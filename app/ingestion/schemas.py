"""Pydantic boundary schemas for ingestion endpoints (no ORM leakage, contracts/)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.ingestion.enums import IngestionRunStatus, SourceName, SourceReliability


class RunCounts(BaseModel):
    """Aggregate record counts for a run or a per-source outcome."""

    fetched: int = 0
    created: int = 0
    skipped: int = 0
    errored: int = 0


class IngestionRunSourceOut(BaseModel):
    """Per-source outcome row within a run (contracts/ingestion-runs.md)."""

    model_config = ConfigDict(from_attributes=True)

    source: str
    status: str
    error: str | None
    counts: RunCounts

    @classmethod
    def from_orm_row(cls, row) -> IngestionRunSourceOut:
        return cls(
            source=row.source,
            status=row.status,
            error=row.error,
            counts=RunCounts(
                fetched=row.fetched_count,
                created=row.created_count,
                skipped=row.skipped_count,
                errored=row.errored_count,
            ),
        )


class IngestionRunOut(BaseModel):
    """Summary + optional per-source detail for an ingestion run (contracts/ingestion-runs.md)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    watchlist_id: int
    status: IngestionRunStatus
    started_at: datetime
    finished_at: datetime | None
    counts: RunCounts
    sources: list[IngestionRunSourceOut] = Field(default_factory=list)

    @classmethod
    def from_orm(cls, run) -> IngestionRunOut:
        return cls(
            id=run.id,
            watchlist_id=run.watchlist_id,
            status=IngestionRunStatus(run.status),
            started_at=run.started_at,
            finished_at=run.finished_at,
            counts=RunCounts(
                fetched=run.fetched_count,
                created=run.created_count,
                skipped=run.skipped_count,
                errored=run.errored_count,
            ),
            sources=[IngestionRunSourceOut.from_orm_row(s) for s in run.run_sources],
        )


class DocumentSourceOut(BaseModel):
    """Per-source metadata for a document detail view (contracts/documents.md)."""

    source: str
    source_external_id: str
    source_reliability: str
    fetched_at: datetime


class DocumentProvenanceOut(BaseModel):
    """Watchlist provenance link for a document (contracts/documents.md)."""

    watchlist_id: int
    first_run_id: int | None
    created_at: datetime


class DocumentOut(BaseModel):
    """Summary document view (list endpoint) — no raw payloads (FR-023)."""

    id: int
    normalized_external_id: str
    source_reliability: SourceReliability
    title: str | None
    published_at: datetime | None
    origin_url: str | None
    contributing_sources: list[str]
    watchlist_ids: list[int]
    first_fetched_at: datetime
    last_fetched_at: datetime

    @classmethod
    def from_orm(cls, doc) -> DocumentOut:
        return cls(
            id=doc.id,
            normalized_external_id=doc.normalized_external_id,
            source_reliability=SourceReliability(doc.source_reliability),
            title=doc.title,
            published_at=doc.published_at,
            origin_url=doc.origin_url,
            contributing_sources=[s.source for s in doc.sources],
            watchlist_ids=[p.watchlist_id for p in doc.provenance],
            first_fetched_at=doc.first_fetched_at,
            last_fetched_at=doc.last_fetched_at,
        )


class DocumentDetailOut(DocumentOut):
    """Full document view with per-source detail and provenance (detail endpoint)."""

    summary: str | None
    sources: list[DocumentSourceOut]
    provenance: list[DocumentProvenanceOut]

    @classmethod
    def from_orm(cls, doc) -> DocumentDetailOut:  # type: ignore[override]
        base = DocumentOut.from_orm(doc)
        return cls(
            **base.model_dump(),
            summary=doc.summary,
            sources=[
                DocumentSourceOut(
                    source=s.source,
                    source_external_id=s.source_external_id,
                    source_reliability=s.source_reliability,
                    fetched_at=s.fetched_at,
                )
                for s in doc.sources
            ],
            provenance=[
                DocumentProvenanceOut(
                    watchlist_id=p.watchlist_id,
                    first_run_id=p.first_run_id,
                    created_at=p.created_at,
                )
                for p in doc.provenance
            ],
        )


class DocumentFilterParams(BaseModel):
    """Query-parameter filter bag for GET /documents."""

    watchlist_id: int | None = None
    source: SourceName | None = None
    reliability: SourceReliability | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
