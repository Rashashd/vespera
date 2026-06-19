"""ORM models for chunks, indexing state, and index build runs."""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    FetchedValue,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.embedding.enums import (
    DocumentIndexStatus,
    IndexBuildRunStatus,
)


class Chunk(Base):
    """One searchable chunk with dense embedding and lexical vector (FR-002/FR-005)."""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-based order
    chunk_type: Mapped[str] = mapped_column(String(16), nullable=False)  # ChunkType StrEnum
    section: Mapped[str | None] = mapped_column(String(255), nullable=True)
    drug: Mapped[str | None] = mapped_column(String(255), nullable=True)  # always NULL in v1
    date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_reliability: Mapped[str] = mapped_column(String(20), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(768), nullable=False)
    text_tsv: Mapped[str] = mapped_column(TSVECTOR, nullable=False, server_default=FetchedValue())
    embedder_version: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Idempotency guard: a re-attempt cannot duplicate
        Index("uq_chunks_document_ordinal", "document_id", "ordinal", unique=True),
        # Tenant scope
        Index("ix_chunks_client_id", "client_id"),
        # Document chunk-set lookup
        Index("ix_chunks_document_id", "document_id"),
        # Spec-7 chunk filtering by type
        Index("ix_chunks_client_chunk_type", "client_id", "chunk_type"),
        # Lexical retrieval (FR-015)
        Index("ix_chunks_text_tsv", "text_tsv", postgresql_using="gin"),
        # Dense retrieval — HNSW index (FR-015)
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class DocumentIndexState(Base):
    """1:1 with documents; tracks per-document indexing progress (FR-009/FR-010)."""

    __tablename__ = "document_index_state"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    client_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=DocumentIndexStatus.NOT_INDEXED,
    )
    embedder_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Durable triage-degraded marker (Constitution III): set when triage could not run for this
    # document (e.g. an NER outage), so a broken run is detectable and the cycle cannot report
    # 'completed' clean. NULL = triage ran (or has not run yet). triage_error is a PII-free code.
    triage_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    triage_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Set when triage RAN for this document (whether or not it produced findings); lets the
    # staleness sweep tell a legitimately-zero-finding document from a never-triaged one.
    triaged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("index_build_runs.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Hot scan: find not-indexed / retryable documents for client X
        Index("ix_document_index_state_client_id", "client_id"),
        Index("ix_document_index_state_client_status", "client_id", "status"),
    )


class IndexBuildRun(Base):
    """Index-build run: observability + one-in-flight guard (FR-010/FR-026)."""

    __tablename__ = "index_build_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("clients.id"), nullable=False)
    # NULL = client-wide manual build; non-NULL = watchlist-scoped cadence build (spec 11 D7)
    watchlist_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("watchlists.id", ondelete="CASCADE", name="fk_index_runs_watchlist"),
        nullable=True,
    )
    triggered_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=IndexBuildRunStatus.RUNNING,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    documents_processed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    chunks_created: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    documents_skipped: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    documents_errored: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (
        # Per-(client,watchlist) in-flight guard; NULL watchlist_id = client-wide manual slot
        Index(
            "uq_index_build_runs_client_wl_running",
            "client_id",
            "watchlist_id",
            unique=True,
            postgresql_where="status = 'running'",
        ),
        Index("ix_index_build_runs_client_id", "client_id"),
        Index("ix_index_build_runs_status", "status"),
        Index("ix_index_build_runs_watchlist_id", "watchlist_id"),
    )
