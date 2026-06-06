"""Reusable role-based authorization guards built on the authenticated-user dep (spec 2, D6)."""

from collections.abc import Callable

from fastapi import Depends, HTTPException, status

from app.auth.backend import current_active_user
from app.auth.models import User
from app.auth.schemas import Role

# Re-exported so later specs import the authenticated-user dependency from one place.
__all__ = ["current_active_user", "require_role", "require_admin", "require_reviewer"]


def require_role(*roles: Role) -> Callable[..., User]:
    """Build a dependency allowing only the given roles: 401 if unauthenticated, else 403."""
    allowed = {Role(r).value for r in roles}

    async def _guard(user: User = Depends(current_active_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="FORBIDDEN")
        return user

    return _guard


require_admin = require_role(Role.ADMIN)
require_reviewer = require_role(Role.REVIEWER)
