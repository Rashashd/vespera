"""Triage fail-safe: degraded-document/cycle markers + classifier-version attribution.

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-19

Additive columns supporting the triage fail-safe cluster (Constitution III):
- findings.classifier_version: SHA-256 of the classifier artifact that made the call. NULL when
  the classifier was unavailable and the pair was escalated — which distinguishes an outage
  escalation from a low-confidence one (mirrors chunks.embedder_version).
- document_index_state.triage_failed_at / triage_error: durable per-document marker written when
  triage could not run (e.g. an NER outage), so a broken run is detectable and the cycle cannot
  report 'completed' clean.
- watchlist_cycles.degraded_reason: set at consolidation when the cycle's index run produced any
  triage-failed document, so a degraded run is distinguishable from a clean completion.

Purely additive (new nullable columns on existing tables): no RLS or grant changes are needed —
the table-level privileges granted to pantera_app in 0011/0012 already cover new columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Classifier model-version attribution (mirrors chunks.embedder_version).
    op.add_column("findings", sa.Column("classifier_version", sa.String(64), nullable=True))

    # Durable per-document degraded marker: triage could not run for this document.
    op.add_column(
        "document_index_state",
        sa.Column("triage_failed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("document_index_state", sa.Column("triage_error", sa.String(255), nullable=True))

    # Cycle-level degraded annotation (parallels skipped_reason); NULL = clean completion.
    op.add_column("watchlist_cycles", sa.Column("degraded_reason", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("watchlist_cycles", "degraded_reason")
    op.drop_column("document_index_state", "triage_error")
    op.drop_column("document_index_state", "triage_failed_at")
    op.drop_column("findings", "classifier_version")
