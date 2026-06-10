"""Unit tests for per-result model-version stamps (T040 / D9 / FR-005b).

Verifies that every classify and embed result carries the correct artifact
sha256/version, and that the top-level response model_version matches.
"""

from __future__ import annotations

import pytest

ADVERSE = "patient developed acute liver failure"
BENIGN = "no adverse events were observed"

pytestmark = pytest.mark.asyncio


async def test_classify_result_version_matches_top_level(ms_authed):
    resp = await ms_authed.post("/classify", json={"texts": [ADVERSE, BENIGN]})
    assert resp.status_code == 200
    body = resp.json()
    top_sha = body["model_version"]["sha256"]
    for r in body["results"]:
        assert r["model_version"]["sha256"] == top_sha


async def test_embed_result_version_matches_top_level(ms_authed):
    resp = await ms_authed.post("/embed", json={"texts": [ADVERSE, BENIGN]})
    assert resp.status_code == 200
    body = resp.json()
    top_sha = body["model_version"]["sha256"]
    for r in body["results"]:
        assert r["model_version"]["sha256"] == top_sha


async def test_classify_version_name_is_classifier(ms_authed):
    resp = await ms_authed.post("/classify", json={"texts": [ADVERSE]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["model_version"]["name"] == "classifier"
    assert body["results"][0]["model_version"]["name"] == "classifier"


async def test_embed_version_name_is_embedder(ms_authed):
    resp = await ms_authed.post("/embed", json={"texts": [ADVERSE]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["model_version"]["name"] == "embedder"
    assert body["results"][0]["model_version"]["name"] == "embedder"


async def test_classify_version_sha256_nonempty(ms_authed):
    resp = await ms_authed.post("/classify", json={"texts": [ADVERSE]})
    assert resp.status_code == 200
    assert resp.json()["model_version"]["sha256"]


async def test_embed_version_sha256_nonempty(ms_authed):
    resp = await ms_authed.post("/embed", json={"texts": [ADVERSE]})
    assert resp.status_code == 200
    assert resp.json()["model_version"]["sha256"]


async def test_classify_and_embed_versions_are_independent(ms_authed):
    """Classifier and embedder are separate artifacts with distinct SHA-256s."""
    r_clf = await ms_authed.post("/classify", json={"texts": [ADVERSE]})
    r_emb = await ms_authed.post("/embed", json={"texts": [ADVERSE]})
    clf_sha = r_clf.json()["model_version"]["sha256"]
    emb_sha = r_emb.json()["model_version"]["sha256"]
    assert clf_sha != emb_sha, "Classifier and embedder must have distinct SHA-256 stamps"
