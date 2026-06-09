"""Migration 0005 schema-presence and ensure_manager idempotency tests (spec 4b, T041)."""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Vault + Postgres + Redis)",
)


async def test_migration_schema_columns_present(auth_app):
    """0005 migration: new columns exist in users, clients, and user_watchlist_scope tables."""
    from sqlalchemy import text

    factory = auth_app.state.session_factory
    async with factory() as s:
        user_cols = {
            row[0]
            for row in (
                await s.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns"
                        " WHERE table_name='users'"
                    )
                )
            )
        }
        client_cols = {
            row[0]
            for row in (
                await s.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns"
                        " WHERE table_name='clients'"
                    )
                )
            )
        }
        tables = {
            row[0]
            for row in (
                await s.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables"
                        " WHERE table_schema='public'"
                    )
                )
            )
        }

    assert "user_type" in user_cols
    assert "client_scope" in user_cols
    assert "min_severity" in user_cols
    assert "report_email_regular" in client_cols
    assert "report_email_urgent" in client_cols
    assert "urgent_severity_threshold" in client_cols
    assert "user_watchlist_scope" in tables


async def test_ensure_manager_idempotent(auth_app):
    """ensure_manager called repeatedly does not create duplicate managers (C2/D8)."""
    from sqlalchemy import func, select

    from app.auth.bootstrap import ensure_manager
    from app.auth.models import User
    from app.core.config import Settings

    factory = auth_app.state.session_factory

    async with factory() as s:
        before = (
            await s.scalar(
                select(func.count())
                .select_from(User)
                .where(User.role == "manager", User.is_active.is_(True))
            )
            or 0
        )

    settings = Settings()
    async with factory() as s:
        async with s.begin():
            await ensure_manager(s, settings)

    async with factory() as s:
        after = (
            await s.scalar(
                select(func.count())
                .select_from(User)
                .where(User.role == "manager", User.is_active.is_(True))
            )
            or 0
        )

    # If at least one manager existed before, count must not increase.
    if before >= 1:
        assert after == before
    else:
        # Fresh DB: exactly one manager should now exist.
        assert after == 1


async def test_at_least_one_manager_exists(auth_app):
    """After startup (which calls ensure_manager), at least one active manager exists (D8)."""
    from sqlalchemy import func, select

    from app.auth.models import User

    factory = auth_app.state.session_factory
    async with factory() as s:
        count = (
            await s.scalar(
                select(func.count())
                .select_from(User)
                .where(User.role == "manager", User.is_active.is_(True))
            )
            or 0
        )
    assert count >= 1
