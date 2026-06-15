"""Integration tests for per-report findings endpoint (FR-031) + status=all listing (FR-006a)."""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_report_findings_missing_report(
    authed_reviewer_client: AsyncClient,
    make_client,
) -> None:
    """Non-existent report_id returns 404."""
    cl = await make_client()
    resp = await authed_reviewer_client.get(f"/clients/{cl.id}/reports/999999999/findings")
    assert resp.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_reports_status_all(
    authed_reviewer_client: AsyncClient,
    make_client,
) -> None:
    """status=all returns without filtering on status (may be empty but must not error)."""
    cl = await make_client()
    resp = await authed_reviewer_client.get(f"/clients/{cl.id}/reports?status=all")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_reports_default_filters_to_review_statuses(
    authed_reviewer_client: AsyncClient,
    make_client,
) -> None:
    """Default listing (no status param) only returns review-queue statuses."""
    cl = await make_client()
    resp = await authed_reviewer_client.get(f"/clients/{cl.id}/reports")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    for r in data:
        assert r["status"] in ("drafted", "under_review", "needs_manual_revision")
