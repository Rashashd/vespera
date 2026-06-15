"""Best-effort LLM usage recorder; write failures are logged and swallowed (FR-033)."""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.observability.models import LlmUsage
from app.observability.pricing import compute_cost

_log = structlog.get_logger(__name__)


async def record_usage(
    *,
    session: AsyncSession,
    settings: Settings,
    call_site: str,
    model: str,
    client_id: int,
    input_tokens: int,
    output_tokens: int,
    finding_id: int | None = None,
) -> None:
    """Write one llm_usage row; silently absorbs any error (FR-033)."""
    try:
        cost = compute_cost(model, input_tokens, output_tokens, settings)
        row = LlmUsage(
            client_id=client_id,
            finding_id=finding_id,
            call_site=call_site,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
        session.add(row)
        await session.flush()
    except Exception as exc:
        _log.warning(
            "observability.usage.write_failed",
            call_site=call_site,
            client_id=client_id,
            reason=str(exc),
        )
