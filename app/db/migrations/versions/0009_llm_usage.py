"""llm_usage table for per-client LLM cost tracking (spec 10 FR-033)

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CALL_SITE_CHECK = "call_site IN ('triage','agent')"


def upgrade() -> None:
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("finding_id", sa.BigInteger(), nullable=True),
        sa.Column("call_site", sa.String(8), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(_CALL_SITE_CHECK, name="ck_llm_usage_call_site"),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"], ondelete="CASCADE", name="fk_llm_usage_client"
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"], ["findings.id"], ondelete="SET NULL", name="fk_llm_usage_finding"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_usage_client_id", "llm_usage", ["client_id"])
    op.create_index("ix_llm_usage_client_created", "llm_usage", ["client_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_client_created", table_name="llm_usage")
    op.drop_index("ix_llm_usage_client_id", table_name="llm_usage")
    op.drop_table("llm_usage")
