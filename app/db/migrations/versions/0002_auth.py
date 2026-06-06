"""auth: users table + audit_log.actor_user_id

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=1024), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
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
        # Two-role constraint mirrors the Role enum (FR-004, data-model.md).
        sa.CheckConstraint("role IN ('admin', 'reviewer')", name="ck_users_role"),
    )
    # Global, case-insensitive-by-normalization unique email (FR-007, research D12).
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_client_id", "users", ["client_id"])

    # Human-actor referential link on the audit log (research D5); nullable, sentinel 0 unlinked.
    op.add_column(
        "audit_log",
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_audit_log_actor_user_id_users",
        "audit_log",
        "users",
        ["actor_user_id"],
        ["id"],
    )
    op.create_index("ix_audit_log_actor_user_id", "audit_log", ["actor_user_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_actor_user_id", table_name="audit_log")
    op.drop_constraint("fk_audit_log_actor_user_id_users", "audit_log", type_="foreignkey")
    op.drop_column("audit_log", "actor_user_id")
    op.drop_index("ix_users_client_id", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
