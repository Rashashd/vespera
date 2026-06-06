"""Fail-fast startup tests: the app refuses to boot when dependencies are unavailable."""

import os

import pytest

from app.core.config import Settings
from app.core.startup import check_database, check_redis, load_secrets_from_vault


async def test_refuses_when_vault_unreachable():
    """load_secrets_from_vault raises a clear error when Vault cannot be reached (FR-002)."""
    settings = Settings(vault_addr="http://127.0.0.1:1", vault_token="bad")
    with pytest.raises(RuntimeError):
        await load_secrets_from_vault(settings)


@pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Postgres + Redis)",
)
async def test_database_check_raises_when_unreachable():
    """check_database raises when the database URL is unreachable (FR-004)."""
    from sqlalchemy.exc import SQLAlchemyError

    from app.db.base import create_engine

    engine = create_engine("postgresql+asyncpg://x:x@127.0.0.1:1/none")
    with pytest.raises((SQLAlchemyError, OSError)):
        await check_database(engine)
    await engine.dispose()


@pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Redis)",
)
async def test_redis_check_raises_when_unreachable():
    """check_redis raises when the cache is unreachable (FR-004)."""
    from redis.exceptions import RedisError

    from app.infra.redis import create_redis

    redis = await create_redis("redis://127.0.0.1:1/0")
    with pytest.raises((RedisError, OSError)):
        await check_redis(redis)
    await redis.aclose()
