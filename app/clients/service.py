"""Client/watchlist queries, validation, and pure budget-state derivation (keeps routes thin)."""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.enums import ClientStatus
from app.clients.models import Client, Watchlist, WatchlistBudgetUsage, WatchlistItem

# Fixed warning threshold: spend at or above 80% of budget warns before the soft cap (FR-010, D12).
WARNING_FRACTION = Decimal("0.80")


class NameConflict(Exception):
    """Raised when a client/watchlist name collides (case-insensitive) → 409."""


class WatchlistEmpty(Exception):
    """Raised when an operation would leave an active watchlist with zero items → 400 (FR-016)."""


# --- Pure helpers ------------------------------------------------------------


def current_period_start() -> date:
    """First day of the current UTC calendar month — the budget period boundary (research D4)."""
    now = datetime.now(UTC)
    return date(now.year, now.month, 1)


def derive_budget_state(budget: Decimal | None, spend: Decimal) -> str:
    """Derive budget state from cap and current-period spend; null budget ⇒ always ok (D4)."""
    if budget is None:
        return "ok"
    if spend >= budget:
        return "soft_capped"
    if spend >= WARNING_FRACTION * budget:
        return "warning"
    return "ok"


def _normalize(value: str) -> str:
    """Idempotency key for an item value: trimmed and lowercased."""
    return value.strip().lower()


async def _try_flush(session: AsyncSession) -> bool:
    """Flush inside a savepoint; return False on a unique violation (race-safe).

    The DB unique indexes are the real guard; this turns a lost concurrent race into a clean
    caller decision (409 / idempotent no-op) instead of an unhandled 500.
    """
    try:
        async with session.begin_nested():
            await session.flush()
        return True
    except IntegrityError:
        return False


# --- Client queries ----------------------------------------------------------


async def get_client(session: AsyncSession, client_id: int) -> Client | None:
    """Fetch a client by id (the caller's own; cross-tenant access is structurally impossible)."""
    return await session.get(Client, client_id)


async def rename_client(session: AsyncSession, client: Client, new_name: str) -> Client:
    """Rename a client; the lower(name) unique index enforces platform-wide uniqueness (FR-001)."""
    client.name = new_name.strip()
    session.add(client)
    if not await _try_flush(session):  # name already taken (incl. concurrent race)
        raise NameConflict
    return client


async def create_client(session: AsyncSession, name: str) -> Client:
    """Insert a new active client (operator path); the unique index enforces the name (FR-001)."""
    client = Client(name=name.strip(), status=ClientStatus.ACTIVE.value)
    session.add(client)
    if not await _try_flush(session):  # name already taken (incl. concurrent race)
        raise NameConflict
    return client


async def set_client_status(session: AsyncSession, client: Client, status: ClientStatus) -> Client:
    """Suspend or reactivate a client (operator path; no destructive delete, FR-002)."""
    client.status = status.value
    session.add(client)
    await session.flush()
    return client


# --- Watchlist queries -------------------------------------------------------


async def get_watchlist(
    session: AsyncSession, client_id: int, watchlist_id: int
) -> Watchlist | None:
    """Fetch a watchlist scoped to the caller's client; cross-tenant ⇒ None (404, SC-003)."""
    watchlist = await session.get(Watchlist, watchlist_id)
    if watchlist is None or watchlist.client_id != client_id:
        return None
    return watchlist


async def list_watchlists(
    session: AsyncSession,
    client_id: int,
    *,
    include_inactive: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[Watchlist]:
    """List the caller's client's watchlists, newest-id last (SC-003)."""
    stmt = select(Watchlist).where(Watchlist.client_id == client_id)
    if not include_inactive:
        stmt = stmt.where(Watchlist.is_active.is_(True))
    stmt = stmt.order_by(Watchlist.id).limit(limit).offset(offset)
    return list((await session.scalars(stmt)).all())


def _dedup_items(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """De-duplicate (item_type, value) pairs by their normalized key (FR-005), preserving order."""
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for item_type, value in items:
        key = (item_type, _normalize(value))
        if key in seen:
            continue
        seen.add(key)
        result.append((item_type, value))
    return result


async def create_watchlist(
    session: AsyncSession,
    client_id: int,
    *,
    name: str,
    cadence: str,
    severity_threshold: str,
    budget_amount: Decimal | None,
    items: list[tuple[str, str]],
) -> Watchlist:
    """Create a watchlist with ≥1 de-duplicated item; the unique index enforces the name."""
    deduped = _dedup_items(items)
    if not deduped:
        raise WatchlistEmpty
    watchlist = Watchlist(
        client_id=client_id,
        name=name.strip(),
        cadence=cadence,
        severity_threshold=severity_threshold,
        budget_amount=budget_amount,
        is_active=True,
    )
    for item_type, value in deduped:
        watchlist.items.append(
            WatchlistItem(
                client_id=client_id,
                item_type=item_type,
                value=value.strip(),
                normalized_value=_normalize(value),
            )
        )
    session.add(watchlist)
    if not await _try_flush(session):  # lost a concurrent same-name create race
        raise NameConflict
    return watchlist


async def rename_watchlist(session: AsyncSession, watchlist: Watchlist, new_name: str) -> None:
    """Rename a watchlist; the per-client unique index enforces uniqueness (FR-003)."""
    watchlist.name = new_name.strip()
    if not await _try_flush(session):  # name already taken in this client (incl. concurrent race)
        raise NameConflict


async def item_count(session: AsyncSession, watchlist_id: int) -> int:
    """Count items currently in a watchlist."""
    return (
        await session.scalar(
            select(func.count())
            .select_from(WatchlistItem)
            .where(WatchlistItem.watchlist_id == watchlist_id)
        )
        or 0
    )


async def set_active(session: AsyncSession, watchlist: Watchlist, active: bool) -> None:
    """Flip a watchlist's active flag; reject activating an empty watchlist (FR-016)."""
    if active and not watchlist.is_active and await item_count(session, watchlist.id) == 0:
        raise WatchlistEmpty
    watchlist.is_active = active


async def add_item(
    session: AsyncSession, watchlist: Watchlist, *, item_type: str, value: str
) -> WatchlistItem | None:
    """Add an item idempotently; return the new row, or None if it already existed (FR-005).

    Uses INSERT ... ON CONFLICT DO NOTHING so a duplicate (even under a concurrent race) is a
    clean no-op with no exception to recover from — the unique index is the single source of truth.
    """
    stmt = (
        pg_insert(WatchlistItem)
        .values(
            watchlist_id=watchlist.id,
            client_id=watchlist.client_id,
            item_type=item_type,
            value=value.strip(),
            normalized_value=_normalize(value),
        )
        .on_conflict_do_nothing(index_elements=["watchlist_id", "item_type", "normalized_value"])
        .returning(WatchlistItem.id)
    )
    new_id = await session.scalar(stmt)
    if new_id is None:  # already present (idempotent no-op)
        return None
    return await session.get(WatchlistItem, new_id)


async def remove_item(
    session: AsyncSession, watchlist: Watchlist, item_id: int
) -> WatchlistItem | None:
    """Remove an item gracefully; guard against emptying an active watchlist (FR-016)."""
    item = await session.get(WatchlistItem, item_id)
    if item is None or item.watchlist_id != watchlist.id:
        return None  # graceful: absent item is a no-op (no event)
    remaining = await session.scalar(
        select(func.count())
        .select_from(WatchlistItem)
        .where(WatchlistItem.watchlist_id == watchlist.id)
    )
    if watchlist.is_active and (remaining or 0) <= 1:
        raise WatchlistEmpty
    await session.delete(item)
    await session.flush()
    return item


# --- Budget usage ------------------------------------------------------------


async def current_period_spend(session: AsyncSession, watchlist_id: int) -> Decimal:
    """Accumulated spend for the watchlist in the current UTC month (0 when no row, D4)."""
    amount = await session.scalar(
        select(WatchlistBudgetUsage.amount).where(
            WatchlistBudgetUsage.watchlist_id == watchlist_id,
            WatchlistBudgetUsage.period_start == current_period_start(),
        )
    )
    return amount if amount is not None else Decimal("0")


async def read_figures(session: AsyncSession, watchlist: Watchlist) -> tuple[str, Decimal]:
    """Return (budget_status, current_period_spend) for a watchlist read (D4)."""
    spend = await current_period_spend(session, watchlist.id)
    return derive_budget_state(watchlist.budget_amount, spend), spend


async def record_spend(
    session: AsyncSession, watchlist: Watchlist, amount: Decimal
) -> WatchlistBudgetUsage:
    """Upsert current-month usage for a watchlist (test/seam helper; spend metering is spec 11)."""
    period = current_period_start()
    usage = await session.scalar(
        select(WatchlistBudgetUsage).where(
            WatchlistBudgetUsage.watchlist_id == watchlist.id,
            WatchlistBudgetUsage.period_start == period,
        )
    )
    if usage is None:
        usage = WatchlistBudgetUsage(
            watchlist_id=watchlist.id,
            client_id=watchlist.client_id,
            period_start=period,
            amount=amount,
        )
        session.add(usage)
    else:
        usage.amount = amount
    await session.flush()
    return usage
