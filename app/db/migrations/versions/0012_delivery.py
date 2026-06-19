"""Report delivery: widen report status, delivery/SLA columns, delivery_attempt + RLS, SFTP dest.

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-17

Adds the delivery lifecycle (sent/delivered/delivery_failed) to reports, per-channel
delivery_attempt tracking (RLS-policied like every client-scoped table — Constitution V),
and SFTP destination metadata on clients (the SFTP credential lives in n8n, not here — D7).
Re-grants table/sequence privileges to the least-privilege pantera_app role because 0011's
blanket grant predates the new table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APP_ROLE = "pantera_app"

_STATUS_OLD = (
    "status IN ('drafted','under_review','approved','rejected',"
    "'discarded','needs_manual_revision')"
)
_STATUS_NEW = (
    "status IN ('drafted','under_review','approved','rejected',"
    "'discarded','needs_manual_revision','sent','delivered','delivery_failed')"
)

# Mirror 0011_rls_policies: staff/system see all rows; clients scope to their GUC client id.
_RLS_PREDICATE = (
    "current_setting('app.is_staff', true) = 'on' "
    "OR client_id = NULLIF(current_setting('app.current_client_id', true), '')::bigint"
)


def upgrade() -> None:
    # ── 1. Widen reports.status CHECK (drop + recreate, per the 0008/0010 pattern) ──────────
    op.drop_constraint("ck_reports_status", "reports", type_="check")
    op.create_check_constraint("ck_reports_status", "reports", _STATUS_NEW)

    # ── 2. reports: delivery lifecycle timestamps + SLA escalation tracking ─────────────────
    op.add_column("reports", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reports", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "reports", sa.Column("delivery_failed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("reports", sa.Column("delivery_error", sa.Text(), nullable=True))
    op.add_column(
        "reports",
        sa.Column("sla_escalation_tier", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "reports", sa.Column("sla_escalated_at", sa.DateTime(timezone=True), nullable=True)
    )

    # ── 3. clients: SFTP destination metadata (credential lives in n8n — D7) ────────────────
    op.add_column(
        "clients",
        sa.Column("sftp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("clients", sa.Column("sftp_host", sa.String(255), nullable=True))
    op.add_column("clients", sa.Column("sftp_path", sa.String(512), nullable=True))
    op.add_column("clients", sa.Column("sftp_username", sa.String(255), nullable=True))

    # ── 4. delivery_attempt: one row per (report, channel); report status is derived ────────
    op.create_table(
        "delivery_attempt",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("report_id", sa.BigInteger(), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("channel", sa.String(8), nullable=False),
        sa.Column("recipient_kind", sa.String(8), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "dispatched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("channel IN ('email','sftp')", name="ck_delivery_attempt_channel"),
        sa.CheckConstraint(
            "status IN ('pending','delivered','failed')", name="ck_delivery_attempt_status"
        ),
        sa.ForeignKeyConstraint(
            ["report_id"], ["reports.id"], ondelete="CASCADE", name="fk_delivery_attempt_report"
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"], ondelete="CASCADE", name="fk_delivery_attempt_client"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_delivery_attempt_report_id", "delivery_attempt", ["report_id"])
    op.create_index("ix_delivery_attempt_client_id", "delivery_attempt", ["client_id"])
    op.create_index(
        "ux_delivery_attempt_report_channel",
        "delivery_attempt",
        ["report_id", "channel"],
        unique=True,
    )

    # ── 5. RLS on delivery_attempt (Constitution V) + re-grant to the least-priv role ───────
    op.execute("ALTER TABLE delivery_attempt ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE delivery_attempt FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON delivery_attempt "
        f"USING ({_RLS_PREDICATE}) WITH CHECK ({_RLS_PREDICATE})"
    )
    # The 0011 blanket grant predates this table/sequence; re-run the idempotent ALL grants so
    # the runtime role can read/write the new objects (guarded — the role is bootstrap-managed).
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_APP_ROLE}') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {_APP_ROLE};
                GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {_APP_ROLE};
            END IF;
        END
        $$;
        """)


def downgrade() -> None:
    op.drop_table("delivery_attempt")  # drops its indexes + RLS policy

    op.drop_column("clients", "sftp_username")
    op.drop_column("clients", "sftp_path")
    op.drop_column("clients", "sftp_host")
    op.drop_column("clients", "sftp_enabled")

    op.drop_column("reports", "sla_escalated_at")
    op.drop_column("reports", "sla_escalation_tier")
    op.drop_column("reports", "delivery_error")
    op.drop_column("reports", "delivery_failed_at")
    op.drop_column("reports", "delivered_at")
    op.drop_column("reports", "sent_at")

    op.drop_constraint("ck_reports_status", "reports", type_="check")
    op.create_check_constraint("ck_reports_status", "reports", _STATUS_OLD)
