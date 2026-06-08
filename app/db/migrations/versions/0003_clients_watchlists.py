"""clients & watchlists: four tables + reconcile users.client_id into a real FK

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Default bootstrap tenant id (matches Settings.bootstrap_admin_client_id).
BOOTSTRAP_CLIENT_ID = 1


def upgrade() -> None:
    # --- clients ----------------------------------------------------------------
    op.create_table(
        "clients",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="ck_clients_status"),
    )
    op.create_index("ux_clients_lower_name", "clients", [sa.text("lower(name)")], unique=True)

    # --- watchlists -------------------------------------------------------------
    op.create_table(
        "watchlists",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "client_id",
            sa.BigInteger(),
            sa.ForeignKey("clients.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("cadence", sa.String(length=16), nullable=False, server_default="weekly"),
        sa.Column(
            "severity_threshold",
            sa.String(length=20),
            nullable=False,
            server_default="serious",
        ),
        sa.Column("budget_amount", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "cadence IN ('daily', 'weekly', 'monthly')", name="ck_watchlists_cadence"
        ),
        sa.CheckConstraint(
            "severity_threshold IN ('non-serious', 'serious', 'life-threatening')",
            name="ck_watchlists_severity",
        ),
        sa.CheckConstraint("budget_amount >= 0", name="ck_watchlists_budget_nonneg"),
    )
    op.create_index("ix_watchlists_client_id", "watchlists", ["client_id"])
    op.create_index(
        "ux_watchlists_client_lower_name",
        "watchlists",
        ["client_id", sa.text("lower(name)")],
        unique=True,
    )

    # --- watchlist_items --------------------------------------------------------
    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "watchlist_id",
            sa.BigInteger(),
            sa.ForeignKey("watchlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("item_type", sa.String(length=16), nullable=False),
        sa.Column("value", sa.String(length=512), nullable=False),
        sa.Column("normalized_value", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "item_type IN ('drug', 'mesh', 'keyword')", name="ck_watchlist_items_type"
        ),
    )
    op.create_index("ix_watchlist_items_watchlist_id", "watchlist_items", ["watchlist_id"])
    op.create_index("ix_watchlist_items_client_id", "watchlist_items", ["client_id"])
    op.create_index(
        "ux_watchlist_items_unique",
        "watchlist_items",
        ["watchlist_id", "item_type", "normalized_value"],
        unique=True,
    )

    # --- watchlist_budget_usage -------------------------------------------------
    op.create_table(
        "watchlist_budget_usage",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "watchlist_id",
            sa.BigInteger(),
            sa.ForeignKey("watchlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=4), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount >= 0", name="ck_watchlist_budget_usage_nonneg"),
    )
    op.create_index(
        "ix_watchlist_budget_usage_watchlist_id", "watchlist_budget_usage", ["watchlist_id"]
    )
    op.create_index("ix_watchlist_budget_usage_client_id", "watchlist_budget_usage", ["client_id"])
    op.create_index(
        "ux_watchlist_budget_usage_period",
        "watchlist_budget_usage",
        ["watchlist_id", "period_start"],
        unique=True,
    )

    # --- reconcile existing users.client_id into real client rows (research D5) -
    # Back-fill a client for every distinct pre-existing client_id (no orphans, SC-001).
    op.execute("""
        INSERT INTO clients (id, name, status, created_at, updated_at)
        SELECT DISTINCT u.client_id, 'Client ' || u.client_id, 'active', now(), now()
        FROM users u
        WHERE NOT EXISTS (SELECT 1 FROM clients c WHERE c.id = u.client_id)
        """)
    # Ensure the bootstrap tenant exists even if no users were present yet.
    op.execute(f"""
        INSERT INTO clients (id, name, status, created_at, updated_at)
        SELECT {BOOTSTRAP_CLIENT_ID}, 'Client {BOOTSTRAP_CLIENT_ID}', 'active', now(), now()
        WHERE NOT EXISTS (SELECT 1 FROM clients c WHERE c.id = {BOOTSTRAP_CLIENT_ID})
        """)
    # Fix the identity sequence so a future auto-id never collides with a back-filled id.
    op.execute(
        "SELECT setval("
        "pg_get_serial_sequence('clients', 'id'), "
        "(SELECT COALESCE(MAX(id), 1) FROM clients))"
    )
    # Now the FK can be enforced safely.
    op.create_foreign_key("fk_users_client_id_clients", "users", "clients", ["client_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_users_client_id_clients", "users", type_="foreignkey")
    op.drop_table("watchlist_budget_usage")
    op.drop_table("watchlist_items")
    op.drop_index("ux_watchlists_client_lower_name", table_name="watchlists")
    op.drop_index("ix_watchlists_client_id", table_name="watchlists")
    op.drop_table("watchlists")
    op.drop_index("ux_clients_lower_name", table_name="clients")
    op.drop_table("clients")
