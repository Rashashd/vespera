"""Async Redis client factory (TLS via rediss:// handled by the URL)."""

from redis.asyncio import Redis, from_url


async def create_redis(redis_url: str) -> Redis:
    """Create an async Redis client; `rediss://` enables TLS in production."""
    return from_url(redis_url, encoding="utf-8", decode_responses=True)
