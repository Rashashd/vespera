"""Async client for the guardrails sidecar /guard endpoint; fail-safe on outage.

Mirrors app/infra/modelserver_client.py: httpx.AsyncClient + tenacity (retry 5xx/timeout/
network only, never 4xx), X-Service-Token auth. On an unreachable/errored sidecar after
retries it raises GuardrailsUnavailable so callers can apply their fail-safe (triage/agent
escalate; intake quarantines).
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.guardrails.schemas import GuardRequest, GuardResponse
from app.infra.http import build_http_client, with_retry


class GuardrailsUnavailable(Exception):
    """Raised when the guardrails sidecar is unreachable/errored after retries (fail-safe)."""


class GuardrailsClient:
    """Typed async client for POST /guard."""

    def __init__(
        self,
        base_url: str,
        token: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._transport = transport  # None → production networking; set for in-process testing
        self._http: httpx.AsyncClient | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> GuardrailsClient:
        return cls(base_url=settings.guardrails_url, token=settings.guardrails_token)

    async def __aenter__(self) -> GuardrailsClient:
        if self._transport is not None:
            self._http = httpx.AsyncClient(
                transport=self._transport,
                base_url=self._base_url,
                headers={"X-Service-Token": self._token},
            )
        else:
            self._http = build_http_client()
            self._http.headers["X-Service-Token"] = self._token
            self._http.base_url = httpx.URL(self._base_url)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    async def guard(
        self, text: str, direction: str, client_id: int, call_site: str
    ) -> GuardResponse:
        """Evaluate one payload; raise GuardrailsUnavailable on any transport/HTTP failure."""
        payload = GuardRequest(
            text=text, direction=direction, client_id=client_id, call_site=call_site
        ).model_dump()
        try:
            data = await self._post_guard(payload)
        except (httpx.HTTPError, OSError) as exc:
            raise GuardrailsUnavailable(f"guardrails sidecar unavailable: {exc}") from exc
        return GuardResponse(**data)

    @with_retry
    async def _post_guard(self, payload: dict) -> dict:
        assert self._http is not None, "client must be used as an async context manager"
        # raise_for_status: 5xx is retryable (with_retry), 4xx is not → propagates to guard().
        response = await self._http.post("/guard", json=payload)
        response.raise_for_status()
        return response.json()
