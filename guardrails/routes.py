"""Sidecar routes: POST /guard (rail evaluation, auth) and GET /health (liveness, no auth)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from guardrails.core import rails
from guardrails.core.auth import require_service_token
from guardrails.core.logging import get_logger
from guardrails.schemas import GuardRequest, GuardResponse

router = APIRouter()
_log = get_logger(__name__)


@router.get("/health")
async def health() -> dict:
    """Liveness: no auth, no evaluation — answers as soon as the process is up."""
    return {"status": "ok"}


@router.post(
    "/guard",
    dependencies=[Depends(require_service_token)],
    response_model=GuardResponse,
)
async def guard(body: GuardRequest) -> GuardResponse:
    """Evaluate one payload against the platform rails; never echoes the input text or PII."""
    result = rails.evaluate(body.text, body.direction, body.client_id)
    _log.info(
        "guard",
        action=result["action"],
        rail=result["rail"],
        reason=result["reason"],
        direction=body.direction,
        call_site=body.call_site,
        client_id=body.client_id,
    )
    return GuardResponse(**result)
