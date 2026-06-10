"""Async caller client for the modelserver inference service (FR-019).

Reuses the shared httpx factory from app/infra/http.py; injects X-Service-Token;
retries on transient errors (5xx / timeout) but never on 4xx.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.infra.http import build_http_client, with_retry

_MAX_BATCH = 128


class ModelserverError(Exception):
    """Raised when the modelserver returns an unexpected error after retries."""


class ModelserverClient:
    """Typed async client for /classify and /embed (FR-019)."""

    def __init__(self, base_url: str, token: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._http: httpx.AsyncClient | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> ModelserverClient:
        return cls(
            base_url=getattr(settings, "modelserver_url", "http://modelserver:8001"),
            token=settings.modelserver_token,
        )

    async def __aenter__(self) -> ModelserverClient:
        self._http = build_http_client()
        self._http.headers["X-Service-Token"] = self._token
        self._http.base_url = httpx.URL(self._base_url)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # Classify
    # ------------------------------------------------------------------

    async def classify(self, texts: list[str]) -> list[dict]:
        """Call POST /classify; returns raw result dicts in input order."""
        if not texts:
            return []
        resp = await self._post_with_retry("/classify", {"texts": texts})
        return resp["results"]

    async def classify_chunked(self, texts: list[str]) -> list[dict]:
        """Chunk large lists into ≤128 batches and concatenate results."""
        out: list[dict] = []
        for i in range(0, len(texts), _MAX_BATCH):
            out.extend(await self.classify(texts[i : i + _MAX_BATCH]))
        return out

    # ------------------------------------------------------------------
    # Embed
    # ------------------------------------------------------------------

    async def embed(self, texts: list[str]) -> list[dict]:
        """Call POST /embed; returns raw result dicts in input order."""
        if not texts:
            return []
        resp = await self._post_with_retry("/embed", {"texts": texts})
        return resp["results"]

    async def embed_chunked(self, texts: list[str]) -> list[dict]:
        """Chunk large lists into ≤128 batches and concatenate results."""
        out: list[dict] = []
        for i in range(0, len(texts), _MAX_BATCH):
            out.extend(await self.embed(texts[i : i + _MAX_BATCH]))
        return out

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @with_retry
    async def _post_with_retry(self, path: str, payload: dict) -> dict:
        assert self._http is not None, "client must be used as an async context manager"
        try:
            resp = self._http.build_request("POST", path, json=payload)
            response = await self._http.send(resp)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise ModelserverError(
                f"modelserver {path} returned {exc.response.status_code}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise exc  # tenacity retries on this
        except Exception as exc:
            raise ModelserverError(f"modelserver {path} failed: {exc}") from exc
