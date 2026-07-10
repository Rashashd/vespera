"""Pure delivery-channel helpers: channel resolution, status derivation, and n8n payload.

Side-effect-free functions shared by ``app/delivery/service.py`` — separated from the
stateful dispatch/callback orchestration so each concern stays under the file-size limit.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.clients.models import Client
from app.reports.enums import ReportStatus, ReportType
from app.reports.models import Report


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


def build_payload(
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
