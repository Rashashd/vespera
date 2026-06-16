"""Client (tenant) lifecycle and client-user management (spec 3 + spec 4b)."""

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, UserWatchlistScope
from app.clients._helpers import (
    CrossClientWatchlist,
    NameConflict,
    _try_flush,
    _validate_scope,
)
from app.clients.enums import ClientStatus
from app.clients.models import Client, Watchlist


async def get_client(session: AsyncSession, client_id: int | None) -> Client | None:
    """Fetch a client by id; returns None for None id (staff have no home client)."""
    if client_id is None:
        return None
    return await session.get(Client, client_id)


async def list_clients(session: AsyncSession) -> list[Client]:
    """Return all clients ordered by id (staff roster; FR-013)."""
    return list((await session.scalars(select(Client).order_by(Client.id))).all())


async def rename_client(session: AsyncSession, client: Client, new_name: str) -> Client:
    """Rename a client; the lower(name) unique index enforces platform-wide uniqueness (FR-001)."""
    client.name = new_name.strip()
    session.add(client)
    if not await _try_flush(session):  # name already taken (incl. concurrent race)
        raise NameConflict
    return client


async def create_client(
    session: AsyncSession,
    name: str,
    *,
    report_email_regular: str | None = None,
    report_email_urgent: str | None = None,
    urgent_severity_threshold: str | None = None,
) -> Client:
    """Insert a new active client; the unique index enforces the name (FR-001/FR-011)."""
    client = Client(
        name=name.strip(),
        status=ClientStatus.ACTIVE.value,
        report_email_regular=report_email_regular,
        report_email_urgent=report_email_urgent,
        urgent_severity_threshold=urgent_severity_threshold or "life-threatening",
    )
    session.add(client)
    if not await _try_flush(session):  # name already taken (incl. concurrent race)
        raise NameConflict
    return client


async def set_client_status(session: AsyncSession, client: Client, status: ClientStatus) -> Client:
    """Suspend or reactivate a client (no destructive delete, FR-002/FR-011)."""
    client.status = status.value
    session.add(client)
    await session.flush()
    return client


async def suspend_client(session: AsyncSession, client: Client) -> Client:
    """Set status='suspended'; idempotent (FR-011)."""
    return await set_client_status(session, client, ClientStatus.SUSPENDED)


async def reactivate_client(session: AsyncSession, client: Client) -> Client:
    """Set status='active'; idempotent (FR-011)."""
    return await set_client_status(session, client, ClientStatus.ACTIVE)


async def set_report_emails(
    session: AsyncSession,
    client: Client,
    *,
    report_email_regular: str | None,
    report_email_urgent: str | None,
    urgent_severity_threshold: str | None,
) -> Client:
    """Update delivery addresses; only non-None fields overwrite existing values (FR-017)."""
    if report_email_regular is not None:
        client.report_email_regular = report_email_regular
    if report_email_urgent is not None:
        client.report_email_urgent = report_email_urgent
    if urgent_severity_threshold is not None:
        client.urgent_severity_threshold = urgent_severity_threshold
    session.add(client)
    await session.flush()
    return client


async def set_severity_keywords(
    session: AsyncSession,
    client: Client,
    *,
    keywords: list[str],
) -> Client:
    """Replace the client's custom severity-escalation keyword list (spec 8 FR-004)."""
    # Normalize: trim, drop blanks, de-duplicate case-insensitively while preserving order.
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in keywords:
        kw = raw.strip()
        if kw and kw.lower() not in seen:
            seen.add(kw.lower())
            cleaned.append(kw)
    client.custom_severity_keywords = cleaned
    session.add(client)
    await session.flush()
    return client


async def create_client_user(
    session: AsyncSession,
    client_id: int,
    *,
    email: str,
    hashed_password: str,
    client_scope: str,
    min_severity: str | None,
    watchlist_ids: list[int],
) -> User:
    """Create a client-user; force user_type='client', validate scope + watchlist ownership."""
    _validate_scope(client_scope, min_severity=min_severity, watchlist_ids=watchlist_ids)

    for wl_id in watchlist_ids:
        wl = await session.get(Watchlist, wl_id)
        if wl is None or wl.client_id != client_id:
            raise CrossClientWatchlist

    user = User(
        email=email,
        hashed_password=hashed_password,
        role="client_user",
        user_type="client",
        client_id=client_id,
        client_scope=client_scope,
        min_severity=min_severity,
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    session.add(user)
    await session.flush()

    for wl_id in watchlist_ids:
        stmt = (
            pg_insert(UserWatchlistScope)
            .values(user_id=user.id, watchlist_id=wl_id, client_id=client_id)
            .on_conflict_do_nothing(index_elements=["user_id", "watchlist_id"])
        )
        await session.execute(stmt)

    await session.flush()
    return user


async def list_client_users(session: AsyncSession, client_id: int) -> list[User]:
    """List all client-users belonging to a named client (admin-facing; FR-014)."""
    return list(
        (
            await session.scalars(
                select(User)
                .where(User.client_id == client_id, User.user_type == "client")
                .order_by(User.id)
            )
        ).all()
    )


async def get_client_user(session: AsyncSession, client_id: int, user_id: int) -> User | None:
    """Fetch a client-user scoped to the given client; cross-tenant ⇒ None."""
    user = await session.get(User, user_id)
    if user is None or user.client_id != client_id or user.user_type != "client":
        return None
    return user


async def update_client_user_scope(
    session: AsyncSession,
    user: User,
    *,
    client_scope: str | None,
    min_severity: str | None,
    watchlist_ids: list[int] | None,
    is_active: bool | None,
) -> User:
    """Update scope/active state for a client-user; validate new effective scope (FR-014/FR-015)."""
    new_scope = client_scope if client_scope is not None else user.client_scope
    new_min_sev = min_severity if min_severity is not None else user.min_severity
    new_wl_ids = (
        watchlist_ids
        if watchlist_ids is not None
        else [ws.watchlist_id for ws in user.watchlist_scopes]
    )

    if new_scope is not None:
        _validate_scope(new_scope, min_severity=new_min_sev, watchlist_ids=new_wl_ids)

    for wl_id in new_wl_ids:
        wl = await session.get(Watchlist, wl_id)
        if wl is None or wl.client_id != user.client_id:
            raise CrossClientWatchlist

    if client_scope is not None:
        user.client_scope = client_scope
    if min_severity is not None:
        user.min_severity = min_severity
    if is_active is not None:
        user.is_active = is_active

    session.add(user)
    await session.flush()

    if watchlist_ids is not None:
        await session.execute(
            delete(UserWatchlistScope).where(UserWatchlistScope.user_id == user.id)
        )
        for wl_id in watchlist_ids:
            stmt = (
                pg_insert(UserWatchlistScope)
                .values(user_id=user.id, watchlist_id=wl_id, client_id=user.client_id)
                .on_conflict_do_nothing(index_elements=["user_id", "watchlist_id"])
            )
            await session.execute(stmt)
        await session.flush()
        await session.refresh(user)

    return user
