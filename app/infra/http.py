"""Shared async HTTP: client factory, tenacity retry helper, per-source semaphores."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

_USER_AGENT = "Pantera/0.1 (pharmacovigilance monitor)"
_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 30.0

# Per-source politeness: at most 3 concurrent requests per adapter.
_SOURCE_SEMAPHORES: dict[str, asyncio.Semaphore] = {}
_SEMAPHORE_CAPACITY = 3


def get_source_semaphore(source_name: str) -> asyncio.Semaphore:
    """Return (creating if needed) a per-source concurrency semaphore (D6)."""
    if source_name not in _SOURCE_SEMAPHORES:
        _SOURCE_SEMAPHORES[source_name] = asyncio.Semaphore(_SEMAPHORE_CAPACITY)
    return _SOURCE_SEMAPHORES[source_name]


def build_http_client(*, ncbi_tool_email: str = "") -> httpx.AsyncClient:
    """Create a configured AsyncClient with platform UA and sensible timeouts."""
    headers = {"User-Agent": _USER_AGENT}
    if ncbi_tool_email:
        headers["X-Tool-Email"] = ncbi_tool_email
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT, write=10.0, pool=5.0),
        headers=headers,
        follow_redirects=True,
    )


def _is_retryable(exc: BaseException) -> bool:
    """Retry timeouts and 5xx responses; never retry 4xx (permanent client errors)."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


def with_retry[T](func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    """Decorator: 3 attempts, exponential backoff (2-10 s), retry only transient errors (D6)."""
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )(func)
