"""Manager-only staff account management (cross-client; contracts/staff-accounts.md)."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi_users import exceptions as fu_exc
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.backend import password_helper
from app.auth.dependencies import require_manager
from app.auth.manager import _active_manager_count, validate_password_policy
from app.auth.models import User
from app.auth.schemas import Role, StaffUserCreate, StaffUserOut, StaffUserUpdate, UserType
from app.core.dependencies import get_session
from app.domain.events import UserCreated, UserDeactivated, UserRoleChanged

router = APIRouter(prefix="/staff", tags=["staff"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=StaffUserOut)
async def create_staff_user(
    payload: StaffUserCreate,
    request: Request,
    manager: User = Depends(require_manager),
    session: AsyncSession = Depends(get_session),
) -> StaffUserOut:
    """Create a staff user; only a manager may create another manager (FR-004)."""
    if payload.role == Role.MANAGER:
        pass  # already guarded: only managers reach this endpoint

    try:
        validate_password_policy(payload.password)
    except fu_exc.InvalidPasswordException as exc:
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
        user_type=UserType.STAFF.value,
        client_id=None,
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    session.add(user)
    await session.flush()
    await request.app.state.dispatcher.dispatch(
        UserCreated(
            actor_id=manager.id,
            actor_type="human",
            client_id=None,
            target_user_id=user.id,
            target_email=user.email,
            role=user.role,
        ),
        session,
    )
    await session.refresh(user)
    return StaffUserOut.model_validate(user)


@router.get("", response_model=list[StaffUserOut])
async def list_staff_users(
    manager: User = Depends(require_manager),
    session: AsyncSession = Depends(get_session),
    limit: int = 50,
    offset: int = 0,
) -> list[StaffUserOut]:
    """List all staff users (manager-only; contracts/staff-accounts.md)."""
    rows = (
        await session.scalars(
            select(User)
            .where(User.user_type == UserType.STAFF.value)
            .order_by(User.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [StaffUserOut.model_validate(u) for u in rows]


@router.patch("/{user_id}", response_model=StaffUserOut)
async def update_staff_user(
    user_id: int,
    payload: StaffUserUpdate,
    request: Request,
    manager: User = Depends(require_manager),
    session: AsyncSession = Depends(get_session),
) -> StaffUserOut:
    """Change role / active status for a staff user (last-manager guard; FR-005)."""
    user = await session.get(User, user_id)
    if user is None or user.user_type != UserType.STAFF.value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="USER_NOT_FOUND")

    dispatcher = request.app.state.dispatcher

    if payload.role is not None and payload.role.value != user.role:
        if (
            user.role == Role.MANAGER.value
            and payload.role != Role.MANAGER
            and await _active_manager_count(session, exclude_id=user.id) == 0
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="LAST_MANAGER")
        await dispatcher.dispatch(
            UserRoleChanged(
                actor_id=manager.id,
                actor_type="human",
                client_id=None,
                target_user_id=user.id,
                old_role=user.role,
                new_role=payload.role.value,
            ),
            session,
        )
        user.role = payload.role.value

    if payload.is_active is not None and payload.is_active != user.is_active:
        if not payload.is_active:
            if (
                user.role == Role.MANAGER.value
                and await _active_manager_count(session, exclude_id=user.id) == 0
            ):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="LAST_MANAGER")
            await dispatcher.dispatch(
                UserDeactivated(
                    actor_id=manager.id,
                    actor_type="human",
                    client_id=None,
                    target_user_id=user.id,
                    target_email=user.email,
                ),
                session,
            )
        user.is_active = payload.is_active

    session.add(user)
    await session.flush()
    await session.refresh(user)
    return StaffUserOut.model_validate(user)
