"""Unit tests for auth schemas: no password leakage, role/email validation (US1, SC-005)."""

import pytest
from pydantic import ValidationError

from app.auth.schemas import AdminUserCreate, Role, UserCreate, UserRead


def test_user_read_has_no_password_field():
    """UserRead never exposes a password or hash (FR-009/SC-005)."""
    fields = set(UserRead.model_fields)
    assert "password" not in fields
    assert "hashed_password" not in fields
    assert {"id", "email", "role", "client_id"} <= fields


def test_user_read_serialization_excludes_secrets():
    """A serialized UserRead contains no password-like keys."""
    dumped = UserRead(
        id=1,
        email="a@x.com",
        is_active=True,
        is_superuser=False,
        is_verified=True,
        role=Role.REVIEWER,
        client_id=3,
    ).model_dump()
    assert not any("password" in key for key in dumped)


def test_role_rejects_unknown_value():
    """Only admin/reviewer are valid roles (FR-004)."""
    with pytest.raises(ValidationError):
        AdminUserCreate(email="a@x.com", password="Abcdef1!", role="superadmin")


def test_user_create_requires_valid_email():
    """An invalid email is rejected at the schema boundary."""
    with pytest.raises(ValidationError):
        UserCreate(email="not-an-email", password="Abcdef1!", role=Role.ADMIN, client_id=1)
