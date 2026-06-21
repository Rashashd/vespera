"""Integration (US1): dispatch→callback→delivered, recipient selection, skip non-approved."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.audit.handler import register_audit_handlers
from app.audit.models import AuditLog
from app.clients.models import Client
from app.core.dispatcher import EventDispatcher
from app.delivery.models import DeliveryAttempt
from app.delivery.service import run_delivery
from app.reports.enums import ReportStatus
from app.reports.models import Report


def _make_wc(auth_app, factory):
    """A WorkerContext-like stub for run_delivery (the worker is not running in tests)."""
    dispatcher = EventDispatcher()
    register_audit_handlers(dispatcher)
    return SimpleNamespace(
        settings=auth_app.state.settings, session_factory=factory, dispatcher=dispatcher
    )


async def _set_channels(factory, client_id, *, regular=None, urgent=None):
    async with factory() as s:
        async with s.begin():
            c = await s.get(Client, client_id)
            c.report_email_regular = regular
            c.report_email_urgent = urgent


async def _seed_report(factory, client_id, *, report_type="batch", status="approved") -> int:
    async with factory() as s:
        async with s.begin():
            report = Report(
                client_id=client_id,
                report_type=report_type,
                status=status,
                structured_fields=[{"text": "signal", "provenance": "drafted_grounded"}],
                draft_body="body",
            )
            s.add(report)
            await s.flush()
            return report.id


async def _attempts(factory, report_id) -> list[DeliveryAttempt]:
    async with factory() as s:
        return list(
            (await s.execute(select(DeliveryAttempt).where(DeliveryAttempt.report_id == report_id)))
            .scalars()
            .all()
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_dispatch_callback_delivered(
    client: AsyncClient, auth_app, make_client, priv_factory, monkeypatch
) -> None:
    """Dispatch → sent + pending email attempt; delivered callback → delivered + audited."""
    sent_payloads: list[dict] = []

    async def fake_send(self, payload):
        sent_payloads.append(payload)

    monkeypatch.setattr("app.delivery.n8n_client.N8nClient.send", fake_send)
    monkeypatch.setattr(auth_app.state.settings, "n8n_webhook_url", "https://n8n.test/webhook")

    cl = await make_client()
    await _set_channels(priv_factory, cl.id, regular="regular@example.com")
    report_id = await _seed_report(priv_factory, cl.id, report_type="batch", status="approved")

    await run_delivery(report_id, _make_wc(auth_app, priv_factory))

    # Dispatched: report sent, one pending email attempt, n8n POST invoked with the recipient.
    async with priv_factory() as s:
        report = await s.get(Report, report_id)
        assert report.status == ReportStatus.SENT
        assert report.sent_at is not None
    attempts = await _attempts(priv_factory, report_id)
    assert len(attempts) == 1
    assert attempts[0].channel == "email" and attempts[0].status == "pending"
    assert len(sent_payloads) == 1
    assert sent_payloads[0]["recipient"] == "regular@example.com"

    # Delivered callback (service-token auth) → report delivered + delivered_at + audited.
    token = auth_app.state.settings.delivery_callback_token
    resp = await client.post(
        f"/clients/{cl.id}/reports/{report_id}/delivery-callback",
        headers={"X-Delivery-Token": token},
        json={"channel": "email", "outcome": "delivered"},
    )
    assert resp.status_code == 200
    assert resp.json()["report_status"] == "delivered"

    async with priv_factory() as s:
        report = await s.get(Report, report_id)
        assert report.status == ReportStatus.DELIVERED
        assert report.delivered_at is not None
        delivered_rows = (
            (
                await s.execute(
                    select(AuditLog).where(
                        AuditLog.event_type == "ReportDelivered",
                        AuditLog.client_id == cl.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(delivered_rows) >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recipient_selection_by_urgency(
    auth_app, make_client, priv_factory, monkeypatch
) -> None:
    """FR-003: expedited → urgent recipient; batch → regular recipient."""
    sent_payloads: list[dict] = []

    async def fake_send(self, payload):
        sent_payloads.append(payload)

    monkeypatch.setattr("app.delivery.n8n_client.N8nClient.send", fake_send)
    monkeypatch.setattr(auth_app.state.settings, "n8n_webhook_url", "https://n8n.test/webhook")

    cl = await make_client()
    await _set_channels(
        priv_factory, cl.id, regular="regular@example.com", urgent="urgent@example.com"
    )

    expedited_id = await _seed_report(priv_factory, cl.id, report_type="expedited")
    await run_delivery(expedited_id, _make_wc(auth_app, priv_factory))
    exp_attempts = await _attempts(priv_factory, expedited_id)
    assert exp_attempts[0].recipient_kind == "urgent"
    assert sent_payloads[-1]["recipient"] == "urgent@example.com"

    batch_id = await _seed_report(priv_factory, cl.id, report_type="batch")
    await run_delivery(batch_id, _make_wc(auth_app, priv_factory))
    batch_attempts = await _attempts(priv_factory, batch_id)
    assert batch_attempts[0].recipient_kind == "regular"
    assert sent_payloads[-1]["recipient"] == "regular@example.com"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_non_approved_report_not_dispatched(
    auth_app, make_client, priv_factory, monkeypatch
) -> None:
    """A drafted report is never dispatched (HITL gate enforced at send time)."""
    calls: list[dict] = []

    async def fake_send(self, payload):
        calls.append(payload)

    monkeypatch.setattr("app.delivery.n8n_client.N8nClient.send", fake_send)

    cl = await make_client()
    await _set_channels(priv_factory, cl.id, regular="regular@example.com")
    report_id = await _seed_report(priv_factory, cl.id, status="drafted")

    await run_delivery(report_id, _make_wc(auth_app, priv_factory))

    assert calls == []
    assert await _attempts(priv_factory, report_id) == []
    async with priv_factory() as s:
        report = await s.get(Report, report_id)
        assert report.status == ReportStatus.DRAFTED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_delivery_missing_report_is_noop(auth_app, priv_factory, monkeypatch) -> None:
    """A delivery job for a non-existent report is a safe no-op (defensive guard, no crash)."""
    calls: list[dict] = []

    async def fake_send(self, payload):
        calls.append(payload)

    monkeypatch.setattr("app.delivery.n8n_client.N8nClient.send", fake_send)
    await run_delivery(999_999_999, _make_wc(auth_app, priv_factory))
    assert calls == []
