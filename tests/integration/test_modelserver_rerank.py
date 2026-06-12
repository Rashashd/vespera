"""Integration test: POST /rerank modelserver contract (T029 / US4).

Boots the modelserver ASGI app in-process with the reranker fixture artifact.
Skipped when onnxruntime is absent (same guard as Spec-6 modelserver tests).
"""

from __future__ import annotations

import os
from importlib.util import find_spec

import pytest

pytestmark = [
    pytest.mark.skipif(
        not os.getenv("PANTERA_INTEGRATION"),
        reason="requires PANTERA_INTEGRATION=1 and docker compose up",
    ),
    pytest.mark.skipif(
        find_spec("onnxruntime") is None,
        reason="onnxruntime not installed",
    ),
]


@pytest.mark.asyncio
class TestModelserverRerank:
    async def test_scores_in_input_order(self, ms_authed_with_reranker) -> None:
        """Returns one score per passage in input order."""
        resp = await ms_authed_with_reranker.post(
            "/rerank",
            json={
                "query": "hepatotoxicity drug reaction",
                "passages": ["liver damage after medication", "no adverse events noted"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 2
        assert all("score" in r for r in data["results"])
        assert all(isinstance(r["score"], float) for r in data["results"])

    async def test_model_version_stamp(self, ms_authed_with_reranker) -> None:
        """Top-level and per-result model_version carry name/version/sha256."""
        resp = await ms_authed_with_reranker.post(
            "/rerank",
            json={"query": "adverse event", "passages": ["patient developed rash after drug"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        mv = data["model_version"]
        assert mv["name"] == "reranker"
        assert "version" in mv and "sha256" in mv
        assert data["results"][0]["model_version"]["sha256"] == mv["sha256"]

    async def test_requires_service_token(self, ms_client_with_reranker) -> None:
        """Requests without X-Service-Token are rejected (401/403)."""
        resp = await ms_client_with_reranker.post(
            "/rerank",
            json={"query": "q", "passages": ["p"]},
        )
        assert resp.status_code in (401, 403)

    async def test_empty_passages_returns_empty(self, ms_authed_with_reranker) -> None:
        """Empty passages list → 200 with empty results, no server error."""
        resp = await ms_authed_with_reranker.post(
            "/rerank",
            json={"query": "hepatotoxicity", "passages": []},
        )
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    async def test_batch_limit_128(self, ms_authed_with_reranker) -> None:
        """Batch of exactly 128 passages returns 128 scores."""
        passages = [f"passage number {i} with some content" for i in range(128)]
        resp = await ms_authed_with_reranker.post(
            "/rerank",
            json={"query": "adverse drug reaction", "passages": passages},
        )
        assert resp.status_code == 200
        assert len(resp.json()["results"]) == 128

    async def test_scores_are_deterministic(self, ms_authed_with_reranker) -> None:
        """Same query+passages produce identical scores on repeated calls (FR-010)."""
        payload = {
            "query": "kidney failure drug",
            "passages": ["acute renal failure after treatment", "clinical trial results"],
        }
        r1 = (await ms_authed_with_reranker.post("/rerank", json=payload)).json()
        r2 = (await ms_authed_with_reranker.post("/rerank", json=payload)).json()
        assert r1["results"][0]["score"] == r2["results"][0]["score"]
        assert r1["results"][1]["score"] == r2["results"][1]["score"]
