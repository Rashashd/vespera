"""Per-transaction Row-Level Security context for the least-privilege runtime role.

set_rls_context writes two transaction-local GUCs read by the tenant_isolation policies
(migration 0011): app.is_staff and app.current_client_id. MUST be called inside an open
transaction, right after it begins, at every session-open site. A session that opens on
pantera_app WITHOUT this call sees zero rows from policied tables (default-deny) — the safe
failure mode (breaks loudly, never leaks).
"""

from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

_SET_STAFF = text("SELECT set_config('app.is_staff', :s, true)")
_SET_CLIENT = text("SELECT set_config('app.current_client_id', :c, true)")


async def set_rls_context(session: AsyncSession, *, client_id: int | None, is_staff: bool) -> None:
    """Set the transaction-local RLS context (is_local=true).

    - Client-user request: ``(client_id=<their id>, is_staff=False)`` → scoped to that client.
    - Staff / system / worker: ``(client_id=None, is_staff=True)`` → sees all clients.
    """
    await session.execute(_SET_STAFF, {"s": "on" if is_staff else "off"})
    await session.execute(_SET_CLIENT, {"c": "" if client_id is None else str(client_id)})


async def set_system_context(session: AsyncSession) -> None:
    """Convenience for non-request sessions (worker/pipeline/lifespan/agent): staff/system."""
    await set_rls_context(session, client_id=None, is_staff=True)


def install_system_rls(engine: AsyncEngine) -> None:
    """Set SYSTEM RLS context on EVERY transaction begin for an all-system engine.

    Use ONLY on the ARQ worker engine, whose sessions are uniformly system/worker context —
    this covers every pipeline session (tasks, runners, indexer, dead-letter) robustly without
    threading set_rls_context through ~30 call sites. NEVER install on an engine that serves
    per-client requests: it would grant is_staff='on' to everyone (a cross-tenant leak). The
    request path (API engine) sets context per-principal instead (auth/dependencies.py).
    """

    @event.listens_for(engine.sync_engine, "begin")
    def _set_system_rls(conn) -> None:  # pragma: no cover - verified against a live DB
        conn.exec_driver_sql("SELECT set_config('app.is_staff', 'on', true)")
        conn.exec_driver_sql("SELECT set_config('app.current_client_id', '', true)")
