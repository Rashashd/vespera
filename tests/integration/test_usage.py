"""Integration tests for the usage/cost dashboard endpoint (FR-021/034)."""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_usage_empty_state_returns_zeros(
    authed_manager_client: AsyncClient,
    make_client,
) -> None:
    """Empty usage for a client returns zeros, not an error (FR-021)."""
    cl = await make_client()
    resp = await authed_manager_client.get(f"/clients/{cl.id}/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["call_count"] == 0
    assert data["total_cost_usd"] == "0.000000"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_usage_reviewer_denied(
    authed_reviewer_client: AsyncClient,
    make_client,
) -> None:
    """Reviewer role cannot access the cost dashboard (require_manager guard)."""
    cl = await make_client()
    resp = await authed_reviewer_client.get(f"/clients/{cl.id}/usage")
    assert resp.status_code in (403, 404)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_usage_admin_denied(
    authed_admin_client: AsyncClient,
    make_client,
) -> None:
    """Admin cannot access the cost dashboard — costs are manager-only (require_manager)."""
    cl = await make_client()
    resp = await authed_admin_client.get(f"/clients/{cl.id}/usage")
    assert resp.status_code in (403, 404)
