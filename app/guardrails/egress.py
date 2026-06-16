"""Egress guard helper: redact-then-guard wrapper with fail-safe audit emission.

Each guarded site calls guard_text() before and after its external-LLM call (or once at
document intake). On a blocking rail or sidecar outage it emits the audit event on the
caller's session (atomic) and raises so the site applies its fail-safe (triage/agent
escalate; intake quarantine). Disabled only in tests via settings.guardrails_enabled —
production boot refuses that toggle (startup.check_security_boundary).
"""

from __future__ import annotations

from app.core.config import Settings
from app.core.dispatcher import EventDispatcher
from app.domain.events import GuardrailRefused, GuardrailUnavailable
from app.guardrails.client import GuardrailsClient, GuardrailsUnavailable

# Fail-safe action per call site (recorded on the GuardrailUnavailable audit row).
_FAIL_ACTION = {"triage": "escalate", "agent": "escalate", "intake": "quarantine"}


class GuardBlocked(Exception):
    """A rail blocked the payload; the call site converts this to its fail-safe."""

    def __init__(self, rail: str | None, direction: str) -> None:
        super().__init__(f"guardrail blocked ({rail}, {direction})")
        self.rail = rail
        self.direction = direction


async def guard_text(
    settings: Settings,
    *,
    text: str,
    direction: str,
    client_id: int,
    call_site: str,
    session: object | None = None,
    dispatcher: EventDispatcher | None = None,
) -> None:
    """Guard one payload. No-op if disabled (test-only). Emit audit + raise on block/outage."""
    if not settings.guardrails_enabled:
        return
    try:
        async with GuardrailsClient.from_settings(settings) as client:
            response = await client.guard(text, direction, client_id, call_site)
    except GuardrailsUnavailable:
        await _emit(
            GuardrailUnavailable(
                actor_id=0,
                actor_type="system",
                client_id=client_id,
                call_site=call_site,
                fail_action=_FAIL_ACTION.get(call_site, "escalate"),
            ),
            session,
            dispatcher,
        )
        raise
    if response.action == "block":
        await _emit(
            GuardrailRefused(
                actor_id=0,
                actor_type="system",
                client_id=client_id,
                rail=response.rail or "",
                call_site=call_site,
                direction=direction,
            ),
            session,
            dispatcher,
        )
        raise GuardBlocked(response.rail, direction)


async def _emit(event: object, session: object | None, dispatcher: EventDispatcher | None) -> None:
    """Dispatch an audit event on the caller's session when both are available."""
    from sqlalchemy.ext.asyncio import AsyncSession

    if dispatcher is not None and isinstance(session, AsyncSession):
        await dispatcher.dispatch(event, session)
