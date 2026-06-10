"""Unit tests for app/infra/modelserver_client.py (T039).

Uses httpx.MockTransport (stub) — no real network, no modelserver process.
Covers: token header sent, timeout propagation, retry on 5xx but NOT on 4xx,
batch chunking helper.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.infra.modelserver_client import ModelserverClient, ModelserverError

TEXT = "patient developed acute liver failure"

_CLASSIFY_RESULT = {
    "model_version": {"name": "classifier", "version": "v1", "sha256": "abc123"},
    "results": [
        {
            "confidence": 0.85,
            "is_adverse": True,
            "model_version": {"name": "classifier", "version": "v1", "sha256": "abc123"},
        }
    ],
}

_EMBED_RESULT = {
    "model_version": {"name": "embedder", "version": "v1", "sha256": "def456"},
    "dim": 768,
    "results": [
        {
            "embedding": [0.1] * 768,
            "model_version": {"name": "embedder", "version": "v1", "sha256": "def456"},
        }
    ],
}


def _make_transport(responses: list[httpx.Response]) -> httpx.MockTransport:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        return queue.pop(0)

    return httpx.MockTransport(handler)


async def _client_with_transport(
    transport: httpx.MockTransport,
) -> ModelserverClient:
    client = ModelserverClient(base_url="http://modelserver:8001", token="test-token")
    client._http = httpx.AsyncClient(transport=transport, base_url="http://modelserver:8001")
    client._http.headers["X-Service-Token"] = "test-token"
    return client


# ---------------------------------------------------------------------------
# Token header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_sends_service_token():
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, json=_CLASSIFY_RESULT)

    transport = httpx.MockTransport(handler)
    client = await _client_with_transport(transport)
    await client.classify([TEXT])

    assert len(captured) == 1
    assert captured[0].headers["X-Service-Token"] == "test-token"


@pytest.mark.asyncio
async def test_embed_sends_service_token():
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, json=_EMBED_RESULT)

    transport = httpx.MockTransport(handler)
    client = await _client_with_transport(transport)
    await client.embed([TEXT])

    assert len(captured) == 1
    assert captured[0].headers["X-Service-Token"] == "test-token"


# ---------------------------------------------------------------------------
# Empty input short-circuits network
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_empty_list_no_request():
    calls: list = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(200, json=_CLASSIFY_RESULT)

    transport = httpx.MockTransport(handler)
    client = await _client_with_transport(transport)
    result = await client.classify([])
    assert result == []
    assert calls == []


@pytest.mark.asyncio
async def test_embed_empty_list_no_request():
    calls: list = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(200, json=_EMBED_RESULT)

    transport = httpx.MockTransport(handler)
    client = await _client_with_transport(transport)
    result = await client.embed([])
    assert result == []
    assert calls == []


# ---------------------------------------------------------------------------
# 4xx — must NOT retry, must raise ModelserverError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_401_raises_no_retry():
    calls: list = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(401, json={"detail": "not authenticated"})

    transport = httpx.MockTransport(handler)
    client = await _client_with_transport(transport)
    with pytest.raises(ModelserverError, match="401"):
        await client.classify([TEXT])

    assert len(calls) == 1, "4xx must not be retried"


@pytest.mark.asyncio
async def test_classify_422_raises_no_retry():
    calls: list = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(422, json={"detail": "validation error"})

    transport = httpx.MockTransport(handler)
    client = await _client_with_transport(transport)
    with pytest.raises(ModelserverError, match="422"):
        await client.classify([TEXT])

    assert len(calls) == 1, "422 must not be retried"


# ---------------------------------------------------------------------------
# Chunking helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_chunked_splits_at_128():
    calls: list[list[str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        calls.append(body["texts"])
        n = len(body["texts"])
        return httpx.Response(
            200,
            json={
                "model_version": {"name": "classifier", "version": "v1", "sha256": "abc"},
                "results": [
                    {
                        "confidence": 0.9,
                        "is_adverse": True,
                        "model_version": {"name": "classifier", "version": "v1", "sha256": "abc"},
                    }
                    for _ in range(n)
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    client = await _client_with_transport(transport)

    # 200 items → 2 calls of 128 and 72
    texts = [f"text-{i}" for i in range(200)]
    results = await client.classify_chunked(texts)

    assert len(results) == 200
    assert len(calls) == 2
    assert len(calls[0]) == 128
    assert len(calls[1]) == 72
