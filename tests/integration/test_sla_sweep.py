"""Integration (US3): no-callback timeout flip + tiered SLA escalation sweep (FR-006a/FR-012)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.audit.handler import register_audit_handlers
from app.audit.models import AuditLog
from app.core.dispatcher import EventDispatcher
from app.delivery.models import DeliveryAttempt
from app.delivery.sweep import run_sla_sweep
from app.reports.enums import ReportStatus
from app.reports.models import Report


def _make_wc(auth_app, factory):
    dispatcher = EventDispatcher()
    register_audit_handlers(dispatcher)
    return SimpleNamespace(
        settings=auth_app.state.settings, session_factory=factory, dispatcher=dispatcher
    )


async def _seed_report(factory, client_id, **fields) -> int:
    async with factory() as s:
        async with s.begin():
            r = Report(client_id=client_id, report_type=fields.pop("report_type", "expedited"))
            r.status = fields.pop("status", "under_review")
            for k, v in fields.items():
                setattr(r, k, v)
            s.add(r)
            await s.flush()
            return r.id


async def _add_pending_attempt(factory, report_id, client_id):
    async with factory() as s:
        async with s.begin():
            s.add(
                DeliveryAttempt(
                    report_id=report_id, client_id=client_id, channel="email", status="pending"
                )
            )


async def _report(factory, rid) -> Report:
    async with factory() as s:
        return await s.get(Report, rid)


async def _audit_count(factory, event_type, client_id, **payload_eq) -> int:
    async with factory() as s:
        rows = (
            (
                await s.execute(
                    select(AuditLog).where(
                        AuditLog.event_type == event_type, AuditLog.client_id == client_id
                    )
                )
            )
            .scalars()
            .all()
        )
    if payload_eq:
        rows = [
            r for r in rows if all((r.payload or {}).get(k) == v for k, v in payload_eq.items())
        ]
    return len(rows)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_callback_timeout_flips_to_failed(
    auth_app, make_client, priv_factory, monkeypatch
) -> None:
    """A `sent` report with a pending attempt older than the window → delivery_failed + alert."""

    async def fake_send(self, payload):
        return None

    monkeypatch.setattr("app.delivery.n8n_client.N8nClient.send", fake_send)

    now = datetime.now(UTC)
    cl = await make_client()
    rid = await _seed_report(
        priv_factory, cl.id, report_type="batch", status="sent", sent_at=now - timedelta(hours=7)
    )
    await _add_pending_attempt(priv_factory, rid, cl.id)

    await run_sla_sweep(_make_wc(auth_app, priv_factory), now=now)

    rep = await _report(priv_factory, rid)
    assert rep.status == ReportStatus.DELIVERY_FAILED
    assert rep.delivery_failed_at is not None
    assert await _audit_count(priv_factory, "ReportDeliveryFailed", cl.id) >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sla_tier1_then_tier2_each_fire_once(
    auth_app, make_client, priv_factory, monkeypatch
) -> None:
    """Overdue expedited → Tier-1 (reviewers); after the gap, Tier-2 (manager/admin); once each."""

    async def fake_send(self, payload):
        return None

    monkeypatch.setattr("app.delivery.n8n_client.N8nClient.send", fake_send)

    now = datetime.now(UTC)
    cl = await make_client()
    rid = await _seed_report(
        priv_factory,
        cl.id,
        report_type="expedited",
        status="under_review",
        sla_deadline=now - timedelta(hours=1),
        sla_escalation_tier=0,
    )

    # First sweep → Tier-1.
    await run_sla_sweep(_make_wc(auth_app, priv_factory), now=now)
    rep = await _report(priv_factory, rid)
    assert rep.sla_escalation_tier == 1
    assert await _audit_count(priv_factory, "SlaEscalated", cl.id, tier=1) == 1

    # Immediate re-sweep → no change (Tier-2 gap not elapsed; Tier-1 not re-fired).
    await run_sla_sweep(_make_wc(auth_app, priv_factory), now=now)
    rep = await _report(priv_factory, rid)
    assert rep.sla_escalation_tier == 1
    assert await _audit_count(priv_factory, "SlaEscalated", cl.id, tier=1) == 1

    # After the Tier-2 interval → Tier-2 (fires once).
    later = now + timedelta(hours=3)
    await run_sla_sweep(_make_wc(auth_app, priv_factory), now=later)
    rep = await _report(priv_factory, rid)
    assert rep.sla_escalation_tier == 2
    assert await _audit_count(priv_factory, "SlaEscalated", cl.id, tier=2) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_actioned_and_non_expedited_never_escalate(
    auth_app, make_client, priv_factory, monkeypatch
) -> None:
    """An actioned (approved) report and a non-expedited report past deadline do not escalate."""

    async def fake_send(self, payload):
        return None

    monkeypatch.setattr("app.delivery.n8n_client.N8nClient.send", fake_send)

    now = datetime.now(UTC)
    cl = await make_client()
    actioned = await _seed_report(
        priv_factory,
        cl.id,
        report_type="expedited",
        status="approved",
        sla_deadline=now - timedelta(hours=5),
    )
    batch = await _seed_report(
        priv_factory,
        cl.id,
        report_type="batch",
        status="under_review",
        sla_deadline=now - timedelta(hours=5),
    )

    await run_sla_sweep(_make_wc(auth_app, priv_factory), now=now)

    assert (await _report(priv_factory, actioned)).sla_escalation_tier == 0
    assert (await _report(priv_factory, batch)).sla_escalation_tier == 0
    assert await _audit_count(priv_factory, "SlaEscalated", cl.id) == 0
