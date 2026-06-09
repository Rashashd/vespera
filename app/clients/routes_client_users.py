"""Client-side user management: create/list/update scoped users per named client (spec 4b, US3)."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi_users import exceptions as fu_exc
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.backend import password_helper
from app.auth.dependencies import acting_client, require_admin
from app.auth.manager import validate_password_policy
from app.auth.models import User
from app.clients import service
from app.clients.models import Client
from app.clients.schemas import ClientUserCreate, ClientUserOut, ClientUserUpdate
from app.core.dependencies import get_session
from app.domain.events import ClientUserCreated, ClientUserScopeChanged, UserDeactivated

router = APIRouter(prefix="/clients", tags=["client-users"])

_get_acting_client = acting_client()


@router.post(
    "/{client_id}/users",
    status_code=status.HTTP_201_CREATED,
    response_model=ClientUserOut,
)
async def create_client_user(
    client_id: int,
    payload: ClientUserCreate,
    request: Request,
    admin: User = Depends(require_admin),
    target: Client = Depends(_get_acting_client),
    session: AsyncSession = Depends(get_session),
) -> ClientUserOut:
    """Create a client-user; scope must be explicit, user_type/client_id forced (FR-014)."""
    try:
        validate_password_policy(payload.password)
    except fu_exc.InvalidPasswordException as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"PASSWORD_POLICY: {exc.reason}",
        ) from exc

    email = payload.email.strip().lower()
    try:
        service.validate_email_address(email)
    except service.InvalidEmail as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="INVALID_EMAIL"
        ) from exc

    if await session.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="USER_ALREADY_EXISTS")

    try:
        user = await service.create_client_user(
            session,
            client_id,
            email=email,
            hashed_password=password_helper.hash(payload.password),
            client_scope=payload.client_scope.value,
            min_severity=payload.min_severity.value if payload.min_severity else None,
            watchlist_ids=payload.watchlist_ids,
        )
    except service.ScopeRequired as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="SCOPE_REQUIRED"
        ) from exc
    except service.CrossClientWatchlist as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="CROSS_CLIENT_WATCHLIST"
        ) from exc

    await request.app.state.dispatcher.dispatch(
        ClientUserCreated(
            actor_id=admin.id,
            actor_type="human",
            client_id=admin.client_id,
            target_client_id=client_id,
            target_user_id=user.id,
            client_scope=user.client_scope or "",
        ),
        session,
    )
    await session.refresh(user)
    return ClientUserOut.from_user(user)


@router.get("/{client_id}/users", response_model=list[ClientUserOut])
async def list_client_users(
    client_id: int,
    admin: User = Depends(require_admin),
    target: Client = Depends(_get_acting_client),
    session: AsyncSession = Depends(get_session),
) -> list[ClientUserOut]:
    """List all users belonging to a named client (admin-only; contracts/client-users.md)."""
    users = await service.list_client_users(session, client_id)
    return [ClientUserOut.from_user(u) for u in users]


@router.patch("/{client_id}/users/{user_id}", response_model=ClientUserOut)
async def update_client_user(
    client_id: int,
    user_id: int,
    payload: ClientUserUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    target: Client = Depends(_get_acting_client),
    session: AsyncSession = Depends(get_session),
) -> ClientUserOut:
    """Update scope / active for a client-user; immutable fields rejected (FR-015)."""
    user = await service.get_client_user(session, client_id, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="USER_NOT_FOUND")

    dispatcher = request.app.state.dispatcher

    try:
        user = await service.update_client_user_scope(
            session,
            user,
            client_scope=payload.client_scope.value if payload.client_scope else None,
            min_severity=payload.min_severity.value if payload.min_severity else None,
            watchlist_ids=payload.watchlist_ids,
            is_active=payload.is_active,
        )
    except service.ScopeRequired as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="SCOPE_REQUIRED"
        ) from exc
    except service.CrossClientWatchlist as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="CROSS_CLIENT_WATCHLIST"
        ) from exc

    changes: dict = {}
    if payload.client_scope is not None:
        changes["client_scope"] = payload.client_scope.value
    if payload.min_severity is not None:
        changes["min_severity"] = payload.min_severity.value
    if payload.watchlist_ids is not None:
        changes["watchlist_ids"] = payload.watchlist_ids

    if changes:
        await dispatcher.dispatch(
            ClientUserScopeChanged(
                actor_id=admin.id,
                actor_type="human",
                client_id=admin.client_id,
                target_client_id=client_id,
                target_user_id=user.id,
                changes=changes,
            ),
            session,
        )
    if payload.is_active is False:
        await dispatcher.dispatch(
            UserDeactivated(
                actor_id=admin.id,
                actor_type="human",
                client_id=admin.client_id,
                target_user_id=user.id,
                target_email=user.email,
            ),
            session,
        )

    await session.refresh(user)
    return ClientUserOut.from_user(user)
