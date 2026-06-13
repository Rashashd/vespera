"""Passive audit handler: records one append-only audit_log row per domain event."""

from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.core.dispatcher import EventDispatcher
from app.domain.events import DomainEvent


def _target_for(event: DomainEvent) -> str:
    """Derive a stable target reference from the event's identifying field."""
    for attr, prefix in (
        ("finding_id", "finding"),
        ("report_id", "report"),
        ("erased_client_id", "client"),
        ("target_user_id", "user"),
        ("user_id", "user"),
        ("run_id", "ingestion_run"),
        ("item_id", "watchlist_item"),
        ("watchlist_id", "watchlist"),
        ("target_client_id", "client"),
    ):
        value = getattr(event, attr, None)
        if value:
            return f"{prefix}:{value}"
    return type(event).__name__


async def audit_log_handler(event: DomainEvent, session: AsyncSession) -> None:
    """Add one audit_log row for the event using the caller's session (atomic; FR-013a)."""
    # Human events link to users.id; system events (sentinel 0) stay unlinked (spec 2, D5).
    actor_user_id = event.actor_id if event.actor_type == "human" else None
    # For cross-client staff events the actor client_id is NULL; record the acted-upon client
    # (target_client_id) so queries can filter by tenant (D11/FR-021).
    effective_client_id = event.client_id or getattr(event, "target_client_id", None)
    session.add(
        AuditLog(
            actor_id=event.actor_id,
            actor_type=event.actor_type,
            actor_user_id=actor_user_id,
            action=type(event).__name__,
            target=_target_for(event),
            event_type=type(event).__name__,
            client_id=effective_client_id,
            payload=asdict(event),
        )
    )


def register_audit_handlers(dispatcher: EventDispatcher) -> None:
    """Register the audit handler for every known domain event subclass."""
    seen: set[type] = set()
    stack = list(DomainEvent.__subclasses__())
    while stack:
        event_type = stack.pop()
        if event_type in seen:
            continue
        seen.add(event_type)
        dispatcher.register(event_type, audit_log_handler)
        stack.extend(event_type.__subclasses__())
