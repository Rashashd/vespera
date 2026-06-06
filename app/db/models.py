"""SQLAlchemy ORM models owned by the foundation (audit_log lands in the US4 phase)."""

from app.db.base import Base  # noqa: F401  (re-exported so migrations import one place)

# The reserved sentinel actor id for system-initiated events (research.md D1).
SYSTEM_ACTOR_ID = 0

# NOTE: the `audit_log` table and its ORM model are added in the US4 implementation
# phase (tasks T036/T039). This module intentionally only re-exports Base for now so
# the Alembic environment is importable from the start.
