"""watchlist_cycles, dead_letter, index_build_runs.watchlist_id, watchlists.budget_exceeded_policy

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CYCLE_STATUS_CHECK = "status IN ('in_progress','completed','failed')"
_CYCLE_STAGE_CHECK = (
    "current_stage IN ('ingestion','index','triage','expedited','consolidation','done')"
)
_BUDGET_POLICY_CHECK = "budget_exceeded_policy IN ('continue','critical_only','pause')"


def upgrade() -> None:
    # ── 1. NEW TABLE: watchlist_cycles ───────────────────────────────────────
    op.create_table(
        "watchlist_cycles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("watchlist_id", sa.BigInteger(), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("current_stage", sa.String(24), nullable=False),
        sa.Column("cadence_at_start", sa.String(16), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingestion_run_id", sa.BigInteger(), nullable=True),
        sa.Column("index_build_run_id", sa.BigInteger(), nullable=True),
        sa.Column("skipped_reason", sa.String(32), nullable=True),
        sa.Column("failure_stage", sa.String(24), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(_CYCLE_STATUS_CHECK, name="ck_watchlist_cycles_status"),
        sa.CheckConstraint(_CYCLE_STAGE_CHECK, name="ck_watchlist_cycles_stage"),
        sa.ForeignKeyConstraint(
            ["watchlist_id"],
            ["watchlists.id"],
            ondelete="CASCADE",
            name="fk_watchlist_cycles_watchlist",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            ondelete="CASCADE",
            name="fk_watchlist_cycles_client",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            ondelete="SET NULL",
            name="fk_watchlist_cycles_ingestion_run",
        ),
        sa.ForeignKeyConstraint(
            ["index_build_run_id"],
            ["index_build_runs.id"],
            ondelete="SET NULL",
            name="fk_watchlist_cycles_index_run",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_watchlist_cycles_watchlist_id", "watchlist_cycles", ["watchlist_id"])
    op.create_index("ix_watchlist_cycles_client_id", "watchlist_cycles", ["client_id"])
    # Partial unique: at most one in_progress cycle per watchlist (FR-017)
    op.create_index(
        "uq_watchlist_cycles_in_progress",
        "watchlist_cycles",
        ["watchlist_id"],
        unique=True,
        postgresql_where="status = 'in_progress'",
    )

    # ── 2. NEW TABLE: dead_letter ─────────────────────────────────────────────
    op.create_table(
        "dead_letter",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_name", sa.String(48), nullable=False),
        sa.Column("job_key", sa.String(128), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=True),
        sa.Column("args_digest", sa.String(64), nullable=False),
        sa.Column("error_class", sa.String(80), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("first_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "dead_lettered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            ondelete="SET NULL",
            name="fk_dead_letter_client",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dead_letter_client_id", "dead_letter", ["client_id"])
    op.create_index("ix_dead_letter_dead_lettered_at", "dead_letter", ["dead_lettered_at"])
    op.create_index(
        "ix_dead_letter_unresolved",
        "dead_letter",
        ["dead_lettered_at"],
        unique=False,
        postgresql_where="resolved_at IS NULL",
    )

    # ── 3. ALTER: index_build_runs — add watchlist_id + swap partial-unique ──
    op.add_column(
        "index_build_runs",
        sa.Column(
            "watchlist_id",
            sa.BigInteger(),
            sa.ForeignKey("watchlists.id", ondelete="CASCADE", name="fk_index_runs_watchlist"),
            nullable=True,
        ),
    )
    op.create_index("ix_index_build_runs_watchlist_id", "index_build_runs", ["watchlist_id"])
    # Drop old client-wide partial unique; create per-(client,watchlist) guard
    op.drop_index("uq_index_build_runs_client_running", table_name="index_build_runs")
    op.create_index(
        "uq_index_build_runs_client_wl_running",
        "index_build_runs",
        ["client_id", "watchlist_id"],
        unique=True,
        postgresql_where="status = 'running'",
    )

    # ── 4. ALTER: watchlists — add budget_exceeded_policy ────────────────────
    op.add_column(
        "watchlists",
        sa.Column(
            "budget_exceeded_policy",
            sa.String(16),
            nullable=False,
            server_default="continue",
        ),
    )
    op.create_check_constraint("ck_watchlists_budget_policy", "watchlists", _BUDGET_POLICY_CHECK)


def downgrade() -> None:
    # Reverse 4: watchlists
    op.drop_constraint("ck_watchlists_budget_policy", "watchlists", type_="check")
    op.drop_column("watchlists", "budget_exceeded_policy")

    # Reverse 3: index_build_runs
    op.drop_index("uq_index_build_runs_client_wl_running", table_name="index_build_runs")
    op.create_index(
        "uq_index_build_runs_client_running",
        "index_build_runs",
        ["client_id"],
        unique=True,
        postgresql_where="status = 'running'",
    )
    op.drop_index("ix_index_build_runs_watchlist_id", table_name="index_build_runs")
    op.drop_constraint("fk_index_runs_watchlist", "index_build_runs", type_="foreignkey")
    op.drop_column("index_build_runs", "watchlist_id")

    # Reverse 2: dead_letter
    op.drop_index("ix_dead_letter_unresolved", table_name="dead_letter")
    op.drop_index("ix_dead_letter_dead_lettered_at", table_name="dead_letter")
    op.drop_index("ix_dead_letter_client_id", table_name="dead_letter")
    op.drop_table("dead_letter")

    # Reverse 1: watchlist_cycles
    op.drop_index("uq_watchlist_cycles_in_progress", table_name="watchlist_cycles")
    op.drop_index("ix_watchlist_cycles_client_id", table_name="watchlist_cycles")
    op.drop_index("ix_watchlist_cycles_watchlist_id", table_name="watchlist_cycles")
    op.drop_table("watchlist_cycles")
