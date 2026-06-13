"""SQLAlchemy ORM model for the findings table (spec 8, migration 0007)."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Finding(Base):
    """One candidate adverse event per (document_id, drug, reaction) grain (FR-010)."""

    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    drug: Mapped[str] = mapped_column(String(512), nullable=False)
    reaction: Mapped[str] = mapped_column(String(512), nullable=False)
    bucket: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    model_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    resolution_path: Mapped[str] = mapped_column(String(12), nullable=False)
    corroboration_sources: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "bucket IN ('irrelevant','positive','minor','urgent','emergency')",
            name="ck_findings_bucket",
        ),
        CheckConstraint(
            "status IN ('pending_expedited','pending_batch','classified',"
            "'processing','reported','discarded')",
            name="ck_findings_status",
        ),
        CheckConstraint(
            "resolution_path IN ('model','llm','escalated')",
            name="ck_findings_resolution_path",
        ),
        Index("ux_findings_doc_drug_reaction", "document_id", "drug", "reaction", unique=True),
        Index("ix_findings_client_id", "client_id"),
        Index("ix_findings_status", "status"),
        Index("ix_findings_client_bucket", "client_id", "bucket"),
    )
