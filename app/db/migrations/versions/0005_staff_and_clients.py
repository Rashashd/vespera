"""staff & clients: agency model — user_type, nullable client_id, user_watchlist_scope

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_CHECK_NEW = "role IN ('manager','admin','reviewer','client_user')"
_ROLE_CHECK_OLD = "role IN ('admin','reviewer')"
_TYPE_CLIENT_CHECK = (
    "(user_type='staff' AND client_id IS NULL) OR " "(user_type='client' AND client_id IS NOT NULL)"
)
_CLIENT_SCOPE_CHECK = "client_scope IS NULL OR client_scope IN ('full','scoped')"
_MIN_SEVERITY_CHECK = (
    "min_severity IS NULL OR " "min_severity IN ('non-serious','serious','life-threatening')"
)
_URGENT_THRESHOLD_CHECK = (
    "urgent_severity_threshold IN ('non-serious','serious','life-threatening')"
)


def upgrade() -> None:
    # --- SCHEMA: users —————————————————————————————————————————————
    # Drop the old 2-role CHECK; recreate with 4 roles.
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint("ck_users_role", "users", _ROLE_CHECK_NEW)

    # Drop the old NOT NULL FK (replaced below as nullable).
    op.drop_constraint("fk_users_client_id_clients", "users", type_="foreignkey")

    # Add new columns to users.
    op.add_column(
        "users", sa.Column("user_type", sa.String(8), nullable=False, server_default="staff")
    )
    op.add_column("users", sa.Column("client_scope", sa.String(8), nullable=True))
    op.add_column("users", sa.Column("min_severity", sa.String(20), nullable=True))

    # Make client_id nullable and re-add the FK.
    op.alter_column("users", "client_id", existing_type=sa.BigInteger(), nullable=True)
    op.create_foreign_key("fk_users_client_id_clients", "users", "clients", ["client_id"], ["id"])

    # --- DATA RESET (dev: wipe users + their FK-dependent rows; preserve docs/watchlists) ——
    # Must run BEFORE the ck_users_type_client constraint: legacy rows have user_type='staff'
    # (server_default) but client_id IS NOT NULL, which would violate the new constraint.
    # Order: most-dependent FK first. audit_log.actor_user_id is nullable; NULL before delete.
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM ingestion_run_sources"))
    conn.execute(sa.text("DELETE FROM ingestion_runs"))
    conn.execute(
        sa.text("UPDATE audit_log SET actor_user_id = NULL WHERE actor_user_id IS NOT NULL")
    )
    conn.execute(sa.text("DELETE FROM users"))

    # Add integrity CHECKs (safe now that the pre-agency users are gone).
    op.create_check_constraint("ck_users_type_client", "users", _TYPE_CLIENT_CHECK)
    op.create_check_constraint("ck_users_client_scope", "users", _CLIENT_SCOPE_CHECK)
    op.create_check_constraint("ck_users_min_severity", "users", _MIN_SEVERITY_CHECK)

    # --- SCHEMA: clients ————————————————————————————————————————————
    op.add_column("clients", sa.Column("report_email_regular", sa.String(320), nullable=True))
    op.add_column("clients", sa.Column("report_email_urgent", sa.String(320), nullable=True))
    op.add_column(
        "clients",
        sa.Column(
            "urgent_severity_threshold",
            sa.String(20),
            nullable=False,
            server_default="life-threatening",
        ),
    )
    op.create_check_constraint("ck_clients_urgent_threshold", "clients", _URGENT_THRESHOLD_CHECK)

    # --- SCHEMA: user_watchlist_scope ——————————————————————————————
    op.create_table(
        "user_watchlist_scope",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
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
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ux_user_watchlist_scope", "user_watchlist_scope", ["user_id", "watchlist_id"], unique=True
    )
    op.create_index("ix_user_watchlist_scope_user_id", "user_watchlist_scope", ["user_id"])
    op.create_index("ix_user_watchlist_scope_client_id", "user_watchlist_scope", ["client_id"])


def downgrade() -> None:
    # Restore schema to pre-0005 state (data reset is one-way, documented).
    op.drop_table("user_watchlist_scope")

    op.drop_constraint("ck_clients_urgent_threshold", "clients", type_="check")
    op.drop_column("clients", "urgent_severity_threshold")
    op.drop_column("clients", "report_email_urgent")
    op.drop_column("clients", "report_email_regular")

    op.drop_constraint("ck_users_min_severity", "users", type_="check")
    op.drop_constraint("ck_users_client_scope", "users", type_="check")
    op.drop_constraint("ck_users_type_client", "users", type_="check")

    op.drop_constraint("fk_users_client_id_clients", "users", type_="foreignkey")
    op.alter_column("users", "client_id", existing_type=sa.BigInteger(), nullable=False)
    op.create_foreign_key("fk_users_client_id_clients", "users", "clients", ["client_id"], ["id"])

    op.drop_column("users", "min_severity")
    op.drop_column("users", "client_scope")
    op.drop_column("users", "user_type")

    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint("ck_users_role", "users", _ROLE_CHECK_OLD)
