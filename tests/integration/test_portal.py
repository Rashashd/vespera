"""Integration tests for the client portal routes (FR-030)."""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_portal_returns_empty_list_for_new_client(
    authed_reviewer_client: AsyncClient,
    make_client,
) -> None:
    """Portal route accessible with acting_client; returns empty list when no approved reports."""
    cl = await make_client()
    resp = await authed_reviewer_client.get(f"/clients/{cl.id}/portal/reports")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_portal_report_cross_client_404(
    authed_reviewer_client: AsyncClient,
    make_client,
) -> None:
    """Requesting portal report from another client returns 404."""
    cl_other = await make_client()
    resp = await authed_reviewer_client.get(f"/clients/{cl_other.id}/portal/reports/999999")
    assert resp.status_code == 404
