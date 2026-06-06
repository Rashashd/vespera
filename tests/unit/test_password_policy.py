"""Unit tests for the password policy helper (FR-016, SC-007); stack-free."""

import pytest
from fastapi_users import exceptions

from app.auth.manager import validate_password_policy


def test_conforming_password_is_accepted():
    """A password meeting all rules passes without raising."""
    validate_password_policy("Abcdef1!")


@pytest.mark.parametrize(
    "password",
    [
        "Ab1!",  # too short
        "abcdef1!",  # no uppercase
        "ABCDEF1!",  # no lowercase
        "Abcdefg!",  # no digit
        "Abcdefg1",  # no symbol
    ],
)
def test_violations_are_rejected(password):
    """Each policy violation raises InvalidPasswordException (FR-016)."""
    with pytest.raises(exceptions.InvalidPasswordException):
        validate_password_policy(password)
