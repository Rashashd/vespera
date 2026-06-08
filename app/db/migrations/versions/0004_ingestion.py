"""ingestion corpus: 6 new tables + additive watchlist_items mesh columns

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCE_CHECK = (
    "source IN ('pubmed','europepmc','openfda_faers','openfda_label',"
    "'fda_medwatch','ema','mhra')"
)
_RELIABILITY_CHECK = (
    "source_reliability IN ('regulatory_alert','peer_reviewed','preprint','case_report')"
)


def upgrade() -> None:
    # --- documents --------------------------------------------------------------
    op.create_table(
        "documents",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.BigInteger(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("normalized_external_id", sa.String(512), nullable=False),
        sa.Column("source_reliability", sa.String(20), nullable=False),
        sa.Column("title", sa.String(1024), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("origin_url", sa.String(2048), nullable=True),
        sa.Column(
            "first_fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(_RELIABILITY_CHECK, name="ck_documents_reliability"),
    )
    op.create_index(
        "ux_documents_client_extid",
        "documents",
        ["client_id", "normalized_external_id"],
        unique=True,
    )
    op.create_index("ix_documents_client_id", "documents", ["client_id"])
    op.create_index(
        "ix_documents_client_reliability",
        "documents",
        ["client_id", "source_reliability"],
    )

    # --- document_sources -------------------------------------------------------
    op.create_table(
        "document_sources",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "document_id",
            sa.BigInteger(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("source_external_id", sa.String(512), nullable=False),
        sa.Column("source_reliability", sa.String(20), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(_SOURCE_CHECK, name="ck_document_sources_source"),
        sa.CheckConstraint(_RELIABILITY_CHECK, name="ck_document_sources_reliability"),
    )
    op.create_index(
        "ux_document_sources_doc_source",
        "document_sources",
        ["document_id", "source"],
        unique=True,
    )
    op.create_index("ix_document_sources_client_id", "document_sources", ["client_id"])

    # --- ingestion_runs ---------------------------------------------------------
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.BigInteger(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("watchlist_id", sa.BigInteger(), sa.ForeignKey("watchlists.id"), nullable=False),
        sa.Column(
            "triggered_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errored_count", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "status IN ('running','success','partial_success','failed')",
            name="ck_ingestion_runs_status",
        ),
    )
    op.create_index("ix_ingestion_runs_client_id", "ingestion_runs", ["client_id"])
    op.create_index("ix_ingestion_runs_watchlist_id", "ingestion_runs", ["watchlist_id"])
    op.create_index("ix_ingestion_runs_status", "ingestion_runs", ["status"])

    # --- document_watchlists ----------------------------------------------------
    op.create_table(
        "document_watchlists",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "document_id",
            sa.BigInteger(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "watchlist_id",
            sa.BigInteger(),
            sa.ForeignKey("watchlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "first_run_id",
            sa.BigInteger(),
            sa.ForeignKey("ingestion_runs.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ux_document_watchlists_doc_wl",
        "document_watchlists",
        ["document_id", "watchlist_id"],
        unique=True,
    )
    op.create_index("ix_document_watchlists_watchlist_id", "document_watchlists", ["watchlist_id"])
    op.create_index("ix_document_watchlists_client_id", "document_watchlists", ["client_id"])

    # --- ingestion_run_sources --------------------------------------------------
    op.create_table(
        "ingestion_run_sources",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey("ingestion_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("fetched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errored_count", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(_SOURCE_CHECK, name="ck_ingestion_run_sources_source"),
        sa.CheckConstraint(
            "status IN ('success','failed')", name="ck_ingestion_run_sources_status"
        ),
    )
    op.create_index(
        "ux_ingestion_run_sources_run_source",
        "ingestion_run_sources",
        ["run_id", "source"],
        unique=True,
    )
    op.create_index("ix_ingestion_run_sources_client_id", "ingestion_run_sources", ["client_id"])

    # --- source_watermarks ------------------------------------------------------
    op.create_table(
        "source_watermarks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "watchlist_id",
            sa.BigInteger(),
            sa.ForeignKey("watchlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("watermark_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cursor", sa.String(512), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(_SOURCE_CHECK, name="ck_source_watermarks_source"),
    )
    op.create_index(
        "ux_source_watermarks_wl_source",
        "source_watermarks",
        ["watchlist_id", "source"],
        unique=True,
    )
    op.create_index("ix_source_watermarks_client_id", "source_watermarks", ["client_id"])

    # --- watchlist_items additive columns (spec-3 carryover, D11) ---------------
    op.add_column("watchlist_items", sa.Column("mesh_validity", sa.String(12), nullable=True))
    op.add_column("watchlist_items", sa.Column("mesh_canonical", sa.String(512), nullable=True))
    op.create_check_constraint(
        "ck_watchlist_items_mesh_validity",
        "watchlist_items",
        "mesh_validity IS NULL OR mesh_validity IN ('valid','invalid','unvalidated')",
    )


def downgrade() -> None:
    # watchlist_items additive columns
    op.drop_constraint("ck_watchlist_items_mesh_validity", "watchlist_items", type_="check")
    op.drop_column("watchlist_items", "mesh_canonical")
    op.drop_column("watchlist_items", "mesh_validity")

    # New tables (reverse creation order to satisfy FK constraints)
    op.drop_index("ix_source_watermarks_client_id", table_name="source_watermarks")
    op.drop_index("ux_source_watermarks_wl_source", table_name="source_watermarks")
    op.drop_table("source_watermarks")

    op.drop_index("ix_ingestion_run_sources_client_id", table_name="ingestion_run_sources")
    op.drop_index("ux_ingestion_run_sources_run_source", table_name="ingestion_run_sources")
    op.drop_table("ingestion_run_sources")

    op.drop_index("ix_document_watchlists_client_id", table_name="document_watchlists")
    op.drop_index("ix_document_watchlists_watchlist_id", table_name="document_watchlists")
    op.drop_index("ux_document_watchlists_doc_wl", table_name="document_watchlists")
    op.drop_table("document_watchlists")

    op.drop_index("ix_ingestion_runs_status", table_name="ingestion_runs")
    op.drop_index("ix_ingestion_runs_watchlist_id", table_name="ingestion_runs")
    op.drop_index("ix_ingestion_runs_client_id", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")

    op.drop_index("ix_document_sources_client_id", table_name="document_sources")
    op.drop_index("ux_document_sources_doc_source", table_name="document_sources")
    op.drop_table("document_sources")

    op.drop_index("ix_documents_client_reliability", table_name="documents")
    op.drop_index("ix_documents_client_id", table_name="documents")
    op.drop_index("ux_documents_client_extid", table_name="documents")
    op.drop_table("documents")
