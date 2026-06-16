"""Async SQLAlchemy engine and session factory plus the declarative base."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def create_engine(database_url: str) -> AsyncEngine:
    """Create the async engine (single instance, owned by the lifespan).

    statement_cache_size=0 disables asyncpg's prepared-statement cache so per-transaction RLS
    GUCs stay correct under transaction pooling (PgBouncer-forward; spec 12 R6).
    """
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"statement_cache_size": 0},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to the given engine."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield a session inside a transaction; commit on success, roll back on error."""
    async with factory() as session:
        async with session.begin():
            yield session
