"""Rate-limit capability and security-response headers for the API."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from slowapi import Limiter
from slowapi.util import get_remote_address

# Baseline security headers applied to every response (FR-010).
_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'",  # revisited when the SPA lands
}


def build_limiter(redis_url: str) -> Limiter:
    """Build a Redis-backed slowapi limiter; no policy is applied here (FR-011)."""
    return Limiter(key_func=get_remote_address, storage_uri=redis_url)


def add_security_headers(app: FastAPI) -> None:
    """Attach middleware that sets the baseline security headers on every response."""

    @app.middleware("http")
    async def _set_security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response
