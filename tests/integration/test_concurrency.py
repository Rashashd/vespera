"""Concurrency tests: many parallel /classify and /embed requests must be correct (FR-018).

Fires multiple concurrent requests and asserts per-input correctness + determinism under load.
"""

from __future__ import annotations

import asyncio

import pytest

ADVERSE = "patient developed acute liver failure after starting drug X"
BENIGN = "no adverse events were observed during the clinical trial"
TEXTS = [ADVERSE, BENIGN, ADVERSE, BENIGN]

pytestmark = pytest.mark.asyncio


async def _classify(client, text: str) -> dict:
    resp = await client.post("/classify", json={"texts": [text]})
    assert resp.status_code == 200
    return resp.json()["results"][0]


async def _embed(client, text: str) -> dict:
    resp = await client.post("/embed", json={"texts": [text]})
    assert resp.status_code == 200
    return resp.json()["results"][0]


async def test_concurrent_classify_deterministic(ms_authed):
    """10 concurrent classify calls for the same text → identical confidence values."""
    tasks = [asyncio.create_task(_classify(ms_authed, ADVERSE)) for _ in range(10)]
    results = await asyncio.gather(*tasks)
    confidences = {r["confidence"] for r in results}
    assert len(confidences) == 1, f"Non-deterministic confidence under load: {confidences}"


async def test_concurrent_embed_deterministic(ms_authed):
    """10 concurrent embed calls for the same text → identical embeddings."""
    tasks = [asyncio.create_task(_embed(ms_authed, ADVERSE)) for _ in range(10)]
    results = await asyncio.gather(*tasks)
    first_emb = results[0]["embedding"]
    for r in results[1:]:
        assert r["embedding"] == first_emb, "Non-deterministic embedding under load"


async def test_concurrent_mixed_correct(ms_authed):
    """Mixed classify + embed tasks all return 200 with the right shape."""
    clf_tasks = [asyncio.create_task(_classify(ms_authed, t)) for t in TEXTS]
    emb_tasks = [asyncio.create_task(_embed(ms_authed, t)) for t in TEXTS]
    clf_results = await asyncio.gather(*clf_tasks)
    emb_results = await asyncio.gather(*emb_tasks)

    for r in clf_results:
        assert 0.0 <= r["confidence"] <= 1.0
        assert isinstance(r["is_adverse"], bool)

    for r in emb_results:
        assert len(r["embedding"]) == 768


async def test_concurrent_batch_requests_correct(ms_authed):
    """5 concurrent batch requests → each returns the right number of results."""
    batch = TEXTS * 4  # 16 texts
    tasks = [
        asyncio.create_task(ms_authed.post("/classify", json={"texts": batch})) for _ in range(5)
    ]
    responses = await asyncio.gather(*tasks)
    for resp in responses:
        assert resp.status_code == 200
        assert len(resp.json()["results"]) == len(batch)
