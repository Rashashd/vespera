"""parse-chunk-embed: RAG index foundation — chunks, document_index_state, index_build_runs

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHUNK_TYPE_CHECK = "chunk_type IN ('text','table','figure_caption','structured_data')"
_DOC_INDEX_STATUS_CHECK = (
    "status IN ('not_indexed','indexed','indexed_empty','errored_transient','errored_permanent')"
)
_RUN_STATUS_CHECK = "status IN ('running','success','partial_success','failed')"
_SOURCE_RELIABILITY_CHECK = (
    "source_reliability IN ('pubmed','europepmc','openfda','fda_medwatch','ema','mhra','regulatory_alert')"
)


def upgrade() -> None:
    # Create pgvector extension (safe to do multiple times)
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    # --- TABLE: chunks (FR-002/FR-005/FR-016) ———————————————————————————
    op.create_table(
        "chunks",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("chunk_type", sa.String(16), nullable=False),
        sa.Column("section", sa.String(255), nullable=True),
        sa.Column("drug", sa.String(255), nullable=True),
        sa.Column("date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_reliability", sa.String(20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(dim=768), nullable=False),
        sa.Column(
            "text_tsv",
            sa.dialects.postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', text)", persisted=True),
            nullable=False,
        ),
        sa.Column("embedder_version", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(_CHUNK_TYPE_CHECK, name="ck_chunks_type"),
        sa.CheckConstraint(_SOURCE_RELIABILITY_CHECK, name="ck_chunks_source_reliability"),
        sa.UniqueConstraint("document_id", "ordinal", name="uq_chunks_document_ordinal"),
    )

    op.create_index("ix_chunks_client_id", "chunks", ["client_id"], unique=False)
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"], unique=False)
    op.create_index("ix_chunks_client_chunk_type", "chunks", ["client_id", "chunk_type"], unique=False)
    op.create_index(
        "ix_chunks_text_tsv",
        "chunks",
        ["text_tsv"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # --- TABLE: document_index_state (FR-009/FR-010) —————————————————
    op.create_table(
        "document_index_state",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="not_indexed"),
        sa.Column("embedder_version", sa.String(64), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_run_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["last_run_id"], ["index_build_runs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", name="uq_document_index_state_document"),
        sa.CheckConstraint(_DOC_INDEX_STATUS_CHECK, name="ck_document_index_state_status"),
    )

    op.create_index(
        "ix_document_index_state_client_id",
        "document_index_state",
        ["client_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_index_state_client_status",
        "document_index_state",
        ["client_id", "status"],
        unique=False,
    )

    # --- TABLE: index_build_runs (FR-010/FR-026) ————————————————————
    op.create_table(
        "index_build_runs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("triggered_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("documents_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunks_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("documents_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("documents_errored", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(
            ["triggered_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(_RUN_STATUS_CHECK, name="ck_index_build_runs_status"),
    )

    op.create_index(
        "ix_index_build_runs_client_id",
        "index_build_runs",
        ["client_id"],
        unique=False,
    )
    op.create_index(
        "ix_index_build_runs_status",
        "index_build_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "uq_index_build_runs_client_running",
        "index_build_runs",
        ["client_id"],
        unique=True,
        postgresql_where="status = 'running'",
    )


def downgrade() -> None:
    # Drop tables in reverse FK dependency order; leave the vector extension in place.
    op.drop_table("document_index_state")
    op.drop_table("chunks")
    op.drop_table("index_build_runs")

    # NOTE: The vector extension is left in place (shared across potential objects).
