"""Integration tests for the ops-metrics endpoint (FR-021a)."""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ops_metrics_empty_state(
    authed_admin_client: AsyncClient,
    make_client,
) -> None:
    """Empty client returns a zeroed structure with delivery=null (spec-13 forward dep)."""
    cl = await make_client()
    resp = await authed_admin_client.get(f"/clients/{cl.id}/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["delivery"] is None
    assert isinstance(data["by_status"], dict)
    assert "pending" in data["queue"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ops_metrics_reviewer_denied(
    authed_reviewer_client: AsyncClient,
    make_client,
) -> None:
    """Reviewer cannot access ops metrics (require_admin guard)."""
    cl = await make_client()
    resp = await authed_reviewer_client.get(f"/clients/{cl.id}/metrics")
    assert resp.status_code in (403, 404)
