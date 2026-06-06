"""Unit tests for role guards: allow matching role, 403 on mismatch (US2, SC-002); stack-free."""

import pytest
from fastapi import HTTPException

from app.auth.dependencies import require_admin, require_reviewer, require_role
from app.auth.schemas import Role


class _User:
    """Minimal stand-in carrying only the attribute the guard inspects."""

    def __init__(self, role: str) -> None:
        self.role = role


async def test_guard_allows_matching_role():
    """The guard returns the user when their role is permitted."""
    user = _User("admin")
    assert await require_admin(user) is user


async def test_guard_forbids_other_role():
    """The guard raises 403 when the role is not permitted (authenticated but unauthorized)."""
    with pytest.raises(HTTPException) as exc:
        await require_admin(_User("reviewer"))
    assert exc.value.status_code == 403


async def test_reviewer_guard_forbids_admin():
    """The reviewer guard refuses an admin (symmetric to the admin guard)."""
    with pytest.raises(HTTPException) as exc:
        await require_reviewer(_User("admin"))
    assert exc.value.status_code == 403


async def test_require_role_accepts_multiple():
    """A guard built for multiple roles admits any of them."""
    guard = require_role(Role.ADMIN, Role.REVIEWER)
    assert await guard(_User("reviewer")) is not None
    assert await guard(_User("admin")) is not None
