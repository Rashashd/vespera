"""SQLAlchemy ORM models for reports, report_findings, and report_followups (migration 0008)."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Report(Base):
    """One drafted safety document for one client (expedited or batch)."""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    report_type: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    # Claim list: [{text, provenance, source_ref?}, ...]
    structured_fields: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="'[]'::jsonb"
    )
    draft_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    corroboration_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    corroboration_sources: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    revision_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reviewer_comments: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="'[]'::jsonb"
    )
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Delivery lifecycle timestamps + SLA escalation tracking (spec 13, migration 0012).
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 0 = none, 1 = reviewers notified, 2 = manager/admin notified (FR-012).
    sla_escalation_tier: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    sla_escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    watchlist_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("watchlists.id", ondelete="SET NULL"), nullable=True
    )
    cycle_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cycle_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("report_type IN ('expedited','batch')", name="ck_reports_type"),
        CheckConstraint(
            "status IN ('drafted','under_review','approved','rejected',"
            "'discarded','needs_manual_revision','sent','delivered','delivery_failed')",
            name="ck_reports_status",
        ),
        Index("ix_reports_client_id", "client_id"),
        Index("ix_reports_status", "status"),
        Index("ix_reports_client_status", "client_id", "status"),
    )


class ReportFinding(Base):
    """Report↔finding junction; carries per-finding inclusion state for batch reports."""

    __tablename__ = "report_findings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("reports.id", ondelete="CASCADE"), nullable=False
    )
    finding_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("findings.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Denormalized from reports.report_type to support the partial unique without a subquery.
    report_type: Mapped[str] = mapped_column(String(12), nullable=False)
    state: Mapped[str] = mapped_column(String(12), nullable=False, default="included")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "state IN ('included','dropped','discarded')", name="ck_report_findings_state"
        ),
        CheckConstraint("report_type IN ('expedited','batch')", name="ck_report_findings_type"),
        Index("ux_report_findings_unique", "report_id", "finding_id", unique=True),
        Index("ix_report_findings_finding_id", "finding_id"),
    )


class ReportFollowup(Base):
    """Emergency author-outreach artifact (not in the reviewer queue; sending deferred)."""

    __tablename__ = "report_followups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    finding_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("findings.id", ondelete="CASCADE"), nullable=False
    )
    report_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("reports.id", ondelete="SET NULL"), nullable=True
    )
    template_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    cover_message: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_kind: Mapped[str | None] = mapped_column(String(8), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="generated")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('generated','sent','failed')", name="ck_report_followups_status"
        ),
        Index("ux_report_followups_finding", "finding_id", unique=True),
    )
