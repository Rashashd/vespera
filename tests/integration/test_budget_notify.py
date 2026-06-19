"""Integration (US6): budget-threshold crossing notifies manager+admin once per state (FR-019)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.audit.handler import register_audit_handlers
from app.audit.models import AuditLog
from app.core.dispatcher import EventDispatcher
from app.delivery.notifications import register_budget_notifications
from app.domain.events import WatchlistBudgetThresholdReached


@pytest.mark.integration
@pytest.mark.asyncio
async def test_budget_threshold_notifies_once_per_state(
    auth_app, make_client, make_watchlist, priv_factory, monkeypatch
) -> None:
    """warning crossing → 1 notification; same state → none; soft_capped crossing → another."""
    sent: list[dict] = []

    async def fake_send(self, payload):
        sent.append(payload)

    monkeypatch.setattr("app.delivery.n8n_client.N8nClient.send", fake_send)

    cl = await make_client()
    wl = await make_watchlist(client_id=cl.id)

    dispatcher = EventDispatcher()
    register_audit_handlers(dispatcher)
    register_budget_notifications(dispatcher)

    async def crossing(state: str) -> None:
        # Separate committed transaction per cycle so the prior threshold event is visible.
        async with priv_factory() as s:
            async with s.begin():
                await dispatcher.dispatch(
                    WatchlistBudgetThresholdReached(
                        actor_id=0,
                        actor_type="system",
                        client_id=cl.id,
                        watchlist_id=wl.id,
                        state=state,
                    ),
                    s,
                )

    await crossing("warning")
    assert len(sent) == 1
    assert sent[0]["notification_type"] == "budget_threshold"
    assert sent[0]["state"] == "warning"
    assert sent[0]["recipients"]  # manager/admin (bootstrap manager guarantees ≥1)

    # Same state again → no new notification (no alert storm).
    await crossing("warning")
    assert len(sent) == 1

    # Crossing to a new state → another notification.
    await crossing("soft_capped")
    assert len(sent) == 2
    assert sent[1]["state"] == "soft_capped"

    # Every crossing is still audited (the threshold event itself fires each cycle).
    async with priv_factory() as s:
        rows = (
            (
                await s.execute(
                    select(AuditLog).where(
                        AuditLog.event_type == "WatchlistBudgetThresholdReached",
                        AuditLog.target == f"watchlist:{wl.id}",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 3
