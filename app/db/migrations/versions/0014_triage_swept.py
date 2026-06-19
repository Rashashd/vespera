"""Triage staleness sweep: record that triage RAN (triaged_at) for noise-free sweeping.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-19

Adds document_index_state.triaged_at — set when triage RAN for a document (regardless of whether
it produced findings). Lets the staleness sweep distinguish a legitimately-zero-finding document
(triaged, nothing found) from one that was never triaged, so the sweep only re-triages documents
that genuinely slipped through (Constitution III backstop) instead of re-triaging every clean
document forever. Additive nullable column — no RLS/grant change needed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_index_state",
        sa.Column("triaged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_index_state", "triaged_at")
