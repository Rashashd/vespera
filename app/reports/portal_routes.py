"""Portal report read path (FR-030) and per-report findings endpoint (FR-031).

Router registered once in main.py; T051 extends this file with portal routes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import acting_client, current_active_principal
from app.auth.models import User
from app.auth.schemas import UserType
from app.clients.models import Client
from app.core.dependencies import get_session
from app.ingestion.models import DocumentWatchlist
from app.reports import service as report_service
from app.reports.models import Report, ReportFinding
from app.reports.schemas import (
    PortalReportDetail,
    PortalReportSummary,
    ReportFindingDetail,
)
from app.triage.models import Finding

router = APIRouter(prefix="/clients/{client_id}", tags=["portal"])

_get_client_read = acting_client(allow_suspended=True)

_PORTAL_STATUSES = {"approved", "sent", "delivered"}


async def _resolve_owning_watchlist(
    session: AsyncSession, report_id: int, client_id: int
) -> int | None:
    """Attribute a report lacking a direct watchlist_id to a single owning watchlist (FR-030).

    Resolves via report_findings → findings.document_id → document_watchlists, picking the
    lowest watchlist_id deterministically (consistent with spec-9 report-once attribution).
    """
    return (
        await session.execute(
            select(DocumentWatchlist.watchlist_id)
            .join(Finding, Finding.document_id == DocumentWatchlist.document_id)
            .join(ReportFinding, ReportFinding.finding_id == Finding.id)
            .where(
                ReportFinding.report_id == report_id,
                DocumentWatchlist.client_id == client_id,
            )
            .order_by(DocumentWatchlist.watchlist_id.asc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _delivery_status(status: str) -> str:
    """Derive delivery_status label from report status (FR-006b)."""
    if status == "approved":
        return "approved_pending_delivery"
    if status in ("sent", "delivered"):
        return status
    return "approved_pending_delivery"


# ── FR-031: per-report findings (used by reviewer batch UI + portal detail) ──


@router.get(
    "/reports/{report_id}/findings",
    response_model=list[ReportFindingDetail],
)
async def list_report_findings(
    report_id: int,
    principal: User = Depends(current_active_principal),
    client: Client = Depends(_get_client_read),
    session: AsyncSession = Depends(get_session),
) -> list[ReportFindingDetail]:
    """Return all findings for a report (reviewer + client-user via acting_client).

    Client-users may only read findings of approved+sent reports (FR-030) — never in-workflow
    (drafted/under_review/rejected/discarded) reports. Staff (reviewer/admin/manager) see all.
    """
    report = await session.get(Report, report_id)
    if report is None or report.client_id != client.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="REPORT_NOT_FOUND")

    # Per-client object-level authz: client-users are restricted to portal-visible statuses.
    if principal.user_type == UserType.CLIENT.value and report.status not in _PORTAL_STATUSES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="REPORT_NOT_FOUND")

    rows = (
        await session.execute(
            select(ReportFinding, Finding)
            .join(Finding, ReportFinding.finding_id == Finding.id)
            .where(ReportFinding.report_id == report_id)
        )
    ).all()

    return [
        ReportFindingDetail(
            id=rf.id,
            report_id=rf.report_id,
            finding_id=rf.finding_id,
            drug=f.drug,
            reaction=f.reaction,
            bucket=f.bucket,
            state=rf.state,
            created_at=rf.created_at,
        )
        for rf, f in rows
    ]


# ── FR-030: client portal report list + detail ────────────────────────────────


@router.get(
    "/portal/reports",
    response_model=list[PortalReportSummary],
)
async def list_portal_reports(
    watchlist_id: int | None = Query(None),
    principal: User = Depends(current_active_principal),
    client: Client = Depends(_get_client_read),
    session: AsyncSession = Depends(get_session),
) -> list[PortalReportSummary]:
    """List approved+sent reports for the client portal, optionally filtered by watchlist.

    Reports without a direct watchlist_id (e.g. expedited) are attributed to a single owning
    watchlist via document_watchlists (FR-030) so they appear under exactly one watchlist page.
    """
    rows = (
        (
            await session.execute(
                select(Report)
                .where(
                    Report.client_id == client.id,
                    Report.status.in_(list(_PORTAL_STATUSES)),
                )
                .order_by(Report.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    # Clinical severity per report (highest-severity included finding) in one extra query.
    severity_by_report = await report_service.severity_by_report(session, [r.id for r in rows])

    summaries: list[PortalReportSummary] = []
    for r in rows:
        effective_wl = r.watchlist_id
        if effective_wl is None:
            effective_wl = await _resolve_owning_watchlist(session, r.id, client.id)
        # Apply the watchlist filter against the *effective* (possibly resolved) watchlist.
        if watchlist_id is not None and effective_wl != watchlist_id:
            continue
        summaries.append(
            PortalReportSummary(
                id=r.id,
                report_type=r.report_type,
                status=r.status,
                severity=severity_by_report.get(r.id),
                watchlist_id=effective_wl,
                corroboration_count=r.corroboration_count,
                sla_deadline=r.sla_deadline,
                cycle_period_start=r.cycle_period_start,
                cycle_period_end=r.cycle_period_end,
                created_at=r.created_at,
                updated_at=r.updated_at,
                delivery_status=_delivery_status(r.status),
            )
        )
    return summaries


@router.get(
    "/portal/reports/{report_id}",
    response_model=PortalReportDetail,
)
async def get_portal_report(
    report_id: int,
    principal: User = Depends(current_active_principal),
    client: Client = Depends(_get_client_read),
    session: AsyncSession = Depends(get_session),
) -> PortalReportDetail:
    """Return portal-safe full report; 404 when not approved-or-later or wrong client."""
    report = await session.get(Report, report_id)
    if report is None or report.client_id != client.id or report.status not in _PORTAL_STATUSES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="REPORT_NOT_FOUND")

    return PortalReportDetail(
        id=report.id,
        client_id=report.client_id,
        report_type=report.report_type,
        status=report.status,
        delivery_status=_delivery_status(report.status),
        watchlist_id=report.watchlist_id,
        corroboration_count=report.corroboration_count,
        sla_deadline=report.sla_deadline,
        cycle_period_start=report.cycle_period_start,
        cycle_period_end=report.cycle_period_end,
        created_at=report.created_at,
        updated_at=report.updated_at,
        structured_fields=report.structured_fields,
        draft_body=report.draft_body,
        corroboration_sources=report.corroboration_sources,
    )
