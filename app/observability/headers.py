"""Rate-limit capability (now) and security-response headers (added in US5)."""

from slowapi import Limiter
from slowapi.util import get_remote_address


def build_limiter(redis_url: str) -> Limiter:
    """Build a Redis-backed slowapi limiter; no policy is applied here (FR-011)."""
    return Limiter(key_func=get_remote_address, storage_uri=redis_url)
