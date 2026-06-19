"""ORM model for per-channel delivery attempts (one row per report×channel; migration 0012)."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DeliveryAttempt(Base):
    """One dispatch of a report to one channel; the report's status is derived from its rows."""

    __tablename__ = "delivery_attempt"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("reports.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalized for RLS tenant-isolation + scoping (no subquery join on the policy predicate).
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(8), nullable=False)
    # Which email recipient was used (regular/urgent); null for SFTP.
    recipient_kind: Mapped[str | None] = mapped_column(String(8), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="pending")
    # PII-free failure summary (scrubbed via app/redaction before persistence).
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dispatched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("channel IN ('email','sftp')", name="ck_delivery_attempt_channel"),
        CheckConstraint(
            "status IN ('pending','delivered','failed')", name="ck_delivery_attempt_status"
        ),
        Index("ix_delivery_attempt_report_id", "report_id"),
        Index("ix_delivery_attempt_client_id", "client_id"),
        # Idempotency key for callbacks (D3): at most one attempt per report×channel.
        Index("ux_delivery_attempt_report_channel", "report_id", "channel", unique=True),
    )
