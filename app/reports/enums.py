"""StrEnums for the reports domain — mirrored by CHECK constraints in migration 0008."""

from enum import StrEnum


class ReportType(StrEnum):
    """Whether a report covers one expedited finding or a consolidated batch."""

    EXPEDITED = "expedited"
    BATCH = "batch"


class ReportStatus(StrEnum):
    """HITL + delivery state machine states for a report (FR-014/016/021; spec 13 FR-004)."""

    DRAFTED = "drafted"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    DISCARDED = "discarded"
    NEEDS_MANUAL_REVISION = "needs_manual_revision"
    # Delivery lifecycle (spec 13): approved → sent → delivered | delivery_failed.
    SENT = "sent"
    DELIVERED = "delivered"
    DELIVERY_FAILED = "delivery_failed"

    @property
    def is_terminal(self) -> bool:
        """Terminal statuses accept no further HITL transitions in this feature.

        `delivered` is terminal; `sent`/`delivery_failed` are NOT (a failed delivery can be
        re-sent, and `sent` is awaiting confirmation) — spec 13 FR-004/FR-006.
        """
        return self in (ReportStatus.APPROVED, ReportStatus.DISCARDED, ReportStatus.DELIVERED)


class ClaimProvenance(StrEnum):
    """How a structured-field claim was produced (FR-004)."""

    DRAFTED_GROUNDED = "drafted_grounded"
    REVIEWER_ATTESTED = "reviewer_attested"
    # Batch summary lines aggregate already-grounded findings; not tied to one passage.
    AGGREGATED = "aggregated"


class FindingReportState(StrEnum):
    """Per-finding inclusion state inside a batch report (FR-013a)."""

    INCLUDED = "included"
    DROPPED = "dropped"
    DISCARDED = "discarded"
