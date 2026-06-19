"""ORM models for watchlist_cycles and dead_letter (spec 11)."""

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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_CYCLE_STATUS_CHECK = "status IN ('in_progress','completed','failed')"
_CYCLE_STAGE_CHECK = (
    "current_stage IN ('ingestion','index','triage','expedited','consolidation','done')"
)


class WatchlistCycle(Base):
    """One automated monitoring cycle for a watchlist (FR-016)."""

    __tablename__ = "watchlist_cycles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    watchlist_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    current_stage: Mapped[str] = mapped_column(String(24), nullable=False)
    cadence_at_start: Mapped[str] = mapped_column(String(16), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingestion_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ingestion_runs.id", ondelete="SET NULL"), nullable=True
    )
    index_build_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("index_build_runs.id", ondelete="SET NULL"), nullable=True
    )
    skipped_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Set at consolidation when the cycle's index run produced any triage-failed document, so a
    # degraded run is distinguishable from a clean completion (status stays 'completed', but a
    # non-NULL degraded_reason means triage coverage was incomplete — Constitution III).
    degraded_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    failure_stage: Mapped[str | None] = mapped_column(String(24), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(_CYCLE_STATUS_CHECK, name="ck_watchlist_cycles_status"),
        CheckConstraint(_CYCLE_STAGE_CHECK, name="ck_watchlist_cycles_stage"),
        Index("ix_watchlist_cycles_watchlist_id", "watchlist_id"),
        Index("ix_watchlist_cycles_client_id", "client_id"),
        Index(
            "uq_watchlist_cycles_in_progress",
            "watchlist_id",
            unique=True,
            postgresql_where="status = 'in_progress'",
        ),
    )


class DeadLetter(Base):
    """Job that exhausted its retries; free of PII/secrets (FR-009/FR-011)."""

    __tablename__ = "dead_letter"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(String(48), nullable=False)
    job_key: Mapped[str] = mapped_column(String(128), nullable=False)
    client_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    args_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    error_class: Mapped[str] = mapped_column(String(80), nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    first_failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dead_lettered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_dead_letter_client_id", "client_id"),
        Index("ix_dead_letter_dead_lettered_at", "dead_lettered_at"),
        Index(
            "ix_dead_letter_unresolved",
            "dead_lettered_at",
            postgresql_where="resolved_at IS NULL",
        ),
    )
