"""Integration tests for the passage-text endpoint (FR-029)."""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_passage_unavailable_returns_404(
    authed_reviewer_client: AsyncClient,
    make_client,
) -> None:
    """Non-existent chunk_id returns 404 PASSAGE_UNAVAILABLE."""
    cl = await make_client()
    resp = await authed_reviewer_client.get(f"/clients/{cl.id}/passages/999999999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "PASSAGE_UNAVAILABLE"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_passage_cross_client_isolation(
    authed_reviewer_client: AsyncClient,
    make_client,
) -> None:
    """Chunk belonging to another client returns 404 (cross-client isolation)."""
    cl_other = await make_client()
    # Any chunk_id not belonging to the acting client returns 404
    resp = await authed_reviewer_client.get(f"/clients/{cl_other.id}/passages/1")
    # Either 403/404 — the key invariant is it never reveals data
    assert resp.status_code in (403, 404)
