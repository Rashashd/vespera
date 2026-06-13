"""Alembic environment — runs async migrations using the Vault-loaded database URL."""

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# Import models so their tables register on Base.metadata.
from app.audit import models as audit_models  # noqa: F401  (registers the audit_log table)
from app.auth import models as auth_models  # noqa: F401  (registers the users table)
from app.clients import models as clients_models  # noqa: F401  (registers spec-3 tables)
from app.core.config import get_settings
from app.core.startup import load_secrets_from_vault
from app.db.base import Base
from app.embedding import models as embedding_models  # noqa: F401  (registers spec-6 tables)
from app.reports import models as reports_models  # noqa: F401  (registers spec-9 tables)
from app.triage import models as triage_models  # noqa: F401  (registers spec-8 tables)

target_metadata = Base.metadata


def _database_url() -> str:
    """Resolve the database URL from settings, loading secrets from Vault first."""
    settings = get_settings()
    asyncio.run(load_secrets_from_vault(settings))
    return settings.database_url


def _run_sync_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations(url: str) -> None:
    engine = create_async_engine(url, pool_pre_ping=True)
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync_migrations)
    await engine.dispose()


def run_migrations_offline() -> None:
    """Emit SQL without a live connection."""
    context.configure(url=_database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live async connection."""
    asyncio.run(_run_async_migrations(_database_url()))


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
