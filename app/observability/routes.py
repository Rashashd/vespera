"""Cost/usage dashboard endpoint (FR-021/034): GET /clients/{id}/usage."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import acting_client, require_manager
from app.auth.models import User
from app.clients.models import Client
from app.core.dependencies import get_session
from app.observability.models import LlmUsage
from app.observability.schemas import CallSiteBreakdown, CostDashboard

router = APIRouter(prefix="/clients/{client_id}", tags=["observability"])

_get_client_read = acting_client(allow_suspended=True)


@router.get("/usage", response_model=CostDashboard)
async def get_usage_dashboard(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    manager: User = Depends(require_manager),
    client: Client = Depends(_get_client_read),
    session: AsyncSession = Depends(get_session),
) -> CostDashboard:
    """Aggregate llm_usage for the client; zeros on empty (FR-021/034)."""
    q = select(LlmUsage).where(LlmUsage.client_id == client.id)
    if from_:
        q = q.where(LlmUsage.created_at >= from_)
    if to:
        q = q.where(LlmUsage.created_at <= to)

    rows = (await session.execute(q)).scalars().all()

    total_cost = sum((r.cost_usd for r in rows), Decimal("0"))
    total_in = sum(r.input_tokens for r in rows)
    total_out = sum(r.output_tokens for r in rows)

    by_site: dict[str, dict] = {}
    for r in rows:
        site = by_site.setdefault(r.call_site, {"cost": Decimal("0"), "calls": 0})
        site["cost"] += r.cost_usd
        site["calls"] += 1

    return CostDashboard(
        client_id=client.id,
        total_cost_usd=f"{total_cost:.6f}",
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        call_count=len(rows),
        by_call_site={
            k: CallSiteBreakdown(cost_usd=f"{v['cost']:.6f}", calls=v["calls"])
            for k, v in by_site.items()
        },
        window={"from": from_.isoformat() if from_ else None, "to": to.isoformat() if to else None},
    )
