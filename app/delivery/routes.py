"""HTTP routes for the delivery callback, staff re-send, and report download (spec 13)."""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import acting_client, require_admin
from app.auth.models import User
from app.clients.models import Client
from app.core.dependencies import get_session
from app.db.rls import set_rls_context
from app.delivery import service as svc
from app.delivery.n8n_client import N8nClient
from app.delivery.rendering import render_report_document
from app.reports.enums import ReportStatus
from app.reports.models import Report
from app.reports.schemas import ReportSummary

router = APIRouter(prefix="/clients/{client_id}", tags=["delivery"])

_get_client = acting_client()
_get_client_read = acting_client(allow_suspended=True)

# The downloadable artifact is the delivered document; only meaningful from approval onward.
_DOWNLOADABLE = {ReportStatus.APPROVED, ReportStatus.SENT, ReportStatus.DELIVERED}

# Reports for which a re-send is meaningful (a held release, a retry, or a failed channel).
_RESENDABLE = {ReportStatus.APPROVED, ReportStatus.SENT, ReportStatus.DELIVERY_FAILED}


class DeliveryCallbackRequest(BaseModel):
    """n8n → backend per-channel delivery confirmation."""

    channel: Literal["email", "sftp"]
    outcome: Literal["delivered", "failed"]
    delivered_at: datetime | None = None
    error: str | None = None


class DeliveryCallbackResponse(BaseModel):
    """Result of a delivery callback (the recomputed overall report status)."""

    report_status: ReportStatus


@router.post(
    "/reports/{report_id}/delivery-callback",
    response_model=DeliveryCallbackResponse,
)
async def delivery_callback(
    client_id: int,
    report_id: int,
    body: DeliveryCallbackRequest,
    request: Request,
    x_delivery_token: str | None = Header(default=None, alias="X-Delivery-Token"),
    session: AsyncSession = Depends(get_session),
) -> DeliveryCallbackResponse:
    """Confirm a per-channel delivery outcome (service-token auth — bypasses user JWT).

    Authenticated ONLY by the shared X-Delivery-Token (constant-time compare). Idempotent per
    (report, channel); an unknown dispatch is rejected 404. Never reveals report content.
    """
    expected = request.app.state.settings.delivery_callback_token
    if (
        not expected
        or not x_delivery_token
        or not secrets.compare_digest(x_delivery_token, expected)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="INVALID_DELIVERY_TOKEN")

    # No request principal on this path → set the per-client RLS context explicitly so the
    # policied reports/delivery_attempt rows are reachable (and scoped to this client).
    await set_rls_context(session, client_id=client_id, is_staff=False)

    try:
        report_status = await svc.handle_callback(
            session,
            client_id=client_id,
            report_id=report_id,
            channel=body.channel,
            outcome=body.outcome,
            delivered_at=body.delivered_at,
            error=body.error,
            dispatcher=request.app.state.dispatcher,
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="UNKNOWN_DISPATCH") from exc

    return DeliveryCallbackResponse(report_status=report_status)


@router.post("/reports/{report_id}/resend", response_model=ReportSummary)
async def resend_report(
    report_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    client=Depends(_get_client),
    session: AsyncSession = Depends(get_session),
) -> ReportSummary:
    """Re-dispatch the unconfirmed/failed channels of a report (admin/manager only — FR-006).

    Used for delivery_failed reports and to release a report held by a previously-missing
    channel. Never re-sends a confirmed channel. 409 when there is nothing to re-send.
    """
    report = await session.get(Report, report_id)
    if report is None or report.client_id != client.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="REPORT_NOT_FOUND")
    if ReportStatus(report.status) not in _RESENDABLE:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="NOTHING_TO_RESEND")

    n8n = N8nClient.from_settings(request.app.state.settings)
    await svc.dispatch_report(
        session,
        report,
        client,
        n8n=n8n,
        dispatcher=request.app.state.dispatcher,
        token=request.app.state.settings.delivery_callback_token,
        resend=True,
        actor_id=admin.id,
        actor_type="human",
    )
    await session.flush()
    await session.refresh(report)
    return ReportSummary.model_validate(report)


@router.get("/reports/{report_id}/download")
async def download_report(
    report_id: int,
    client: Client = Depends(_get_client_read),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Return the rendered report document (FR-017) — the same artifact delivered to the client.

    A client-user may download only their own approved/sent/delivered reports (acting_client
    enforces ownership; another client's user → 404). Staff download for the acting client.
    """
    report = await session.get(Report, report_id)
    if (
        report is None
        or report.client_id != client.id
        or ReportStatus(report.status) not in _DOWNLOADABLE
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="REPORT_NOT_FOUND")

    document = render_report_document(report, await svc._included_findings(session, report))
    return Response(
        content=document,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="report-{report_id}.html"'},
    )
