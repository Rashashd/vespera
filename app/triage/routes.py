"""FastAPI route: GET /clients/{client_id}/findings/{finding_id} (FR-013)."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select

from app.auth.dependencies import get_acting_client
from app.clients.models import Client
from app.db.rls import set_rls_context
from app.triage.models import Finding
from app.triage.schemas import FindingStateResponse

router = APIRouter(prefix="/clients/{client_id}", tags=["triage"])
_log = structlog.get_logger(__name__)


@router.get(
    "/findings/{finding_id}",
    response_model=FindingStateResponse,
    status_code=status.HTTP_200_OK,
)
async def get_finding(
    request: Request,
    finding_id: int,
    target: Client = Depends(get_acting_client),
) -> FindingStateResponse:
    """Return triage state for a single finding (client-scoped; 404 on cross-tenant access).

    Suspended clients are refused by get_acting_client (400 CLIENT_SUSPENDED).
    """
    session_factory = request.app.state.session_factory
    log = _log.bind(client_id=target.id, finding_id=finding_id)

    async with session_factory() as session:
        await set_rls_context(session, client_id=target.id, is_staff=False)
        result = await session.execute(
            select(Finding).where(
                Finding.id == finding_id,
                Finding.client_id == target.id,
            )
        )
        finding = result.scalar_one_or_none()

    if finding is None:
        log.info("triage.get_finding.not_found")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FINDING_NOT_FOUND")

    log.info("triage.get_finding.ok", bucket=finding.bucket)
    return FindingStateResponse.model_validate(finding)
