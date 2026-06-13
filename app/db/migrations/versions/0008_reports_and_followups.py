"""reports, report_findings, report_followups; widen findings.status + watchlists.cadence (spec 9)

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FINDINGS_STATUS_NEW = (
    "status IN ('pending_expedited','pending_batch','classified',"
    "'processing','reported','discarded')"
)
_FINDINGS_STATUS_OLD = "status IN ('pending_expedited','pending_batch','classified')"

_CADENCE_NEW = "cadence IN ('daily','weekly','biweekly','monthly')"
_CADENCE_OLD = "cadence IN ('daily', 'weekly', 'monthly')"

_REPORT_TYPE_CHECK = "report_type IN ('expedited','batch')"
_REPORT_STATUS_CHECK = (
    "status IN ('drafted','under_review','approved','rejected','discarded','needs_manual_revision')"
)
_RF_STATE_CHECK = "state IN ('included','dropped','discarded')"
_FOLLOWUP_STATUS_CHECK = "status IN ('generated','sent','failed')"


def upgrade() -> None:
    # ── 1. Widen findings.status CHECK ──────────────────────────────────────────
    op.drop_constraint("ck_findings_status", "findings", type_="check")
    op.create_check_constraint("ck_findings_status", "findings", _FINDINGS_STATUS_NEW)

    # ── 2. Widen watchlists.cadence CHECK ───────────────────────────────────────
    op.drop_constraint("ck_watchlists_cadence", "watchlists", type_="check")
    op.create_check_constraint("ck_watchlists_cadence", "watchlists", _CADENCE_NEW)

    # ── 3. Create reports ────────────────────────────────────────────────────────
    op.create_table(
        "reports",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("report_type", sa.String(12), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column(
            "structured_fields",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("draft_body", sa.Text(), nullable=True),
        sa.Column("corroboration_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("corroboration_sources", postgresql.JSONB(), nullable=True),
        sa.Column("revision_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "reviewer_comments",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("sla_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("watchlist_id", sa.BigInteger(), nullable=True),
        sa.Column("cycle_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cycle_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["watchlist_id"], ["watchlists.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(_REPORT_TYPE_CHECK, name="ck_reports_type"),
        sa.CheckConstraint(_REPORT_STATUS_CHECK, name="ck_reports_status"),
    )
    op.create_index("ix_reports_client_id", "reports", ["client_id"], unique=False)
    op.create_index("ix_reports_status", "reports", ["status"], unique=False)
    op.create_index("ix_reports_client_status", "reports", ["client_id", "status"], unique=False)
    # Partial unique: one active batch report per watchlist per cycle (SC-008)
    op.create_index(
        "ux_reports_batch_cycle",
        "reports",
        ["watchlist_id", "cycle_period_start"],
        unique=True,
        postgresql_where=sa.text(
            "report_type = 'batch' AND status NOT IN ('approved','discarded')"
        ),
    )

    # ── 4. Create report_findings ────────────────────────────────────────────────
    op.create_table(
        "report_findings",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("report_id", sa.BigInteger(), nullable=False),
        sa.Column("finding_id", sa.BigInteger(), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        # Denormalized so the partial unique on (finding_id) works without a subquery.
        sa.Column("report_type", sa.String(12), nullable=False),
        sa.Column("state", sa.String(12), nullable=False, server_default="included"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(_RF_STATE_CHECK, name="ck_report_findings_state"),
        sa.CheckConstraint(_REPORT_TYPE_CHECK, name="ck_report_findings_type"),
    )
    op.create_index(
        "ux_report_findings_unique",
        "report_findings",
        ["report_id", "finding_id"],
        unique=True,
    )
    op.create_index(
        "ix_report_findings_finding_id",
        "report_findings",
        ["finding_id"],
        unique=False,
    )
    # Partial unique: one active expedited report per finding (FR-030)
    op.create_index(
        "ux_report_findings_active_expedited",
        "report_findings",
        ["finding_id"],
        unique=True,
        postgresql_where=sa.text("report_type = 'expedited' AND state != 'discarded'"),
    )

    # ── 5. Create report_followups ────────────────────────────────────────────────
    op.create_table(
        "report_followups",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("finding_id", sa.BigInteger(), nullable=False),
        sa.Column("report_id", sa.BigInteger(), nullable=True),
        sa.Column("template_ref", sa.String(64), nullable=False),
        sa.Column("cover_message", sa.Text(), nullable=False),
        sa.Column("recipient_kind", sa.String(8), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="generated"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(_FOLLOWUP_STATUS_CHECK, name="ck_report_followups_status"),
    )
    # Idempotent: one follow-up per emergency finding
    op.create_index(
        "ux_report_followups_finding",
        "report_followups",
        ["finding_id"],
        unique=True,
    )


def downgrade() -> None:
    # ── 5. Drop report_followups ─────────────────────────────────────────────────
    op.drop_index("ux_report_followups_finding", table_name="report_followups")
    op.drop_table("report_followups")

    # ── 4. Drop report_findings ───────────────────────────────────────────────────
    op.drop_index("ux_report_findings_active_expedited", table_name="report_findings")
    op.drop_index("ix_report_findings_finding_id", table_name="report_findings")
    op.drop_index("ux_report_findings_unique", table_name="report_findings")
    op.drop_table("report_findings")

    # ── 3. Drop reports ───────────────────────────────────────────────────────────
    op.drop_index("ux_reports_batch_cycle", table_name="reports")
    op.drop_index("ix_reports_client_status", table_name="reports")
    op.drop_index("ix_reports_status", table_name="reports")
    op.drop_index("ix_reports_client_id", table_name="reports")
    op.drop_table("reports")

    # ── 2. Restore watchlists.cadence CHECK ──────────────────────────────────────
    op.drop_constraint("ck_watchlists_cadence", "watchlists", type_="check")
    op.create_check_constraint("ck_watchlists_cadence", "watchlists", _CADENCE_OLD)

    # ── 1. Restore findings.status CHECK ─────────────────────────────────────────
    op.drop_constraint("ck_findings_status", "findings", type_="check")
    op.create_check_constraint("ck_findings_status", "findings", _FINDINGS_STATUS_OLD)
