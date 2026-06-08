"""Watchlist CRUD + item routes, all scoped to the caller's client (writes admin-only, FR-013)."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import current_active_user, require_admin
from app.auth.models import User
from app.clients import service
from app.clients.schemas import WatchlistCreate, WatchlistItemAdd, WatchlistRead, WatchlistUpdate
from app.core.dependencies import get_session
from app.domain.events import (
    WatchlistCreated,
    WatchlistDeactivated,
    WatchlistItemAdded,
    WatchlistItemRemoved,
    WatchlistUpdated,
)

router = APIRouter(prefix="/watchlists", tags=["watchlists"])


async def _to_read(session: AsyncSession, watchlist) -> WatchlistRead:
    """Build the response model, computing the derived budget status/spend."""
    budget_status, spend = await service.read_figures(session, watchlist)
    return WatchlistRead.from_watchlist(watchlist, budget_status=budget_status, spend=spend)


async def _require_watchlist(session: AsyncSession, client_id: int, watchlist_id: int):
    """Fetch a watchlist in the caller's client or raise 404 (no reveal, SC-003)."""
    watchlist = await service.get_watchlist(session, client_id, watchlist_id)
    if watchlist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WATCHLIST_NOT_FOUND")
    return watchlist


@router.post("", status_code=status.HTTP_201_CREATED, response_model=WatchlistRead)
async def create_watchlist(
    payload: WatchlistCreate,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> WatchlistRead:
    """Create a named watchlist with ≥1 item in the admin's client (FR-003/FR-016)."""
    try:
        watchlist = await service.create_watchlist(
            session,
            admin.client_id,
            name=payload.name,
            cadence=payload.cadence.value,
            severity_threshold=payload.severity_threshold.value,
            budget_amount=payload.budget_amount,
            items=[(i.item_type.value, i.value) for i in payload.items],
        )
    except service.WatchlistEmpty as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="WATCHLIST_EMPTY"
        ) from exc
    except service.NameConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="WATCHLIST_NAME_TAKEN"
        ) from exc

    await request.app.state.dispatcher.dispatch(
        WatchlistCreated(
            actor_id=admin.id,
            actor_type="human",
            client_id=admin.client_id,
            watchlist_id=watchlist.id,
            name=watchlist.name,
        ),
        session,
    )
    return await _to_read(session, watchlist)


@router.get("", response_model=list[WatchlistRead])
async def list_watchlists(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
    include_inactive: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[WatchlistRead]:
    """List the caller's client's watchlists (reviewer may view; SC-003)."""
    rows = await service.list_watchlists(
        session, user.client_id, include_inactive=include_inactive, limit=limit, offset=offset
    )
    return [await _to_read(session, w) for w in rows]


@router.get("/{watchlist_id}", response_model=WatchlistRead)
async def get_watchlist(
    watchlist_id: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> WatchlistRead:
    """Retrieve one watchlist of the caller's client; cross-tenant ⇒ 404 (SC-003)."""
    watchlist = await _require_watchlist(session, user.client_id, watchlist_id)
    return await _to_read(session, watchlist)


@router.patch("/{watchlist_id}", response_model=WatchlistRead)
async def update_watchlist(
    watchlist_id: int,
    payload: WatchlistUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> WatchlistRead:
    """Rename / set cadence,severity,budget / (de)activate a watchlist; one audit event (FR-017)."""
    watchlist = await _require_watchlist(session, admin.client_id, watchlist_id)
    fields = payload.model_fields_set
    changes: dict = {}
    deactivated = False

    if "name" in fields and payload.name != watchlist.name:
        try:
            await service.rename_watchlist(session, watchlist, payload.name)
        except service.NameConflict as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="WATCHLIST_NAME_TAKEN"
            ) from exc
        changes["name"] = watchlist.name

    if "cadence" in fields and payload.cadence.value != watchlist.cadence:
        watchlist.cadence = payload.cadence.value
        changes["cadence"] = watchlist.cadence

    if (
        "severity_threshold" in fields
        and payload.severity_threshold.value != watchlist.severity_threshold
    ):
        watchlist.severity_threshold = payload.severity_threshold.value
        changes["severity_threshold"] = watchlist.severity_threshold

    if "budget_amount" in fields and payload.budget_amount != watchlist.budget_amount:
        watchlist.budget_amount = payload.budget_amount
        changes["budget_amount"] = (
            str(payload.budget_amount) if payload.budget_amount is not None else None
        )

    if "is_active" in fields and payload.is_active != watchlist.is_active:
        try:
            await service.set_active(session, watchlist, payload.is_active)
        except service.WatchlistEmpty as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="WATCHLIST_EMPTY"
            ) from exc
        deactivated = payload.is_active is False
        changes["is_active"] = watchlist.is_active

    if changes:
        session.add(watchlist)
        await session.flush()
        dispatcher = request.app.state.dispatcher
        if deactivated:
            await dispatcher.dispatch(
                WatchlistDeactivated(
                    actor_id=admin.id,
                    actor_type="human",
                    client_id=admin.client_id,
                    watchlist_id=watchlist.id,
                ),
                session,
            )
        else:
            await dispatcher.dispatch(
                WatchlistUpdated(
                    actor_id=admin.id,
                    actor_type="human",
                    client_id=admin.client_id,
                    watchlist_id=watchlist.id,
                    changes=changes,
                ),
                session,
            )

    await session.refresh(watchlist)
    return await _to_read(session, watchlist)


@router.post("/{watchlist_id}/items", response_model=WatchlistRead)
async def add_item(
    watchlist_id: int,
    payload: WatchlistItemAdd,
    request: Request,
    response: Response,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> WatchlistRead:
    """Add an item idempotently; 201 when created, 200 on a duplicate no-op (FR-005)."""
    watchlist = await _require_watchlist(session, admin.client_id, watchlist_id)
    item = await service.add_item(
        session, watchlist, item_type=payload.item_type.value, value=payload.value
    )
    if item is None:
        response.status_code = status.HTTP_200_OK
    else:
        response.status_code = status.HTTP_201_CREATED
        await request.app.state.dispatcher.dispatch(
            WatchlistItemAdded(
                actor_id=admin.id,
                actor_type="human",
                client_id=admin.client_id,
                watchlist_id=watchlist.id,
                item_id=item.id,
                item_type=item.item_type,
                value=item.value,
            ),
            session,
        )
    await session.refresh(watchlist)
    return await _to_read(session, watchlist)


@router.delete("/{watchlist_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_item(
    watchlist_id: int,
    item_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Remove an item gracefully; refuse to empty an active watchlist (FR-016)."""
    watchlist = await _require_watchlist(session, admin.client_id, watchlist_id)
    try:
        removed = await service.remove_item(session, watchlist, item_id)
    except service.WatchlistEmpty as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="WATCHLIST_EMPTY"
        ) from exc
    if removed is not None:
        await request.app.state.dispatcher.dispatch(
            WatchlistItemRemoved(
                actor_id=admin.id,
                actor_type="human",
                client_id=admin.client_id,
                watchlist_id=watchlist.id,
                item_id=item_id,
            ),
            session,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
