"""Budget gate for scheduled cycle stages (spec 11 FR-019a/FR-019b/Constitution III)."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

_log = structlog.get_logger(__name__)

_SYSTEM_ACTOR_ID = 0
_SYSTEM_ACTOR_TYPE = "system"


async def gate(
    session: AsyncSession,
    watchlist_id: int,
    client_id: int,
    dispatcher: Any,
) -> str:
    """Return the effective policy string for the current cycle's drafting stages.

    Returns one of: "continue" | "critical_only" | "pause".

    Constitution III: detection/escalation/alerting (triage) are NEVER gated — only
    drafting steps (expedited, consolidation). Callers must only gate drafting.

    Budget state is per-UTC-month via derive_budget_state/read_figures.
    WatchlistBudgetThresholdReached is dispatched on warning/exceeded transitions.
    """
    from app.clients.models import Watchlist
    from app.clients.watchlists import read_figures
    from app.domain.events import WatchlistBudgetThresholdReached

    watchlist = await session.get(Watchlist, watchlist_id)
    if watchlist is None:
        return "continue"

    budget_status, _spend = await read_figures(session, watchlist)
    policy = watchlist.budget_exceeded_policy  # "continue" | "critical_only" | "pause"

    if budget_status in ("warning", "soft_capped"):
        # Dispatch budget threshold event (FR-019c) — idempotent; handler is passive (audit only)
        await dispatcher.dispatch(
            WatchlistBudgetThresholdReached(
                actor_id=_SYSTEM_ACTOR_ID,
                actor_type=_SYSTEM_ACTOR_TYPE,
                client_id=client_id,
                watchlist_id=watchlist_id,
                state=budget_status,
            ),
            session,
        )

    # Apply policy only when budget exceeded (soft_capped = at or above cap)
    if budget_status == "soft_capped":
        _log.info(
            "budget.gate",
            watchlist_id=watchlist_id,
            budget_status=budget_status,
            policy=policy,
        )
        return policy  # "continue" | "critical_only" | "pause"

    return "continue"
