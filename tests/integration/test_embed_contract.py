"""Contract tests for POST /embed (US2).

Covers: 768-dim output, L2 normalization, determinism, batch order,
empty batch, semantic-sanity cosine check, per-result model_version,
and token rejection.
Uses ASGI transport against the fixture modelserver app — no network needed.
"""

from __future__ import annotations

import math

import pytest

MEDICAL_TEXT_A = "patient liver damage severe"
MEDICAL_TEXT_B = "patient liver damage acute"
UNRELATED_TEXT = "no trial participants"

pytestmark = pytest.mark.asyncio


def _cosine(v1: list[float], v2: list[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2, strict=True))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(b * b for b in v2))
    if n1 == 0 or n2 == 0:
        return 0.0
    return dot / (n1 * n2)


async def test_embed_returns_768_dim(ms_authed):
    resp = await ms_authed.post("/embed", json={"texts": [MEDICAL_TEXT_A]})
    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body
    assert len(body["results"]) == 1
    assert len(body["results"][0]["embedding"]) == 768


async def test_embed_correct_count(ms_authed):
    texts = [MEDICAL_TEXT_A, MEDICAL_TEXT_B, UNRELATED_TEXT]
    resp = await ms_authed.post("/embed", json={"texts": texts})
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 3


async def test_embed_l2_normalized(ms_authed):
    resp = await ms_authed.post("/embed", json={"texts": [MEDICAL_TEXT_A, UNRELATED_TEXT]})
    assert resp.status_code == 200
    for r in resp.json()["results"]:
        vec = r["embedding"]
        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 1e-4, f"vector norm {norm:.6f} is not ≈ 1.0"


async def test_embed_determinism(ms_authed):
    payload = {"texts": [MEDICAL_TEXT_A]}
    r1 = await ms_authed.post("/embed", json=payload)
    r2 = await ms_authed.post("/embed", json=payload)
    assert r1.status_code == r2.status_code == 200
    v1 = r1.json()["results"][0]["embedding"]
    v2 = r2.json()["results"][0]["embedding"]
    assert v1 == v2


async def test_embed_batch_order_preserved(ms_authed):
    texts = [MEDICAL_TEXT_A, MEDICAL_TEXT_B, MEDICAL_TEXT_A]
    resp = await ms_authed.post("/embed", json={"texts": texts})
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 3
    # First and third are the same text — must produce the same vector
    assert results[0]["embedding"] == results[2]["embedding"]


async def test_embed_empty_batch_returns_empty(ms_authed):
    resp = await ms_authed.post("/embed", json={"texts": []})
    assert resp.status_code == 200
    assert resp.json()["results"] == []


async def test_embed_semantic_sanity_cosine(ms_authed):
    """Medical texts sharing tokens (A & B) must be closer than either is to UNRELATED."""
    resp = await ms_authed.post(
        "/embed", json={"texts": [MEDICAL_TEXT_A, MEDICAL_TEXT_B, UNRELATED_TEXT]}
    )
    assert resp.status_code == 200
    vecs = [r["embedding"] for r in resp.json()["results"]]
    sim_ab = _cosine(vecs[0], vecs[1])
    sim_ac = _cosine(vecs[0], vecs[2])
    assert sim_ab > sim_ac, (
        f"Expected similar medical texts (sim={sim_ab:.4f}) to be "
        f"closer than unrelated text (sim={sim_ac:.4f})"
    )


async def test_embed_model_version_stamp_present(ms_authed):
    resp = await ms_authed.post("/embed", json={"texts": [MEDICAL_TEXT_A]})
    assert resp.status_code == 200
    body = resp.json()
    assert "model_version" in body
    mv = body["model_version"]
    assert mv["name"] == "embedder"
    assert mv["sha256"]
    assert mv["version"]
    r = body["results"][0]
    assert r["model_version"]["sha256"] == mv["sha256"]


async def test_embed_model_version_consistent_across_results(ms_authed):
    resp = await ms_authed.post("/embed", json={"texts": [MEDICAL_TEXT_A, MEDICAL_TEXT_B]})
    assert resp.status_code == 200
    sha256s = {r["model_version"]["sha256"] for r in resp.json()["results"]}
    assert len(sha256s) == 1, "All results must carry the same embedder version"


async def test_embed_dim_field_in_response(ms_authed):
    resp = await ms_authed.post("/embed", json={"texts": [MEDICAL_TEXT_A]})
    assert resp.status_code == 200
    assert resp.json()["dim"] == 768


async def test_embed_over_128_items_rejected(ms_authed):
    texts = ["text"] * 129
    resp = await ms_authed.post("/embed", json={"texts": texts})
    assert resp.status_code == 422


async def test_embed_missing_token_returns_401(ms_client):
    resp = await ms_client.post("/embed", json={"texts": [MEDICAL_TEXT_A]})
    assert resp.status_code == 401


async def test_embed_invalid_token_returns_403(ms_client):
    resp = await ms_client.post(
        "/embed",
        json={"texts": [MEDICAL_TEXT_A]},
        headers={"X-Service-Token": "wrong-token"},
    )
    assert resp.status_code == 403
