"""Shared FastAPI dependency providers backed by lifespan-owned singletons."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings


def get_settings_dep(request: Request) -> Settings:
    """Return the loaded Settings singleton."""
    return request.app.state.settings


def get_redis(request: Request):
    """Return the Redis client singleton."""
    return request.app.state.redis


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a transactional DB session from the lifespan-owned session factory."""
    factory = request.app.state.session_factory
    async with factory() as session:
        async with session.begin():
            yield session
