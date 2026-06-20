"""Right-to-erasure: client tombstone status + erased_at (Cluster 3 / B1, Constitution V).

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-20

Erasure purges a client's personal data (rows + vectors + sessions) but retains a minimal client
tombstone (id + name + timestamps) so the relationship/audit trail survives. This migration widens
ck_clients_status to allow the terminal 'erased' state and adds clients.erased_at. Additive (new
nullable column + a CHECK widening); no RLS/grant change.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS_OLD = "status IN ('active', 'suspended')"
_STATUS_NEW = "status IN ('active', 'suspended', 'erased')"


def upgrade() -> None:
    op.add_column("clients", sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint("ck_clients_status", "clients", type_="check")
    op.create_check_constraint("ck_clients_status", "clients", _STATUS_NEW)


def downgrade() -> None:
    op.drop_constraint("ck_clients_status", "clients", type_="check")
    op.create_check_constraint("ck_clients_status", "clients", _STATUS_OLD)
    op.drop_column("clients", "erased_at")
