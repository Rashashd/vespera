"""Pydantic schemas for embedding API boundaries."""

from datetime import datetime

from pydantic import BaseModel


class IndexBuildRunOut(BaseModel):
    """Index build run output (no ORM at the boundary)."""

    id: int
    client_id: int
    status: str
    started_at: datetime
    finished_at: datetime | None
    documents_processed: int
    chunks_created: int
    documents_skipped: int
    documents_errored: int

    class Config:
        from_attributes = True


class DocumentIndexStateOut(BaseModel):
    """Document index state output (no ORM at the boundary)."""

    document_id: int
    status: str
    chunk_count: int
    embedder_version: str | None
    attempts: int
    updated_at: datetime

    class Config:
        from_attributes = True

