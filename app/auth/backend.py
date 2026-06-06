"""fastapi-users wiring: user-db adapter, JWT strategy, auth backend, and current-user dep."""

from collections.abc import AsyncIterator

from fastapi import Depends
from fastapi_users import FastAPIUsers
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)
from fastapi_users.password import PasswordHelper
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.manager import UserManager
from app.auth.models import User
from app.core.config import Settings
from app.core.dependencies import get_session, get_settings_dep

# Argon2-backed hasher (research D2); shared by the login route and the admin write paths.
password_helper = PasswordHelper()

# Bearer transport pointed at the custom login route (contracts/auth.md).
bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")


async def get_user_db(
    session: AsyncSession = Depends(get_session),
) -> AsyncIterator[SQLAlchemyUserDatabase]:
    """Yield the SQLAlchemy user-database adapter bound to the request session."""
    yield SQLAlchemyUserDatabase(session, User)


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
    settings: Settings = Depends(get_settings_dep),
) -> AsyncIterator[UserManager]:
    """Yield the UserManager (used for read-path token validation)."""
    yield UserManager(user_db, settings.auth_jwt_secret)


def get_jwt_strategy(
    settings: Settings = Depends(get_settings_dep),
) -> JWTStrategy:
    """Build the stateless JWT strategy (Vault secret, ~30 min TTL; research D3)."""
    return JWTStrategy(
        secret=settings.auth_jwt_secret,
        lifetime_seconds=settings.auth_token_ttl_seconds,
    )


auth_backend = AuthenticationBackend(
    name="jwt", transport=bearer_transport, get_strategy=get_jwt_strategy
)

fastapi_users = FastAPIUsers[User, int](get_user_manager, [auth_backend])

# Reusable dependency: an authenticated, active user (401 when missing/expired/inactive; FR-003).
current_active_user = fastapi_users.current_user(active=True)
