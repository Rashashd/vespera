"""StrEnums for the reports domain — mirrored by CHECK constraints in migration 0008."""

from enum import StrEnum


class ReportType(StrEnum):
    """Whether a report covers one expedited finding or a consolidated batch."""

    EXPEDITED = "expedited"
    BATCH = "batch"


class ReportStatus(StrEnum):
    """HITL state machine states for a report (FR-014/016/021)."""

    DRAFTED = "drafted"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    DISCARDED = "discarded"
    NEEDS_MANUAL_REVISION = "needs_manual_revision"

    @property
    def is_terminal(self) -> bool:
        """Terminal statuses accept no further transitions in this feature."""
        return self in (ReportStatus.APPROVED, ReportStatus.DISCARDED)


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
