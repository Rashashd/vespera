"""Unit tests for auth guard/manager internals that the HTTP integration tests don't reach.

Covers the deactivated-user 401 and cross-client 404 branches in app/auth/dependencies.py and the
admin-count query helper + UserManager.validate_password delegation in app/auth/manager.py, using
fakes so no live DB is needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.auth import dependencies as deps
from app.auth.manager import UserManager, _active_admin_count
from app.auth.schemas import UserType

pytestmark = pytest.mark.asyncio


async def test_current_active_principal_deactivated_user_raises_401():
    """A token whose user row is gone/deactivated fails closed (fresh read, not token claims)."""
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)  # user no longer exists
    user = MagicMock(id=1)

    with pytest.raises(HTTPException) as exc:
        await deps.current_active_principal(user=user, session=session)
    assert exc.value.status_code == 401


async def test_acting_client_rejects_cross_client_user_with_404():
    """A client-user naming a client that is not their own gets 404 (looks absent)."""
    dep = deps.acting_client()  # allow_suspended=False
    session = AsyncMock()
    session.get = AsyncMock(return_value=MagicMock(status="active"))
    user = MagicMock(user_type=UserType.CLIENT.value, client_id=999)

    with pytest.raises(HTTPException) as exc:
        await dep(client_id=1, user=user, session=session)  # 1 != own client 999
    assert exc.value.status_code == 404


async def test_active_admin_count_returns_scalar():
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=3)
    assert await _active_admin_count(session, client_id=1) == 3


async def test_active_admin_count_none_coerces_to_zero_with_exclude():
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    assert await _active_admin_count(session, client_id=1, exclude_id=5) == 0


async def test_user_manager_validate_password_delegates_to_policy():
    manager = UserManager(user_db=MagicMock(), jwt_secret="secret")
    await manager.validate_password("ValidPass1!", MagicMock())  # policy-compliant → no raise


async def test_user_manager_validate_password_rejects_weak():
    manager = UserManager(user_db=MagicMock(), jwt_secret="secret")
    with pytest.raises(Exception):  # noqa: B017 - fastapi_users InvalidPasswordException
        await manager.validate_password("weak", MagicMock())
