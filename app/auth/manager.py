"""Password policy (FR-016), guard helpers, and the fastapi-users UserManager."""

import re

from fastapi_users import BaseUserManager, IntegerIDMixin, exceptions
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.schemas import Role

_SYMBOL = re.compile(r"[^A-Za-z0-9]")


def validate_password_policy(password: str) -> None:
    """Enforce FR-016: ≥8 chars incl. upper, lower, digit, symbol; raise on violation."""
    missing: list[str] = []
    if len(password) < 8:
        missing.append("at least 8 characters")
    if not any(c.islower() for c in password):
        missing.append("a lowercase letter")
    if not any(c.isupper() for c in password):
        missing.append("an uppercase letter")
    if not any(c.isdigit() for c in password):
        missing.append("a digit")
    if not _SYMBOL.search(password):
        missing.append("a symbol")
    if missing:
        raise exceptions.InvalidPasswordException(
            reason="Password must contain " + ", ".join(missing) + "."
        )


async def _active_manager_count(session: AsyncSession, exclude_id: int | None = None) -> int:
    """Count active managers globally, optionally excluding one user (last-manager guard)."""
    stmt = (
        select(func.count())
        .select_from(User)
        .where(User.role == Role.MANAGER.value, User.is_active.is_(True))
    )
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return await session.scalar(stmt) or 0


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


class UserManager(IntegerIDMixin, BaseUserManager[User, int]):
    """fastapi-users manager; supplies password policy and token-secret configuration."""

    def __init__(self, user_db, jwt_secret: str) -> None:
        super().__init__(user_db)
        # Reset/verification flows are out of scope; secrets are set to satisfy the base class.
        self.reset_password_token_secret = jwt_secret
        self.verification_token_secret = jwt_secret

    async def validate_password(self, password: str, user) -> None:  # noqa: ANN001
        """Delegate to the shared policy helper (FR-016)."""
        validate_password_policy(password)
