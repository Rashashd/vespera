"""Authz matrix unit tests: role × user_type × action (spec 4b, US1, SC-001)."""

import pytest
from fastapi import HTTPException

from app.auth.dependencies import (
    require_admin,
    require_manager,
    require_reviewer,
    require_reviewer_or_admin,
    require_role,
    require_staff,
)
from app.auth.schemas import Role, UserType


class _User:
    """Minimal stand-in with the attributes guards inspect."""

    def __init__(self, role: str, user_type: str = "staff") -> None:
        self.role = role
        self.user_type = user_type


# ---- require_manager ---------------------------------------------------------


async def test_manager_passes_manager_guard():
    u = _User("manager")
    assert await require_manager(u) is u


@pytest.mark.parametrize("role", ["admin", "reviewer", "client_user"])
async def test_non_manager_blocked_by_manager_guard(role):
    with pytest.raises(HTTPException) as exc:
        await require_manager(_User(role))
    assert exc.value.status_code == 403


# ---- require_admin -----------------------------------------------------------


@pytest.mark.parametrize("role", ["manager", "admin"])
async def test_manager_and_admin_pass_admin_guard(role):
    """Manager inherits admin powers (FR-003)."""
    u = _User(role)
    assert await require_admin(u) is u


@pytest.mark.parametrize("role", ["reviewer", "client_user"])
async def test_reviewer_and_client_user_blocked_by_admin_guard(role):
    with pytest.raises(HTTPException) as exc:
        await require_admin(_User(role))
    assert exc.value.status_code == 403


# ---- require_reviewer_or_admin -----------------------------------------------


@pytest.mark.parametrize("role", ["manager", "admin", "reviewer"])
async def test_staff_roles_pass_reviewer_or_admin_guard(role):
    u = _User(role)
    assert await require_reviewer_or_admin(u) is u


async def test_client_user_blocked_by_reviewer_or_admin_guard():
    with pytest.raises(HTTPException) as exc:
        await require_reviewer_or_admin(_User("client_user", "client"))
    assert exc.value.status_code == 403


# ---- require_staff -----------------------------------------------------------


@pytest.mark.parametrize("role", ["manager", "admin", "reviewer"])
async def test_staff_type_passes_staff_guard(role):
    u = _User(role, user_type="staff")
    assert await require_staff(u) is u


async def test_client_user_blocked_by_staff_guard():
    u = _User("client_user", user_type="client")
    with pytest.raises(HTTPException) as exc:
        await require_staff(u)
    assert exc.value.status_code == 403


# ---- require_reviewer --------------------------------------------------------


async def test_reviewer_passes_reviewer_guard():
    u = _User("reviewer")
    assert await require_reviewer(u) is u


@pytest.mark.parametrize("role", ["manager", "admin", "client_user"])
async def test_non_reviewer_blocked_by_reviewer_guard(role):
    with pytest.raises(HTTPException) as exc:
        await require_reviewer(_User(role))
    assert exc.value.status_code == 403


# ---- require_role (multi-role) -----------------------------------------------


async def test_require_role_multiple():
    guard = require_role(Role.ADMIN, Role.REVIEWER)
    assert await guard(_User("admin")) is not None
    assert await guard(_User("reviewer")) is not None
    with pytest.raises(HTTPException):
        await guard(_User("manager"))


# ---- enum completeness -------------------------------------------------------


def test_role_enum_has_four_values():
    assert set(Role) == {Role.MANAGER, Role.ADMIN, Role.REVIEWER, Role.CLIENT_USER}


def test_user_type_enum_has_two_values():
    assert set(UserType) == {UserType.STAFF, UserType.CLIENT}
