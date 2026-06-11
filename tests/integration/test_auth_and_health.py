"""US4 integration tests: auth guards, health/ready endpoints, and readiness gating.

Covers: missing token→401, invalid→403, /health no-auth 200, /ready 503 before
artifacts loaded then 200 with model versions; /classify and /embed gated 503.
"""

from __future__ import annotations

import importlib.util

import pytest
from httpx import ASGITransport, AsyncClient

ADVERSE_TEXT = "patient developed acute liver failure after starting drug X"

# Exercises the standalone modelserver app, which imports onnxruntime at boot (only in the
# `modelserver` uv group). Skip unless that dep is present; CI installs it via --group modelserver.
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        importlib.util.find_spec("onnxruntime") is None,
        reason="requires modelserver runtime deps (onnxruntime); run under the modelserver env",
    ),
]


# ---------------------------------------------------------------------------
# /health — liveness, no auth required
# ---------------------------------------------------------------------------


async def test_health_always_200_no_auth(ms_client):
    resp = await ms_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_health_200_even_with_token(ms_authed):
    resp = await ms_authed.get("/health")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /ready — readiness probe, no auth required
# ---------------------------------------------------------------------------


async def test_ready_200_after_artifacts_loaded(ms_authed):
    resp = await ms_authed.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert "classifier" in body["models"]
    assert "embedder" in body["models"]


async def test_ready_503_before_lifespan():
    """Without running the lifespan, the service is not ready."""
    from modelserver.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/ready")
    assert resp.status_code == 503


async def test_ready_includes_latency_counters(ms_authed):
    # Warm up with a classify call first
    await ms_authed.post("/classify", json={"texts": [ADVERSE_TEXT]})
    resp = await ms_authed.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert "latency_ms" in body
    assert "classify" in body["latency_ms"]
    assert body["latency_ms"]["classify"]["count"] >= 1


# ---------------------------------------------------------------------------
# Auth: missing / wrong token
# ---------------------------------------------------------------------------


async def test_classify_missing_token_401(ms_client):
    resp = await ms_client.post("/classify", json={"texts": [ADVERSE_TEXT]})
    assert resp.status_code == 401


async def test_classify_wrong_token_403(ms_client):
    resp = await ms_client.post(
        "/classify",
        json={"texts": [ADVERSE_TEXT]},
        headers={"X-Service-Token": "bad-token"},
    )
    assert resp.status_code == 403


async def test_embed_missing_token_401(ms_client):
    resp = await ms_client.post("/embed", json={"texts": [ADVERSE_TEXT]})
    assert resp.status_code == 401


async def test_embed_wrong_token_403(ms_client):
    resp = await ms_client.post(
        "/embed",
        json={"texts": [ADVERSE_TEXT]},
        headers={"X-Service-Token": "bad-token"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Readiness gate: /classify and /embed return 503 before load
# ---------------------------------------------------------------------------


async def test_classify_503_before_ready():
    """Classify must 503 when the service has not loaded artifacts."""
    from modelserver.main import create_app

    app = create_app()
    # Manually set service_token so auth passes but ready is still False
    app.state.service_token = "test-service-token"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/classify",
            json={"texts": [ADVERSE_TEXT]},
            headers={"X-Service-Token": "test-service-token"},
        )
    assert resp.status_code == 503


async def test_embed_503_before_ready():
    """Embed must 503 when the service has not loaded artifacts."""
    from modelserver.main import create_app

    app = create_app()
    app.state.service_token = "test-service-token"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/embed",
            json={"texts": [ADVERSE_TEXT]},
            headers={"X-Service-Token": "test-service-token"},
        )
    assert resp.status_code == 503
