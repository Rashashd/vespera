"""Read schemas for the audit-log viewer endpoint (staff oversight; FR-013/FR-014)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

# Event categories surfaced as convenience filters by the admin audit viewer. Each maps to
# the set of domain-event class names (audit_log.event_type) recorded for that activity.
AUDIT_CATEGORIES: dict[str, tuple[str, ...]] = {
    "reports": (
        "ReportDrafted",
        "ReportApproved",
        "ReportEdited",
        "ReportRejected",
        "ReportDiscarded",
        "ReportOperatorAlert",
    ),
    "findings": (
        "FindingClassified",
        "FindingDiscarded",
    ),
    "clients": (
        "ClientCreated",
        "ClientUpdated",
        "ClientSuspended",
        "ClientReactivated",
        "ClientReportEmailChanged",
    ),
    "jobs": (
        "JobDeadLettered",
        "ReportOperatorAlert",
    ),
}


class AuditEntryOut(BaseModel):
    """A single append-only audit-log row as returned to staff."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_id: int
    actor_type: str
    actor_user_id: int | None
    action: str
    target: str
    event_type: str
    client_id: int | None
    payload: dict | None
    created_at: datetime
