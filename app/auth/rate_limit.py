"""Login rate-limit policy (5/min/IP) on a slowapi limiter upgraded to Redis at startup."""

from slowapi import Limiter
from slowapi.util import get_remote_address

# Applied to the login route via decorator (FR-010); the decorating instance enforces the limit.
LOGIN_RATE_LIMIT = "5/minute"

# Single shared limiter; storage starts in-memory and is pointed at Redis in the lifespan so the
# decorated route (bound to this instance at import) enforces against Redis (research D7).
login_limiter = Limiter(key_func=get_remote_address, default_limits=[])


def use_redis_storage(redis_url: str) -> None:
    """Point the login limiter's storage at Redis; call once at startup before serving."""
    from limits.storage import storage_from_string
    from limits.strategies import FixedWindowRateLimiter

    storage = storage_from_string(redis_url)
    login_limiter._storage = storage
    login_limiter._limiter = FixedWindowRateLimiter(storage)
