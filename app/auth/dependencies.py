"""Role-based guards and the acting-client dependency (spec 4b; contracts/authz-model.md)."""

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.backend import current_active_user
from app.auth.models import User
from app.auth.schemas import Role, UserType
from app.clients.models import Client
from app.core.dependencies import get_session

__all__ = [
    "current_active_user",
    "current_active_principal",
    "require_staff",
    "require_manager",
    "require_admin",
    "require_reviewer_or_admin",
    "acting_client",
]


async def current_active_principal(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Re-read the user's current DB state; for client-users, also gate on client status.

    Freshness: authorization is computed from the current stored row, not token claims (FR-019).
    """
    # Re-read so demotion/deactivation is effective on the next request.
    fresh = await session.get(User, user.id)
    if fresh is None or not fresh.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="NOT_AUTHENTICATED")

    if fresh.user_type == UserType.CLIENT.value and fresh.client_id is not None:
        client = await session.get(Client, fresh.client_id)
        if client is None or client.status != "active":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CLIENT_SUSPENDED")

    return fresh


def require_role(*roles: Role) -> Callable[..., User]:
    """Build a dependency allowing only the given roles; 401 if unauthenticated, 403 otherwise."""
    allowed = {r.value for r in roles}

    async def _guard(user: User = Depends(current_active_principal)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="FORBIDDEN")
        return user

    return _guard


async def require_staff(
    user: User = Depends(current_active_principal),
) -> User:
    """Reject client-users; allow any staff role (403 otherwise)."""
    if user.user_type != UserType.STAFF.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="FORBIDDEN")
    return user


require_manager = require_role(Role.MANAGER)
# Manager inherits admin powers (FR-003).
require_admin = require_role(Role.MANAGER, Role.ADMIN)
require_reviewer_or_admin = require_role(Role.MANAGER, Role.ADMIN, Role.REVIEWER)

# Backwards-compatible alias used by existing spec-2/3/4 routes.
require_reviewer = require_role(Role.REVIEWER)


def acting_client(allow_suspended: bool = False) -> Callable[..., Client]:
    """Factory: returns a dep that loads + validates the {client_id} path param.

    - 404 if the client does not exist.
    - For client-users: 404 if the client is not their own.
    - 400 CLIENT_SUSPENDED for new-work routes (allow_suspended=False, the default).
    - allow_suspended=True is used by read-only / status-check routes.
    """

    async def _dep(
        client_id: int,
        user: User = Depends(current_active_principal),
        session: AsyncSession = Depends(get_session),
    ) -> Client:
        client = await session.get(Client, client_id)
        if client is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CLIENT_NOT_FOUND")

        if user.user_type == UserType.CLIENT.value:
            # Client-users may only name their own client.
            if user.client_id != client_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="CLIENT_NOT_FOUND"
                )

        if not allow_suspended and client.status != "active":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CLIENT_SUSPENDED")

        return client

    return _dep


def acting_client_read() -> Callable[..., Client]:
    """acting_client variant that allows reading a suspended client's data."""
    return acting_client(allow_suspended=True)


# Pre-built dependency instances for the common cases.
get_acting_client = acting_client()
get_acting_client_read = acting_client_read()
