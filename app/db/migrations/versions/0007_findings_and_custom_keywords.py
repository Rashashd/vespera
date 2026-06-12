"""findings table + clients.custom_severity_keywords (spec 8, migration 0007)

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BUCKET_CHECK = "bucket IN ('irrelevant','positive','minor','urgent','emergency')"
_STATUS_CHECK = "status IN ('pending_expedited','pending_batch','classified')"
_RESOLUTION_CHECK = "resolution_path IN ('model','llm','escalated')"


def upgrade() -> None:
    op.create_table(
        "findings",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("drug", sa.String(512), nullable=False),
        sa.Column("reaction", sa.String(512), nullable=False),
        sa.Column("bucket", sa.String(16), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("model_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("resolution_path", sa.String(12), nullable=False),
        sa.Column("corroboration_sources", postgresql.JSONB(), nullable=True),
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
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(_BUCKET_CHECK, name="ck_findings_bucket"),
        sa.CheckConstraint(_STATUS_CHECK, name="ck_findings_status"),
        sa.CheckConstraint(_RESOLUTION_CHECK, name="ck_findings_resolution_path"),
    )

    op.create_index(
        "ux_findings_doc_drug_reaction",
        "findings",
        ["document_id", "drug", "reaction"],
        unique=True,
    )
    op.create_index("ix_findings_client_id", "findings", ["client_id"], unique=False)
    op.create_index("ix_findings_status", "findings", ["status"], unique=False)
    op.create_index("ix_findings_client_bucket", "findings", ["client_id", "bucket"], unique=False)

    op.add_column(
        "clients",
        sa.Column(
            "custom_severity_keywords",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("clients", "custom_severity_keywords")
    op.drop_index("ix_findings_client_bucket", table_name="findings")
    op.drop_index("ix_findings_status", table_name="findings")
    op.drop_index("ix_findings_client_id", table_name="findings")
    op.drop_index("ux_findings_doc_drug_reaction", table_name="findings")
    op.drop_table("findings")
