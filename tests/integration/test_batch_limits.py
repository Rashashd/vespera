"""Integration tests for batch-size limits, cold-start readiness, and truncation path (T041).

Covers: >128 items → 422, exactly 128 → 200, 0 items → 200 with empty results,
over-long text truncation end-to-end through /classify and /embed.
"""

from __future__ import annotations

import importlib.util

import pytest

# Exercises the standalone modelserver app, which imports onnxruntime at boot (only in the
# `modelserver` uv group). Skip unless that dep is present; CI installs it via --group modelserver.
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        importlib.util.find_spec("onnxruntime") is None,
        reason="requires modelserver runtime deps (onnxruntime); run under the modelserver env",
    ),
]

ADVERSE = "patient developed acute liver failure"


# ---------------------------------------------------------------------------
# Batch-size limits
# ---------------------------------------------------------------------------


async def test_classify_128_items_accepted(ms_authed):
    texts = [ADVERSE] * 128
    resp = await ms_authed.post("/classify", json={"texts": texts})
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 128


async def test_classify_129_items_rejected(ms_authed):
    texts = [ADVERSE] * 129
    resp = await ms_authed.post("/classify", json={"texts": texts})
    assert resp.status_code == 422


async def test_embed_128_items_accepted(ms_authed):
    texts = [ADVERSE] * 128
    resp = await ms_authed.post("/embed", json={"texts": texts})
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 128


async def test_embed_129_items_rejected(ms_authed):
    texts = ["text"] * 129
    resp = await ms_authed.post("/embed", json={"texts": texts})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Empty batch
# ---------------------------------------------------------------------------


async def test_classify_empty_batch_200(ms_authed):
    resp = await ms_authed.post("/classify", json={"texts": []})
    assert resp.status_code == 200
    assert resp.json()["results"] == []


async def test_embed_empty_batch_200(ms_authed):
    resp = await ms_authed.post("/embed", json={"texts": []})
    assert resp.status_code == 200
    assert resp.json()["results"] == []


# ---------------------------------------------------------------------------
# Over-long text truncation end-to-end
# ---------------------------------------------------------------------------


async def test_classify_overlong_text_still_returns_200(ms_authed):
    """600-token text must be truncated and still produce a result."""
    long_text = " ".join(["patient"] * 600)
    resp = await ms_authed.post("/classify", json={"texts": [long_text]})
    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert 0.0 <= result["confidence"] <= 1.0
    assert isinstance(result["is_adverse"], bool)


async def test_embed_overlong_text_still_returns_200(ms_authed):
    """600-token text must be truncated and still produce a 768-dim embedding."""
    long_text = " ".join(["adverse"] * 600)
    resp = await ms_authed.post("/embed", json={"texts": [long_text]})
    assert resp.status_code == 200
    embedding = resp.json()["results"][0]["embedding"]
    assert len(embedding) == 768


# ---------------------------------------------------------------------------
# Cold-start readiness
# ---------------------------------------------------------------------------


async def test_cold_start_503_without_lifespan():
    """App created but lifespan not run: /classify and /embed return 503."""
    from httpx import ASGITransport, AsyncClient

    from modelserver.main import create_app

    app = create_app()
    app.state.service_token = "test-service-token"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r1 = await c.post(
            "/classify",
            json={"texts": [ADVERSE]},
            headers={"X-Service-Token": "test-service-token"},
        )
        r2 = await c.post(
            "/embed",
            json={"texts": [ADVERSE]},
            headers={"X-Service-Token": "test-service-token"},
        )
    assert r1.status_code == 503
    assert r2.status_code == 503
