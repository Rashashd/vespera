"""Contract tests for POST /classify (US1).

Covers: batch order, confidence ∈ [0,1], is_adverse at default cutoff 0.5,
determinism, per-result model_version stamp, empty batch, and token rejection.
Uses ASGI transport against the fixture modelserver app — no network needed.
"""

from __future__ import annotations

import pytest

ADVERSE_TEXT = "patient developed acute liver failure after starting drug X"
BENIGN_TEXT = "no adverse events were observed during the 12-week trial"

pytestmark = pytest.mark.asyncio


async def test_classify_returns_correct_shape(ms_authed):
    resp = await ms_authed.post("/classify", json={"texts": [ADVERSE_TEXT, BENIGN_TEXT]})
    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body
    assert len(body["results"]) == 2


async def test_confidence_in_unit_interval(ms_authed):
    resp = await ms_authed.post("/classify", json={"texts": [ADVERSE_TEXT, BENIGN_TEXT]})
    assert resp.status_code == 200
    for r in resp.json()["results"]:
        assert 0.0 <= r["confidence"] <= 1.0, f"confidence out of [0,1]: {r['confidence']}"


async def test_is_adverse_matches_confidence_threshold(ms_authed):
    resp = await ms_authed.post("/classify", json={"texts": [ADVERSE_TEXT, BENIGN_TEXT]})
    assert resp.status_code == 200
    for r in resp.json()["results"]:
        expected = r["confidence"] >= 0.5
        assert (
            r["is_adverse"] == expected
        ), f"is_adverse={r['is_adverse']} but confidence={r['confidence']}"


async def test_batch_order_preserved(ms_authed):
    texts = [ADVERSE_TEXT, BENIGN_TEXT, ADVERSE_TEXT]
    resp = await ms_authed.post("/classify", json={"texts": texts})
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 3
    # First and third (same adverse text) should have the same confidence
    assert results[0]["confidence"] == results[2]["confidence"]


async def test_determinism(ms_authed):
    payload = {"texts": [ADVERSE_TEXT]}
    r1 = await ms_authed.post("/classify", json=payload)
    r2 = await ms_authed.post("/classify", json=payload)
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["results"][0]["confidence"] == r2.json()["results"][0]["confidence"]
    assert r1.json()["results"][0]["is_adverse"] == r2.json()["results"][0]["is_adverse"]


async def test_model_version_stamp_present(ms_authed):
    resp = await ms_authed.post("/classify", json={"texts": [ADVERSE_TEXT]})
    assert resp.status_code == 200
    body = resp.json()
    # Top-level version
    assert "model_version" in body
    mv = body["model_version"]
    assert mv["name"] == "classifier"
    assert mv["sha256"]
    assert mv["version"]
    # Per-result version
    r = body["results"][0]
    assert r["model_version"]["sha256"] == mv["sha256"]


async def test_model_version_consistent_across_results(ms_authed):
    resp = await ms_authed.post("/classify", json={"texts": [ADVERSE_TEXT, BENIGN_TEXT]})
    assert resp.status_code == 200
    sha256s = {r["model_version"]["sha256"] for r in resp.json()["results"]}
    assert len(sha256s) == 1, "All results must carry the same classifier version"


async def test_empty_batch_returns_empty_results(ms_authed):
    resp = await ms_authed.post("/classify", json={"texts": []})
    assert resp.status_code == 200
    assert resp.json()["results"] == []


async def test_over_128_items_rejected(ms_authed):
    texts = ["text"] * 129
    resp = await ms_authed.post("/classify", json={"texts": texts})
    assert resp.status_code == 422


async def test_missing_token_returns_401(ms_client):
    resp = await ms_client.post("/classify", json={"texts": [ADVERSE_TEXT]})
    assert resp.status_code == 401


async def test_invalid_token_returns_403(ms_client):
    resp = await ms_client.post(
        "/classify",
        json={"texts": [ADVERSE_TEXT]},
        headers={"X-Service-Token": "wrong-token"},
    )
    assert resp.status_code == 403


async def test_health_requires_no_auth(ms_client):
    resp = await ms_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_ready_returns_model_versions(ms_authed):
    resp = await ms_authed.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert "classifier" in body["models"]
    assert "embedder" in body["models"]
