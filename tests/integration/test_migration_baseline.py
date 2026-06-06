"""Baseline migration test: audit_log + indexes exist on an empty DB (US5 / SC-008)."""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Postgres) with `alembic upgrade head` applied",
)


async def test_audit_log_table_and_indexes_exist():
    """After the baseline migration, audit_log and its indexes are present."""
    from sqlalchemy import inspect

    from app.core.config import Settings
    from app.core.startup import load_secrets_from_vault
    from app.db.base import create_engine

    settings = Settings()
    await load_secrets_from_vault(settings)
    engine = create_engine(settings.database_url)

    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
        assert "audit_log" in tables
        index_names = await conn.run_sync(
            lambda c: {ix["name"] for ix in inspect(c).get_indexes("audit_log")}
        )
    await engine.dispose()

    for expected in (
        "ix_audit_log_actor_id",
        "ix_audit_log_actor_type",
        "ix_audit_log_client_id",
        "ix_audit_log_created_at",
        "ix_audit_log_event_type",
    ):
        assert expected in index_names
