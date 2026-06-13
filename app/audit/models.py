"""The append-only audit-log ORM model (consumed by the passive handler in this package)."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# The reserved sentinel actor id for system-initiated events (research.md D1).
SYSTEM_ACTOR_ID = 0


class AuditLog(Base):
    """Append-only record of one domain event (never updated or deleted; FR-013/FR-014)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # Human-actor referential link (spec 2, research D5); NULL for system events (sentinel 0).
    actor_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String, nullable=False)
    target: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    client_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_audit_log_actor_id", "actor_id"),
        Index("ix_audit_log_actor_type", "actor_type"),
        Index("ix_audit_log_actor_user_id", "actor_user_id"),
        Index("ix_audit_log_client_id", "client_id"),
        Index("ix_audit_log_created_at", "created_at"),
        Index("ix_audit_log_event_type", "event_type"),
    )
