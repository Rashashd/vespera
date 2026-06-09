"""Unit tests for role guards: allow matching role, 403 on mismatch (spec 4b); stack-free."""

import pytest
from fastapi import HTTPException

from app.auth.dependencies import require_admin, require_manager, require_reviewer, require_role
from app.auth.schemas import Role


class _User:
    """Minimal stand-in carrying the attributes the guards inspect."""

    def __init__(self, role: str, user_type: str = "staff") -> None:
        self.role = role
        self.user_type = user_type


async def test_guard_allows_matching_role():
    """The admin guard returns the user when role is admin (FR-003)."""
    user = _User("admin")
    assert await require_admin(user) is user


async def test_manager_also_passes_admin_guard():
    """Manager inherits admin powers — the admin guard admits managers (FR-003)."""
    user = _User("manager")
    assert await require_admin(user) is user


async def test_guard_forbids_other_role():
    """The admin guard raises 403 for reviewer."""
    with pytest.raises(HTTPException) as exc:
        await require_admin(_User("reviewer"))
    assert exc.value.status_code == 403


async def test_reviewer_guard_forbids_admin():
    """The reviewer guard refuses an admin."""
    with pytest.raises(HTTPException) as exc:
        await require_reviewer(_User("admin"))
    assert exc.value.status_code == 403


async def test_manager_guard_forbids_admin():
    """The manager guard refuses a plain admin."""
    with pytest.raises(HTTPException) as exc:
        await require_manager(_User("admin"))
    assert exc.value.status_code == 403


async def test_require_role_accepts_multiple():
    """A guard built for multiple roles admits any of them."""
    guard = require_role(Role.ADMIN, Role.REVIEWER)
    assert await guard(_User("reviewer")) is not None
    assert await guard(_User("admin")) is not None
