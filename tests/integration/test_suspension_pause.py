"""Integration: FR-007b — a suspended client's watchlists are paused from the cadence loop.

Asserts the comprehensive pause claim (no cycles run while suspended; resume on reactivation),
not merely the delivery hold — the cadence loop already gates on Client.status == active (D5).
"""

from __future__ import annotations

import pytest

from app.clients.models import Client, WatchlistItem
from app.scheduling.service import CycleService


async def _add_item(factory, watchlist_id, client_id):
    async with factory() as s:
        async with s.begin():
            s.add(
                WatchlistItem(
                    watchlist_id=watchlist_id,
                    client_id=client_id,
                    item_type="drug",
                    value="aspirin",
                    normalized_value="aspirin",
                )
            )


async def _set_status(factory, client_id, status):
    async with factory() as s:
        async with s.begin():
            (await s.get(Client, client_id)).status = status


async def _due_ids(factory) -> set[int]:
    async with factory() as s:
        rows = await CycleService.query_due_watchlists(s)
    return {r["watchlist_id"] for r in rows}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_suspension_pauses_and_reactivation_resumes_cycles(
    auth_app, make_client, make_watchlist, priv_factory
) -> None:
    """A due watchlist drops out of query_due_watchlists when its client is suspended, and
    returns once reactivated — proving suspension pauses ALL cadence work (not just delivery)."""
    cl = await make_client(status="active")
    wl = await make_watchlist(client_id=cl.id, is_active=True)
    await _add_item(priv_factory, wl.id, cl.id)

    # Active + due (no prior cycle) → present.
    assert wl.id in await _due_ids(priv_factory)

    # Suspended → excluded (no cycles run).
    await _set_status(priv_factory, cl.id, "suspended")
    assert wl.id not in await _due_ids(priv_factory)

    # Reactivated → present again (cadence resumes automatically; no watchlist is_active change).
    await _set_status(priv_factory, cl.id, "active")
    assert wl.id in await _due_ids(priv_factory)
