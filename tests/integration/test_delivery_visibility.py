"""Integration (US2): reviewer schemas carry delivery_status; metrics delivery block populated."""

from __future__ import annotations

import pytest

from app.reports.models import Report


async def _seed(factory, client_id, status) -> int:
    async with factory() as s:
        async with s.begin():
            r = Report(client_id=client_id, report_type="batch", status=status)
            s.add(r)
            await s.flush()
            return r.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reviewer_summary_and_detail_carry_delivery_status(
    authed_reviewer_client, make_client, priv_factory
) -> None:
    """Each reviewer report summary + detail exposes the derived delivery_status label."""
    cl = await make_client()
    ids = {
        "approved": await _seed(priv_factory, cl.id, "approved"),
        "sent": await _seed(priv_factory, cl.id, "sent"),
        "delivered": await _seed(priv_factory, cl.id, "delivered"),
        "delivery_failed": await _seed(priv_factory, cl.id, "delivery_failed"),
    }
    expected = {
        "approved": "approved_pending_delivery",
        "sent": "sent",
        "delivered": "delivered",
        "delivery_failed": "delivery_failed",
    }

    resp = await authed_reviewer_client.get(f"/clients/{cl.id}/reports?status=all")
    assert resp.status_code == 200
    by_id = {row["id"]: row for row in resp.json()}
    for key, rid in ids.items():
        assert by_id[rid]["delivery_status"] == expected[key]

    detail = await authed_reviewer_client.get(f"/clients/{cl.id}/reports/{ids['sent']}")
    assert detail.status_code == 200
    assert detail.json()["delivery_status"] == "sent"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_metrics_delivery_block_populated(
    authed_admin_client, make_client, priv_factory
) -> None:
    """GET /metrics returns a non-null delivery block with sent/delivered/failed/success_rate."""
    cl = await make_client()
    await _seed(priv_factory, cl.id, "sent")
    await _seed(priv_factory, cl.id, "delivered")
    await _seed(priv_factory, cl.id, "delivery_failed")

    resp = await authed_admin_client.get(f"/clients/{cl.id}/metrics")
    assert resp.status_code == 200
    delivery = resp.json()["delivery"]
    assert delivery is not None
    assert delivery["sent"] == 1
    assert delivery["delivered"] == 1
    assert delivery["failed"] == 1
    # delivered ÷ dispatched = 1/3 → 33.3
    assert delivery["success_rate"] == 33.3
