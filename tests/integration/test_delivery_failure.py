"""Integration: multi-channel failure + targeted resend, callback idempotency, holds (US1)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.audit.handler import register_audit_handlers
from app.audit.models import AuditLog
from app.clients.models import Client
from app.core.dispatcher import EventDispatcher
from app.delivery.handlers import make_on_client_reactivated
from app.delivery.models import DeliveryAttempt
from app.delivery.service import run_delivery
from app.domain.events import ClientReactivated
from app.reports.enums import ReportStatus
from app.reports.models import Report


def _make_wc(auth_app, factory):
    dispatcher = EventDispatcher()
    register_audit_handlers(dispatcher)
    return SimpleNamespace(
        settings=auth_app.state.settings, session_factory=factory, dispatcher=dispatcher
    )


async def _configure(factory, client_id, **fields):
    async with factory() as s:
        async with s.begin():
            c = await s.get(Client, client_id)
            for k, v in fields.items():
                setattr(c, k, v)


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


async def _attempts_by_channel(factory, report_id) -> dict[str, DeliveryAttempt]:
    async with factory() as s:
        rows = (
            (await s.execute(select(DeliveryAttempt).where(DeliveryAttempt.report_id == report_id)))
            .scalars()
            .all()
        )
        return {a.channel: a for a in rows}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multichannel_failure_then_targeted_resend(
    client: AsyncClient, authed_admin_client, auth_app, make_client, priv_factory, monkeypatch
) -> None:
    """email ok + sftp failed → delivery_failed; admin resend re-sends sftp only → delivered."""
    payloads: list[dict] = []

    async def fake_send(self, payload):
        payloads.append(payload)

    monkeypatch.setattr("app.delivery.n8n_client.N8nClient.send", fake_send)
    monkeypatch.setattr(auth_app.state.settings, "n8n_webhook_url", "https://n8n.test/webhook")

    cl = await make_client()
    await _configure(
        priv_factory,
        cl.id,
        report_email_regular="regular@example.com",
        sftp_enabled=True,
        sftp_host="sftp.example.com",
        sftp_path="/inbound",
    )
    rid = await _seed_report(priv_factory, cl.id, report_type="batch")

    await run_delivery(rid, _make_wc(auth_app, priv_factory))
    attempts = await _attempts_by_channel(priv_factory, rid)
    assert set(attempts) == {"email", "sftp"}
    assert all(a.status == "pending" for a in attempts.values())

    token = auth_app.state.settings.delivery_callback_token
    base = f"/clients/{cl.id}/reports/{rid}/delivery-callback"

    r1 = await client.post(
        base, headers={"X-Delivery-Token": token}, json={"channel": "email", "outcome": "delivered"}
    )
    assert r1.status_code == 200 and r1.json()["report_status"] == "sent"

    r2 = await client.post(
        base,
        headers={"X-Delivery-Token": token},
        json={"channel": "sftp", "outcome": "failed", "error": "connection refused"},
    )
    assert r2.status_code == 200 and r2.json()["report_status"] == "delivery_failed"

    async with priv_factory() as s:
        rep = await s.get(Report, rid)
        assert rep.status == ReportStatus.DELIVERY_FAILED
        assert rep.delivery_failed_at is not None
        failed_rows = (
            (
                await s.execute(
                    select(AuditLog).where(
                        AuditLog.event_type == "ReportDeliveryFailed",
                        AuditLog.client_id == cl.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(failed_rows) >= 1

    # Admin re-send: only the failed (sftp) channel re-dispatches; email stays delivered.
    payloads.clear()
    rr = await authed_admin_client.post(f"/clients/{cl.id}/reports/{rid}/resend")
    assert rr.status_code == 200
    assert [p["channel"] for p in payloads] == ["sftp"]

    attempts = await _attempts_by_channel(priv_factory, rid)
    assert attempts["email"].status == "delivered"  # confirmed channel untouched
    assert attempts["sftp"].status == "pending"
    async with priv_factory() as s:
        assert (await s.get(Report, rid)).status == ReportStatus.SENT

    # SFTP delivered callback → all channels confirmed → delivered.
    r3 = await client.post(
        base, headers={"X-Delivery-Token": token}, json={"channel": "sftp", "outcome": "delivered"}
    )
    assert r3.status_code == 200 and r3.json()["report_status"] == "delivered"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_callback_idempotency_and_unknown_dispatch(
    client: AsyncClient, auth_app, make_client, priv_factory, monkeypatch
) -> None:
    """A duplicate callback on a final attempt is a no-op 200; an unknown dispatch is 404."""

    async def fake_send(self, payload):
        return None

    monkeypatch.setattr("app.delivery.n8n_client.N8nClient.send", fake_send)
    monkeypatch.setattr(auth_app.state.settings, "n8n_webhook_url", "https://n8n.test/webhook")

    cl = await make_client()
    await _configure(priv_factory, cl.id, report_email_regular="regular@example.com")
    rid = await _seed_report(priv_factory, cl.id)
    await run_delivery(rid, _make_wc(auth_app, priv_factory))

    token = auth_app.state.settings.delivery_callback_token
    base = f"/clients/{cl.id}/reports/{rid}/delivery-callback"

    r1 = await client.post(
        base, headers={"X-Delivery-Token": token}, json={"channel": "email", "outcome": "delivered"}
    )
    assert r1.json()["report_status"] == "delivered"

    # Duplicate / late callback → no-op, stays delivered (does not flip).
    r2 = await client.post(
        base, headers={"X-Delivery-Token": token}, json={"channel": "email", "outcome": "failed"}
    )
    assert r2.status_code == 200 and r2.json()["report_status"] == "delivered"

    # Unknown dispatch (no sftp attempt for this report) → 404.
    r3 = await client.post(
        base, headers={"X-Delivery-Token": token}, json={"channel": "sftp", "outcome": "delivered"}
    )
    assert r3.status_code == 404

    # Wrong token → 401.
    r4 = await client.post(
        base,
        headers={"X-Delivery-Token": "wrong"},
        json={"channel": "email", "outcome": "delivered"},
    )
    assert r4.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_channel_holds_report(auth_app, make_client, priv_factory, monkeypatch) -> None:
    """A client with no configured channel holds the report approved-pending-delivery + alerts."""
    calls: list[dict] = []

    async def fake_send(self, payload):
        calls.append(payload)

    monkeypatch.setattr("app.delivery.n8n_client.N8nClient.send", fake_send)

    cl = await make_client()  # no email, no sftp
    rid = await _seed_report(priv_factory, cl.id)
    await run_delivery(rid, _make_wc(auth_app, priv_factory))

    assert calls == []
    assert await _attempts_by_channel(priv_factory, rid) == {}
    async with priv_factory() as s:
        assert (await s.get(Report, rid)).status == ReportStatus.APPROVED
        held = (
            (
                await s.execute(
                    select(AuditLog).where(
                        AuditLog.event_type == "ReportDeliveryHeld",
                        AuditLog.client_id == cl.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert any((row.payload or {}).get("reason") == "no_channel" for row in held)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unconfigured_n8n_holds_report(
    auth_app, make_client, priv_factory, monkeypatch
) -> None:
    """No n8n webhook configured → report holds approved-pending-delivery (graceful degrade)."""
    monkeypatch.setattr(auth_app.state.settings, "n8n_webhook_url", "")

    cl = await make_client()
    await _configure(priv_factory, cl.id, report_email_regular="regular@example.com")
    rid = await _seed_report(priv_factory, cl.id)
    await run_delivery(rid, _make_wc(auth_app, priv_factory))

    # No dispatch attempts; report stays approved; held with reason "unconfigured".
    assert await _attempts_by_channel(priv_factory, rid) == {}
    async with priv_factory() as s:
        assert (await s.get(Report, rid)).status == ReportStatus.APPROVED
        held = (
            (
                await s.execute(
                    select(AuditLog).where(
                        AuditLog.event_type == "ReportDeliveryHeld",
                        AuditLog.client_id == cl.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert any((row.payload or {}).get("reason") == "unconfigured" for row in held)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_suspended_holds_then_reactivation_releases(
    auth_app, make_client, priv_factory, monkeypatch
) -> None:
    """A suspended client holds delivery; once active, the held report dispatches (release)."""
    payloads: list[dict] = []

    async def fake_send(self, payload):
        payloads.append(payload)

    monkeypatch.setattr("app.delivery.n8n_client.N8nClient.send", fake_send)
    monkeypatch.setattr(auth_app.state.settings, "n8n_webhook_url", "https://n8n.test/webhook")

    cl = await make_client(status="suspended")
    await _configure(priv_factory, cl.id, report_email_regular="regular@example.com")
    rid = await _seed_report(priv_factory, cl.id)

    # Suspended → held, no dispatch, stays approved.
    await run_delivery(rid, _make_wc(auth_app, priv_factory))
    assert payloads == []
    async with priv_factory() as s:
        assert (await s.get(Report, rid)).status == ReportStatus.APPROVED

    # Reactivate, then re-run delivery (what the reactivation handler enqueues) → dispatched.
    await _configure(priv_factory, cl.id, status="active")
    await run_delivery(rid, _make_wc(auth_app, priv_factory))
    assert len(payloads) == 1
    async with priv_factory() as s:
        assert (await s.get(Report, rid)).status == ReportStatus.SENT


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resend_unknown_report_404(authed_admin_client, make_client) -> None:
    """Resend on a non-existent report → 404."""
    cl = await make_client()
    resp = await authed_admin_client.post(f"/clients/{cl.id}/reports/999999/resend")
    assert resp.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resend_non_resendable_409(authed_admin_client, make_client, priv_factory) -> None:
    """Resend on a drafted (not-yet-deliverable) report → 409."""
    cl = await make_client()
    rid = await _seed_report(priv_factory, cl.id, status="drafted")
    resp = await authed_admin_client.post(f"/clients/{cl.id}/reports/{rid}/resend")
    assert resp.status_code == 409


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reactivation_handler_enqueues_only_approved_reports(
    auth_app, make_client, priv_factory, monkeypatch
) -> None:
    """on_client_reactivated re-enqueues delivery for each held (approved) report, not others."""
    job_ids: list[str] = []

    async def fake_enqueue(name, **kw):
        job_ids.append(kw["job_id"])

    monkeypatch.setattr("app.delivery.handlers.enqueue", fake_enqueue)

    cl = await make_client()
    r1 = await _seed_report(priv_factory, cl.id, status="approved")
    r2 = await _seed_report(priv_factory, cl.id, status="approved")
    await _seed_report(priv_factory, cl.id, status="delivered")  # not re-enqueued

    handler = make_on_client_reactivated(SimpleNamespace(state=SimpleNamespace(arq=object())))
    event = ClientReactivated(
        actor_id=1, actor_type="human", client_id=None, target_client_id=cl.id
    )
    async with priv_factory() as s:
        async with s.begin():
            await handler(event, s)

    assert sorted(job_ids) == sorted([f"deliver:{r1}", f"deliver:{r2}"])
