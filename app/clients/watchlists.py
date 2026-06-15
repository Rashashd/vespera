"""Watchlist queries/mutations and per-watchlist budget usage (spec 3)."""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients._helpers import (
    NameConflict,
    WatchlistEmpty,
    _normalize,
    _try_flush,
    current_period_start,
    derive_budget_state,
)
from app.clients.models import Watchlist, WatchlistBudgetUsage, WatchlistItem


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
    budget_exceeded_policy: str = "continue",
    items: list[tuple[str, str]],
) -> Watchlist:
    """Create a watchlist with ≥1 de-duplicated item; the unique index enforces the name."""
    from app.ingestion.mesh import validate_mesh

    deduped = _dedup_items(items)
    if not deduped:
        raise WatchlistEmpty
    watchlist = Watchlist(
        client_id=client_id,
        name=name.strip(),
        cadence=cadence,
        severity_threshold=severity_threshold,
        budget_amount=budget_amount,
        budget_exceeded_policy=budget_exceeded_policy,
        is_active=True,
    )
    for item_type, value in deduped:
        validity, canonical = validate_mesh(value) if item_type == "mesh" else (None, None)
        watchlist.items.append(
            WatchlistItem(
                client_id=client_id,
                item_type=item_type,
                value=value.strip(),
                normalized_value=_normalize(value),
                mesh_validity=validity.value if validity is not None else None,
                mesh_canonical=canonical,
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
    MeSH items have mesh_validity/mesh_canonical set at write time (FR-009).
    """
    from app.ingestion.mesh import validate_mesh

    validity, canonical = validate_mesh(value) if item_type == "mesh" else (None, None)
    stmt = (
        pg_insert(WatchlistItem)
        .values(
            watchlist_id=watchlist.id,
            client_id=watchlist.client_id,
            item_type=item_type,
            value=value.strip(),
            normalized_value=_normalize(value),
            mesh_validity=validity.value if validity is not None else None,
            mesh_canonical=canonical,
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
