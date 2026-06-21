"""Delivery domain service: channel resolution, dispatch, attempt tracking, status derivation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.models import Client
from app.delivery.models import DeliveryAttempt
from app.delivery.n8n_client import N8nClient, N8nDeliveryError
from app.delivery.rendering import render_report_document
from app.domain.events import (
    ReportDelivered,
    ReportDeliveryFailed,
    ReportDeliveryHeld,
    ReportDispatched,
    ReportResent,
)
from app.redaction.recognizers import scrub_text
from app.reports.enums import ReportStatus, ReportType
from app.reports.models import Report, ReportFinding
from app.triage.models import Finding

_log = structlog.get_logger(__name__)
_SYSTEM_ACTOR_ID = 0
_SYSTEM_ACTOR_TYPE = "system"


def _now() -> datetime:
    return datetime.now(UTC)


def _scrub(value: str | None) -> str | None:
    """Scrub a free-text error/reason for safe persistence (PII-free; ≤500 chars)."""
    if not value:
        return None
    return scrub_text(value)[:500] or None


@dataclass(frozen=True, slots=True)
class ChannelTarget:
    """One configured delivery channel for a report."""

    channel: str  # "email" | "sftp"
    recipient_kind: str | None  # "regular" | "urgent" for email; None for sftp
    recipient: str  # email address, or "host:path" for sftp (display only)


def resolve_channels(report: Report, client: Client) -> list[ChannelTarget]:
    """Configured channels for a report (FR-003): email by urgency + SFTP if enabled."""
    targets: list[ChannelTarget] = []
    if ReportType(report.report_type) == ReportType.EXPEDITED:
        address, kind = client.report_email_urgent, "urgent"
    else:
        address, kind = client.report_email_regular, "regular"
    if address:
        targets.append(ChannelTarget("email", kind, address))
    if client.sftp_enabled and client.sftp_host and client.sftp_path:
        targets.append(ChannelTarget("sftp", None, f"{client.sftp_host}:{client.sftp_path}"))
    return targets


def derive_report_status(attempt_statuses: Iterable[str]) -> ReportStatus | None:
    """Overall report delivery status from its per-channel attempts (D2/FR-004a).

    delivered = every attempt delivered; delivery_failed = any attempt failed; otherwise sent.
    Returns None when there are no attempts (nothing dispatched yet).
    """
    statuses = list(attempt_statuses)
    if not statuses:
        return None
    if any(s == "failed" for s in statuses):
        return ReportStatus.DELIVERY_FAILED
    if all(s == "delivered" for s in statuses):
        return ReportStatus.DELIVERED
    return ReportStatus.SENT


async def _load_attempts(session: AsyncSession, report_id: int) -> list[DeliveryAttempt]:
    return list(
        (
            await session.execute(
                select(DeliveryAttempt).where(DeliveryAttempt.report_id == report_id)
            )
        )
        .scalars()
        .all()
    )


async def _included_findings(session: AsyncSession, report: Report) -> list[dict]:
    """Included findings (drug/reaction/bucket) for rendering a batch report's body."""
    rows = (
        await session.execute(
            select(ReportFinding, Finding)
            .join(Finding, ReportFinding.finding_id == Finding.id)
            .where(
                ReportFinding.report_id == report.id,
                ReportFinding.state == "included",
            )
        )
    ).all()
    return [
        {"drug": f.drug, "reaction": f.reaction, "bucket": f.bucket, "state": rf.state}
        for rf, f in rows
    ]


def _payload(
    report: Report, client: Client, target: ChannelTarget, document: str, token: str
) -> dict:
    """Build the backend→n8n send payload (contract §n8n outbound)."""
    payload: dict[str, Any] = {
        "report_id": report.id,
        "client_id": report.client_id,
        "channel": target.channel,
        "document": document,
        "callback_url": (f"/clients/{report.client_id}/reports/{report.id}/delivery-callback"),
        "callback_token": token,
    }
    if target.channel == "email":
        payload["recipient"] = target.recipient
    else:
        # SFTP credential lives in n8n; the app sends destination metadata only (D7).
        payload["sftp_ref"] = {
            "host": client.sftp_host,
            "path": client.sftp_path,
            "username": client.sftp_username,
        }
    return payload


async def _hold(
    session: AsyncSession,
    report: Report,
    dispatcher: Any,
    *,
    reason: str,
    actor_id: int,
    actor_type: str,
) -> None:
    """Hold a report approved-pending-delivery (no configured channel / suspended client)."""
    report.updated_at = _now()
    await dispatcher.dispatch(
        ReportDeliveryHeld(
            actor_id=actor_id,
            actor_type=actor_type,
            client_id=report.client_id,
            report_id=report.id,
            reason=reason,
        ),
        session,
    )
    _log.info("delivery.held", report_id=report.id, reason=reason)


async def _finalize_status(
    session: AsyncSession,
    report: Report,
    dispatcher: Any,
    *,
    actor_id: int,
    actor_type: str,
) -> ReportStatus:
    """Recompute report status from its attempts; set timestamps; emit transition events once."""
    attempts = await _load_attempts(session, report.id)
    new_status = derive_report_status(a.status for a in attempts) or ReportStatus.SENT
    old_status = report.status
    report.status = new_status
    report.updated_at = _now()

    if new_status == ReportStatus.DELIVERED:
        confirmed = [a.confirmed_at for a in attempts if a.confirmed_at]
        report.delivered_at = max(confirmed) if confirmed else _now()
        if old_status != ReportStatus.DELIVERED:
            await dispatcher.dispatch(
                ReportDelivered(
                    actor_id=actor_id,
                    actor_type=actor_type,
                    client_id=report.client_id,
                    report_id=report.id,
                ),
                session,
            )
    elif new_status == ReportStatus.DELIVERY_FAILED:
        failed = next((a for a in attempts if a.status == "failed"), None)
        report.delivery_failed_at = _now()
        report.delivery_error = _scrub(failed.error if failed else None)
        if old_status != ReportStatus.DELIVERY_FAILED:
            await dispatcher.dispatch(
                ReportDeliveryFailed(
                    actor_id=actor_id,
                    actor_type=actor_type,
                    client_id=report.client_id,
                    report_id=report.id,
                    channel=failed.channel if failed else "",
                    reason=report.delivery_error or "",
                ),
                session,
            )
    return new_status


async def dispatch_report(
    session: AsyncSession,
    report: Report,
    client: Client,
    *,
    n8n: N8nClient,
    dispatcher: Any,
    token: str,
    resend: bool = False,
    actor_id: int = _SYSTEM_ACTOR_ID,
    actor_type: str = _SYSTEM_ACTOR_TYPE,
) -> ReportStatus | str:
    """Render + dispatch a report to its configured channels; returns the resulting status.

    Holds (returns "held") when the client is suspended or no channel is configured. On resend,
    a confirmed channel is never re-sent. Per-channel send failures mark that attempt failed and
    are reflected in the derived report status (delivered=all / failed=any / sent=otherwise).
    """
    if client.status != "active":
        await _hold(
            session,
            report,
            dispatcher,
            reason="suspended",
            actor_id=actor_id,
            actor_type=actor_type,
        )
        return "held"

    targets = resolve_channels(report, client)
    if not targets:
        await _hold(
            session,
            report,
            dispatcher,
            reason="no_channel",
            actor_id=actor_id,
            actor_type=actor_type,
        )
        return "held"

    # No routing webhook configured → hold approved-pending-delivery rather than failing every
    # attempt (FR-002/003 graceful degradation; the report re-dispatches once n8n is wired).
    if not n8n.configured:
        await _hold(
            session,
            report,
            dispatcher,
            reason="unconfigured",
            actor_id=actor_id,
            actor_type=actor_type,
        )
        return "held"

    existing = {a.channel: a for a in await _load_attempts(session, report.id)}
    document = render_report_document(report, await _included_findings(session, report))

    dispatched: list[str] = []
    for target in targets:
        attempt = existing.get(target.channel)
        if resend and attempt is not None and attempt.status == "delivered":
            continue  # FR-006: never re-send a confirmed channel
        if attempt is None:
            attempt = DeliveryAttempt(
                report_id=report.id, client_id=report.client_id, channel=target.channel
            )
            session.add(attempt)
        attempt.recipient_kind = target.recipient_kind
        attempt.status = "pending"
        attempt.error = None
        attempt.dispatched_at = _now()
        attempt.confirmed_at = None
        await session.flush()
        try:
            await n8n.send(_payload(report, client, target, document, token))
            dispatched.append(target.channel)
        except N8nDeliveryError as exc:
            attempt.status = "failed"
            attempt.error = _scrub(str(exc))
            attempt.confirmed_at = _now()
            _log.warning("delivery.dispatch_failed", report_id=report.id, channel=target.channel)

    report.sent_at = _now()
    event = ReportResent if resend else ReportDispatched
    await dispatcher.dispatch(
        event(
            actor_id=actor_id,
            actor_type=actor_type,
            client_id=report.client_id,
            report_id=report.id,
            channels=dispatched,
        ),
        session,
    )
    return await _finalize_status(
        session, report, dispatcher, actor_id=actor_id, actor_type=actor_type
    )


async def handle_callback(
    session: AsyncSession,
    *,
    client_id: int,
    report_id: int,
    channel: str,
    outcome: str,
    delivered_at: datetime | None,
    error: str | None,
    dispatcher: Any,
    actor_id: int = _SYSTEM_ACTOR_ID,
    actor_type: str = _SYSTEM_ACTOR_TYPE,
) -> ReportStatus:
    """Apply an n8n delivery callback to the matching attempt; recompute report status.

    Idempotent: a callback for an already-final attempt is a no-op. Raises LookupError when no
    dispatched attempt exists for (report_id, channel) under this client (unknown dispatch → 404).
    """
    report = await session.get(Report, report_id)
    if report is None or report.client_id != client_id:
        raise LookupError("unknown report")

    attempt = (
        await session.execute(
            select(DeliveryAttempt).where(
                DeliveryAttempt.report_id == report_id,
                DeliveryAttempt.channel == channel,
                DeliveryAttempt.client_id == client_id,
            )
        )
    ).scalar_one_or_none()
    if attempt is None:
        raise LookupError("unknown dispatch")

    # Idempotent: a late/duplicate callback on a finalized attempt does not flip it.
    if attempt.status in ("delivered", "failed"):
        return ReportStatus(report.status)

    if outcome == "delivered":
        attempt.status = "delivered"
        attempt.confirmed_at = delivered_at or _now()
        attempt.error = None
    else:
        attempt.status = "failed"
        attempt.confirmed_at = _now()
        attempt.error = _scrub(error)
    await session.flush()

    return await _finalize_status(
        session, report, dispatcher, actor_id=actor_id, actor_type=actor_type
    )


async def mark_no_callback_failed(
    session: AsyncSession,
    report: Report,
    dispatcher: Any,
    *,
    actor_id: int = _SYSTEM_ACTOR_ID,
    actor_type: str = _SYSTEM_ACTOR_TYPE,
) -> ReportStatus:
    """Flip a stale `sent` report to delivery_failed when no callback arrived (FR-006a)."""
    for attempt in await _load_attempts(session, report.id):
        if attempt.status == "pending":
            attempt.status = "failed"
            attempt.confirmed_at = _now()
            attempt.error = "no delivery callback within window"
    return await _finalize_status(
        session, report, dispatcher, actor_id=actor_id, actor_type=actor_type
    )


def resend_channels_remaining(attempts: Iterable[DeliveryAttempt]) -> bool:
    """Whether any channel is still re-sendable (not delivered) — else nothing to re-send."""
    return any(a.status != "delivered" for a in attempts)


async def run_delivery(report_id: int, wc: Any, *, resend: bool = False) -> None:
    """Durable job body: load an approved report and dispatch it (worker session = system RLS).

    Enforces the HITL gate at send time — only an `approved` report is dispatched (a held report
    stays `approved`, so reactivation re-enqueue re-enters here correctly).
    """
    n8n = N8nClient.from_settings(wc.settings)
    async with wc.session_factory() as session:
        async with session.begin():
            report = await session.get(Report, report_id)
            if report is None:
                return
            if ReportStatus(report.status) != ReportStatus.APPROVED:
                _log.info("delivery.skip_non_approved", report_id=report_id, status=report.status)
                return
            client = await session.get(Client, report.client_id)
            if client is None:
                return
            await dispatch_report(
                session,
                report,
                client,
                n8n=n8n,
                dispatcher=wc.dispatcher,
                token=wc.settings.delivery_callback_token,
                resend=resend,
            )
