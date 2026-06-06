"""In-process domain-event dispatcher (synchronous, runs within the caller's transaction)."""

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

# A handler receives the event and the active session so its writes share the transaction.
Handler = Callable[[Any, AsyncSession], Awaitable[None]]


class EventDispatcher:
    """Dispatches events to handlers within the caller's transaction (atomic audit)."""

    def __init__(self) -> None:
        self._handlers: dict[type, list[Handler]] = defaultdict(list)

    def register(self, event_type: type, handler: Handler) -> None:
        """Register a handler for an event type."""
        self._handlers[event_type].append(handler)

    async def dispatch(self, event: Any, session: AsyncSession) -> None:
        """Invoke every handler registered for the event's type, in registration order."""
        for handler in self._handlers[type(event)]:
            await handler(event, session)
