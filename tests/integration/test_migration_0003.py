"""Migration 0003: tables created, users.client_id reconciled to a real FK (SC-001)."""

import os

import pytest
from sqlalchemy import inspect, text

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack with `alembic upgrade head` applied",
)


async def _engine():
    from app.core.config import Settings
    from app.core.startup import load_secrets_from_vault
    from app.db.base import create_engine

    settings = Settings()
    await load_secrets_from_vault(settings)
    return create_engine(settings.database_url)


async def test_new_tables_and_indexes_exist():
    """The four spec-3 tables and their key unique indexes are present after upgrade."""
    engine = await _engine()
    async with engine.connect() as conn:
        tables = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
        client_ix = await conn.run_sync(
            lambda c: {ix["name"] for ix in inspect(c).get_indexes("clients")}
        )
        wl_ix = await conn.run_sync(
            lambda c: {ix["name"] for ix in inspect(c).get_indexes("watchlists")}
        )
    await engine.dispose()

    assert {"clients", "watchlists", "watchlist_items", "watchlist_budget_usage"} <= tables
    assert "ux_clients_lower_name" in client_ix
    assert {"ix_watchlists_client_id", "ux_watchlists_client_lower_name"} <= wl_ix


async def test_users_client_id_has_fk_to_clients():
    """The reconciled FK users.client_id → clients.id exists and is enforced."""
    engine = await _engine()
    async with engine.connect() as conn:
        fks = await conn.run_sync(lambda c: inspect(c).get_foreign_keys("users"))
    referred = {fk["referred_table"] for fk in fks}
    await engine.dispose()
    assert "clients" in referred


async def test_no_orphaned_users():
    """Every non-NULL users.client_id resolves to a real clients row (SC-001, no orphans).

    staff users have client_id IS NULL (valid in the 4b agency model); only non-NULL
    client_id values need a matching clients row.
    """
    engine = await _engine()
    async with engine.connect() as conn:
        orphans = await conn.scalar(
            text(
                "SELECT count(*) FROM users u "
                "LEFT JOIN clients c ON c.id = u.client_id "
                "WHERE u.client_id IS NOT NULL AND c.id IS NULL"
            )
        )
    await engine.dispose()
    assert orphans == 0


async def test_fk_rejects_unknown_client(auth_app):
    """Inserting a user with a non-existent client_id is rejected by the FK."""
    from sqlalchemy.exc import IntegrityError

    from app.auth.models import User

    factory = auth_app.state.session_factory
    with pytest.raises(IntegrityError):
        async with factory() as s:
            async with s.begin():
                s.add(
                    User(
                        email="orphan@x.com",
                        hashed_password="x",
                        role="reviewer",
                        client_id=999_999_999,
                        is_active=True,
                        is_superuser=False,
                        is_verified=True,
                    )
                )


def test_migration_is_reversible():
    """The 0003 migration defines a downgrade chained to 0002 (clean reversibility)."""
    import importlib

    mod = importlib.import_module("app.db.migrations.versions.0003_clients_watchlists")
    assert mod.down_revision == "0002"
    assert callable(mod.downgrade)
