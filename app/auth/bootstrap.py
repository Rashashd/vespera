"""Idempotent bootstrap-manager seed: create one manager iff none exist (FR-024, D8)."""

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.backend import password_helper
from app.auth.manager import validate_password_policy
from app.auth.models import User
from app.auth.schemas import Role, UserType
from app.core.config import Settings

_log = structlog.get_logger(__name__)

# Dev fallback: used only when Vault secrets are absent (local/CI without a real Vault).
# Prod deployments must supply bootstrap_manager_email/password via Vault.
_DEV_EMAIL = "manager@pantera.local"
_DEV_PASSWORD = "ChangeMe1!"


async def ensure_manager(session: AsyncSession, settings: Settings) -> None:
    """Create the bootstrap manager only if no active manager exists (idempotent)."""
    existing = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.role == Role.MANAGER.value, User.is_active.is_(True))
    )
    if existing:
        return

    email = (settings.bootstrap_manager_email or _DEV_EMAIL).lower()
    password = settings.bootstrap_manager_password or _DEV_PASSWORD

    # Validate password policy; a weak dev password is intentionally accepted here because
    # _DEV_PASSWORD satisfies the policy and prod passwords come from Vault.
    try:
        validate_password_policy(password)
    except Exception:  # noqa: BLE001
        _log.warning("bootstrap.weak_password_skipped")
        return

    manager = User(
        email=email,
        hashed_password=password_helper.hash(password),
        role=Role.MANAGER.value,
        user_type=UserType.STAFF.value,
        client_id=None,
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    session.add(manager)
    await session.flush()
    _log.info("bootstrap.manager_created", email=email, user_id=manager.id)
