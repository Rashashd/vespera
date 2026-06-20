"""Pydantic boundary schemas for the reports API (no ORM leakage)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, computed_field

from app.reports.enums import ClaimProvenance, FindingReportState, ReportStatus, ReportType


def delivery_status_label(status: str) -> str:
    """Map a report status to its reviewer-facing delivery label (spec 13 FR-009).

    Pre-delivery statuses (drafted/under_review/rejected/discarded/needs_manual_revision) are
    'not_applicable' — the delivery chip is only meaningful from approval onward.
    """
    if status == ReportStatus.APPROVED:
        return "approved_pending_delivery"
    if status in (ReportStatus.SENT, ReportStatus.DELIVERED, ReportStatus.DELIVERY_FAILED):
        return str(status)
    return "not_applicable"


class Claim(BaseModel):
    """One structured claim in a report's claim list (FR-004)."""

    text: str
    provenance: ClaimProvenance
    source_ref: str | None = None


class ReportResponse(BaseModel):
    """Full report response for GET /clients/{id}/reports/{rid} (FR-020)."""

    id: int
    client_id: int
    report_type: ReportType
    status: ReportStatus
    structured_fields: list[Claim]
    draft_body: str | None
    corroboration_count: int
    corroboration_sources: list[dict] | None
    revision_count: int
    reviewer_comments: list[dict]
    sla_deadline: datetime | None
    watchlist_id: int | None
    cycle_period_start: datetime | None
    cycle_period_end: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def delivery_status(self) -> str:
        """Reviewer-facing delivery label derived from status (spec 13 US2)."""
        return delivery_status_label(self.status)


class ReportSummary(BaseModel):
    """Compact report entry for the reviewer queue list (GET /clients/{id}/reports)."""

    id: int
    client_id: int
    report_type: ReportType
    status: ReportStatus
    # Highest-severity bucket among the report's included findings (emergency/urgent/minor/
    # positive); None when the report has no included findings. Lets the list show the clinical
    # classification without a per-row findings fetch.
    severity: str | None = None
    corroboration_count: int
    revision_count: int
    sla_deadline: datetime | None
    watchlist_id: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def delivery_status(self) -> str:
        """Reviewer-facing delivery label derived from status (spec 13 US2)."""
        return delivery_status_label(self.status)


class ApproveRequest(BaseModel):
    """Body for POST .../reports/{rid}/approve (no payload required; included for future use)."""

    pass


class EditApproveRequest(BaseModel):
    """Body for POST .../reports/{rid}/edit-approve; reviewer supplies corrected content."""

    draft_body: str = Field(..., min_length=1)
    structured_fields: list[Claim] = Field(default_factory=list)
    comment: str = Field("", max_length=2000)


class RejectRequest(BaseModel):
    """Body for POST .../reports/{rid}/reject; reviewer must provide a redraft comment."""

    comment: str = Field(..., min_length=1, max_length=2000)


class DiscardRequest(BaseModel):
    """Body for POST .../reports/{rid}/discard."""

    reason: str = Field("", max_length=2000)


class FindingDropRequest(BaseModel):
    """Body for POST .../findings/{fid}/drop (puts finding back to pending_batch)."""

    pass


class FindingDiscardRequest(BaseModel):
    """Body for POST .../findings/{fid}/discard (permanently discards the finding)."""

    reason: str = Field("", max_length=2000)


class ReportFindingResponse(BaseModel):
    """One finding link entry within a batch report."""

    id: int
    report_id: int
    finding_id: int
    client_id: int
    report_type: ReportType
    state: FindingReportState
    created_at: datetime

    model_config = {"from_attributes": True}


class ConsolidateResponse(BaseModel):
    """Response for POST .../watchlists/{wid}/consolidate-batch."""

    report_id: int
    status: ReportStatus
    finding_count: int


class PassageResponse(BaseModel):
    """Exact passage text for a chunk (FR-029)."""

    chunk_id: int
    text: str
    section: str | None
    source_reliability: str
    date: datetime | None
    document_id: int
    title: str | None
    external_id: str | None


class ReportFindingDetail(BaseModel):
    """Per-finding detail for batch report UI and client portal (FR-031)."""

    id: int
    report_id: int
    finding_id: int
    drug: str
    reaction: str
    bucket: str
    state: FindingReportState
    created_at: datetime

    model_config = {"from_attributes": True}


class PortalReportSummary(BaseModel):
    """Portal-safe report summary (omits reviewer-internal fields — FR-030)."""

    id: int
    report_type: ReportType
    status: ReportStatus
    delivery_status: str
    # Highest-severity included-finding bucket (emergency/urgent/minor/positive); None if none.
    severity: str | None = None
    watchlist_id: int | None
    corroboration_count: int
    sla_deadline: datetime | None
    cycle_period_start: datetime | None
    cycle_period_end: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PortalReportDetail(PortalReportSummary):
    """Full portal report including claims, body, sources, and per-finding status (FR-030)."""

    structured_fields: list[Claim]
    draft_body: str | None
    corroboration_sources: list[dict] | None
