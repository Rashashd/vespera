"""ORM model for the llm_usage table (migration 0009)."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LlmUsage(Base):
    """One row per external LLM call; drives the per-client cost dashboard (FR-033)."""

    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    finding_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("findings.id", ondelete="SET NULL"), nullable=True
    )
    call_site: Mapped[str] = mapped_column(String(8), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("call_site IN ('triage','agent')", name="ck_llm_usage_call_site"),
        Index("ix_llm_usage_client_id", "client_id"),
        Index("ix_llm_usage_client_created", "client_id", "created_at"),
    )
