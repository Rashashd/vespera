"""Async httpx client that POSTs render+route requests to the n8n notification/SFTP layer."""

from __future__ import annotations

import httpx
import structlog
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import Settings

_log = structlog.get_logger(__name__)


class N8nDeliveryError(Exception):
    """The n8n routing layer was unreachable or rejected the request (PII-free message)."""


def _retryable(exc: BaseException) -> bool:
    """Retry transient transport errors and 5xx; never retry a 4xx (config/client error)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError))


class N8nClient:
    """Posts delivery + notification payloads to the configured n8n webhook (FR-002/003)."""

    def __init__(self, webhook_url: str, *, timeout: float = 30.0) -> None:
        self._webhook_url = webhook_url
        self._timeout = timeout

    @classmethod
    def from_settings(cls, settings: Settings) -> N8nClient:
        """Build the client from the (optional) configured webhook URL."""
        return cls(settings.n8n_webhook_url)

    @property
    def configured(self) -> bool:
        """Whether a routing webhook is configured (delivery holds/degrades when not)."""
        return bool(self._webhook_url)

    @retry(
        retry=retry_if_exception(_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _post(self, payload: dict) -> None:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(self._webhook_url, json=payload)
            resp.raise_for_status()

    async def send(self, payload: dict) -> None:
        """POST one delivery/notification payload; raise N8nDeliveryError on failure.

        Retries transient/5xx up to 3 attempts (never 4xx). The raised message is PII-free
        (status code / exception class only) so it is safe to persist on the attempt row.
        """
        if not self._webhook_url:
            raise N8nDeliveryError("n8n_webhook_url is not configured")
        try:
            await self._post(payload)
        except httpx.HTTPStatusError as exc:
            raise N8nDeliveryError(f"n8n returned HTTP {exc.response.status_code}") from exc
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise N8nDeliveryError(f"n8n transport error: {type(exc).__name__}") from exc
