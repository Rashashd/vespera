"""Pydantic schemas for the triage API boundary and internal DTOs (no ORM at boundaries)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.triage.enums import Bucket, FindingStatus, ResolutionPath


class FindingStateResponse(BaseModel):
    """Public API response for GET /clients/{id}/findings/{finding_id}."""

    id: int
    client_id: int
    document_id: int
    drug: str
    reaction: str
    bucket: Bucket
    status: FindingStatus
    model_confidence: Decimal | None
    resolution_path: ResolutionPath
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FindingOutcome(BaseModel):
    """Internal DTO returned by triage_document(); never exposed directly at the API layer."""

    document_id: int
    drug: str
    reaction: str
    bucket: Bucket
    status: FindingStatus
    model_confidence: float | None
    resolution_path: ResolutionPath
    finding_id: int | None = None
    created: bool = True
