"""Admin user-management routes: client-scoped create/list/update with audit (spec 2, D9)."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi_users import exceptions
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.backend import password_helper
from app.auth.dependencies import require_admin
from app.auth.manager import validate_password_policy
from app.auth.models import User
from app.auth.schemas import AdminUserCreate, AdminUserUpdate, Role, UserRead
from app.core.dependencies import get_session
from app.domain.events import UserCreated, UserDeactivated, UserRoleChanged

router = APIRouter(prefix="/users", tags=["users"])


async def _active_admin_count(
    session: AsyncSession, client_id: int, exclude_id: int | None = None
) -> int:
    """Count active admins in a client, optionally excluding one user (last-admin guard)."""
    stmt = (
        select(func.count())
        .select_from(User)
        .where(
            User.client_id == client_id,
            User.role == Role.ADMIN.value,
            User.is_active.is_(True),
        )
    )
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return await session.scalar(stmt) or 0


@router.post("", status_code=status.HTTP_201_CREATED, response_model=UserRead)
async def create_user(
    payload: AdminUserCreate,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> UserRead:
    """Create a user in the acting admin's client (FR-006/FR-007); audit it (FR-012)."""
    try:
        validate_password_policy(payload.password)
    except exceptions.InvalidPasswordException as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"PASSWORD_POLICY: {exc.reason}",
        ) from exc

    email = payload.email.lower()
    if await session.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="USER_ALREADY_EXISTS")

    user = User(
        email=email,
        hashed_password=password_helper.hash(payload.password),
        role=payload.role.value,
        client_id=admin.client_id,  # client comes from the token, never the body (FR-007)
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    session.add(user)
    await session.flush()  # assign id within the transaction
    await request.app.state.dispatcher.dispatch(
        UserCreated(
            actor_id=admin.id,
            actor_type="human",
            client_id=admin.client_id,
            target_user_id=user.id,
            target_email=user.email,
            role=user.role,
        ),
        session,
    )
    await session.refresh(user)
    return UserRead.model_validate(user)


@router.get("", response_model=list[UserRead])
async def list_users(
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    limit: int = 50,
    offset: int = 0,
) -> list[UserRead]:
    """List users in the acting admin's client only (FR-007, SC-003)."""
    rows = (
        await session.scalars(
            select(User)
            .where(User.client_id == admin.client_id)
            .order_by(User.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [UserRead.model_validate(u) for u in rows]


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> UserRead:
    """Change role and/or active status for a user in the admin's client (FR-008/013/014)."""
    user = await session.get(User, user_id)
    if user is None or user.client_id != admin.client_id:
        # Never reveal the existence of another client's user (SC-003).
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="USER_NOT_FOUND")

    dispatcher = request.app.state.dispatcher

    if payload.role is not None and payload.role.value != user.role:
        if (
            user.role == Role.ADMIN.value
            and payload.role != Role.ADMIN
            and await _active_admin_count(session, admin.client_id, exclude_id=user.id) == 0
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="LAST_ADMIN")
        await dispatcher.dispatch(
            UserRoleChanged(
                actor_id=admin.id,
                actor_type="human",
                client_id=admin.client_id,
                target_user_id=user.id,
                old_role=user.role,
                new_role=payload.role.value,
            ),
            session,
        )
        user.role = payload.role.value

    if payload.is_active is not None and payload.is_active != user.is_active:
        if payload.is_active is False:
            if (
                user.role == Role.ADMIN.value
                and await _active_admin_count(session, admin.client_id, exclude_id=user.id) == 0
            ):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="LAST_ADMIN")
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
        user.is_active = payload.is_active

    session.add(user)
    await session.flush()
    await session.refresh(user)
    return UserRead.model_validate(user)
