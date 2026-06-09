"""Unit tests for auth schemas: no password leakage, role/email/type validation (spec 4b)."""

import pytest
from pydantic import ValidationError

from app.auth.schemas import AdminUserCreate, Role, UserCreate, UserRead, UserType


def test_user_read_has_no_password_field():
    """UserRead never exposes a password or hash (FR-009)."""
    fields = set(UserRead.model_fields)
    assert "password" not in fields
    assert "hashed_password" not in fields
    assert {"id", "email", "role", "user_type"} <= fields


def test_user_read_serialization_excludes_secrets():
    """A serialized UserRead contains no password-like keys."""
    dumped = UserRead(
        id=1,
        email="a@x.com",
        is_active=True,
        is_superuser=False,
        is_verified=True,
        role=Role.REVIEWER,
        user_type=UserType.STAFF,
        client_id=None,
    ).model_dump()
    assert not any("password" in key for key in dumped)


def test_user_read_staff_has_null_client_id():
    """Staff UserRead has client_id=None."""
    u = UserRead(
        id=2,
        email="staff@x.com",
        is_active=True,
        is_superuser=False,
        is_verified=True,
        role=Role.ADMIN,
        user_type=UserType.STAFF,
        client_id=None,
    )
    assert u.client_id is None


def test_role_rejects_unknown_value():
    """Only known roles are valid (FR-002)."""
    with pytest.raises(ValidationError):
        AdminUserCreate(email="a@x.com", password="Abcdef1!", role="superadmin")


def test_user_create_requires_valid_email():
    """An invalid email is rejected at the schema boundary."""
    with pytest.raises(ValidationError):
        UserCreate(email="not-an-email", password="Abcdef1!", role=Role.ADMIN)


def test_usertype_enum_values():
    """UserType has exactly the two expected values."""
    assert set(UserType) == {UserType.STAFF, UserType.CLIENT}
