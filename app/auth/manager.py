"""Password policy (FR-016) and the fastapi-users UserManager used for token validation."""

import re

from fastapi_users import BaseUserManager, IntegerIDMixin, exceptions

from app.auth.models import User

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
