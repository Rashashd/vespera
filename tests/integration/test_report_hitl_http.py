"""Integration regression: reviewer HITL routes must work over the real HTTP path.

Every reviewer/finding route in app/reports/routes.py used to open `async with session.begin()`
while get_session already owns the request transaction → 500 "A transaction is already begun".
The existing suite only exercised the service layer (app/reports/review.py) directly, so the
double-begin never surfaced. These tests drive the routes through the ASGI client to lock it.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.reports.models import Report


async def _seed_report(factory, client_id, *, status="under_review") -> int:
    """Insert a batch report in a reviewable state and return its id."""
    async with factory() as s:
        async with s.begin():
            report = Report(
                client_id=client_id,
                report_type="batch",
                status=status,
                structured_fields=[{"text": "signal", "provenance": "drafted_grounded"}],
                draft_body="body",
            )
            s.add(report)
            await s.flush()
            return report.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_over_http_returns_200(
    authed_reviewer_client: AsyncClient, make_client, priv_factory, monkeypatch
) -> None:
    """POST .../approve returns 200 + approved (regression for the double-begin 500)."""

    async def fake_send(self, payload):  # approval enqueues delivery — never hit a real n8n
        return None

    monkeypatch.setattr("app.delivery.n8n_client.N8nClient.send", fake_send)

    cl = await make_client()
    report_id = await _seed_report(priv_factory, cl.id, status="under_review")

    resp = await authed_reviewer_client.post(f"/clients/{cl.id}/reports/{report_id}/approve")

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discard_over_http_returns_200(
    authed_reviewer_client: AsyncClient, make_client, priv_factory
) -> None:
    """POST .../discard returns 200 + discarded (same double-begin path, no enqueue)."""
    cl = await make_client()
    report_id = await _seed_report(priv_factory, cl.id, status="under_review")

    resp = await authed_reviewer_client.post(
        f"/clients/{cl.id}/reports/{report_id}/discard", json={}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "discarded"
