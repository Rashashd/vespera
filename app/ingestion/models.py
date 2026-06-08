"""ORM models for the ingestion corpus: 6 new tables + additive watchlist_items columns (spec 4)."""

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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Document(Base):
    """One real paper/record per client; the dedup target (FR-006, D10)."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("clients.id"), nullable=False)
    normalized_external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    source_reliability: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    origin_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    first_fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    sources: Mapped[list["DocumentSource"]] = relationship(
        "DocumentSource", cascade="all, delete-orphan", lazy="selectin"
    )
    provenance: Mapped[list["DocumentWatchlist"]] = relationship(
        "DocumentWatchlist", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            "source_reliability IN ('regulatory_alert','peer_reviewed','preprint','case_report')",
            name="ck_documents_reliability",
        ),
        Index("ux_documents_client_extid", "client_id", "normalized_external_id", unique=True),
        Index("ix_documents_client_id", "client_id"),
        Index("ix_documents_client_reliability", "client_id", "source_reliability"),
    )


class DocumentSource(Base):
    """Contributing source(s) for a document; 1 document → N sources (FR-005)."""

    __tablename__ = "document_sources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    source_external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    source_reliability: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "source IN ('pubmed','europepmc','openfda_faers','openfda_label',"
            "'fda_medwatch','ema','mhra')",
            name="ck_document_sources_source",
        ),
        CheckConstraint(
            "source_reliability IN ('regulatory_alert','peer_reviewed','preprint','case_report')",
            name="ck_document_sources_reliability",
        ),
        Index("ux_document_sources_doc_source", "document_id", "source", unique=True),
        Index("ix_document_sources_client_id", "client_id"),
    )


class DocumentWatchlist(Base):
    """Provenance: which watchlist(s)/run surfaced a document (FR-007)."""

    __tablename__ = "document_watchlists"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    watchlist_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    first_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ingestion_runs.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ux_document_watchlists_doc_wl", "document_id", "watchlist_id", unique=True),
        Index("ix_document_watchlists_watchlist_id", "watchlist_id"),
        Index("ix_document_watchlists_client_id", "client_id"),
    )


class IngestionRun(Base):
    """A tracked unit of ingestion work for one watchlist (FR-011, FR-024)."""

    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("clients.id"), nullable=False)
    watchlist_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("watchlists.id"), nullable=False
    )
    triggered_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="running")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    errored_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    run_sources: Mapped[list["IngestionRunSource"]] = relationship(
        "IngestionRunSource", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('running','success','partial_success','failed')",
            name="ck_ingestion_runs_status",
        ),
        Index("ix_ingestion_runs_client_id", "client_id"),
        Index("ix_ingestion_runs_watchlist_id", "watchlist_id"),
        Index("ix_ingestion_runs_status", "status"),
    )


class IngestionRunSource(Base):
    """Per-source outcome within a run (FR-012)."""

    __tablename__ = "ingestion_run_sources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    errored_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (
        CheckConstraint(
            "source IN ('pubmed','europepmc','openfda_faers','openfda_label',"
            "'fda_medwatch','ema','mhra')",
            name="ck_ingestion_run_sources_source",
        ),
        CheckConstraint(
            "status IN ('success','failed')",
            name="ck_ingestion_run_sources_status",
        ),
        Index("ux_ingestion_run_sources_run_source", "run_id", "source", unique=True),
        Index("ix_ingestion_run_sources_client_id", "client_id"),
    )


class SourceWatermark(Base):
    """Per-(watchlist, source) incremental high-water mark (FR-021, D9)."""

    __tablename__ = "source_watermarks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    watchlist_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    watermark_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cursor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "source IN ('pubmed','europepmc','openfda_faers','openfda_label',"
            "'fda_medwatch','ema','mhra')",
            name="ck_source_watermarks_source",
        ),
        Index("ux_source_watermarks_wl_source", "watchlist_id", "source", unique=True),
        Index("ix_source_watermarks_client_id", "client_id"),
    )
