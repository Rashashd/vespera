"""One-time operator bootstrap: create the first admin when no users exist (spec 2, FR-011)."""

import asyncio

from sqlalchemy import func, select

from app.auth.backend import password_helper
from app.auth.manager import validate_password_policy
from app.auth.models import User
from app.core.config import get_settings
from app.core.startup import load_secrets_from_vault
from app.db.base import create_engine, create_session_factory


async def _seed() -> None:
    """Create the bootstrap admin from Vault-sourced credentials; idempotent."""
    settings = get_settings()
    await load_secrets_from_vault(settings)
    if not (settings.bootstrap_admin_email and settings.bootstrap_admin_password):
        raise SystemExit("bootstrap_admin_email / bootstrap_admin_password missing from Vault")
    validate_password_policy(settings.bootstrap_admin_password)

    engine = create_engine(settings.database_url)
    try:
        factory = create_session_factory(engine)
        async with factory() as session:
            existing = await session.scalar(select(func.count()).select_from(User))
            if existing:
                print(f"Users already exist ({existing}); bootstrap is a no-op.")
                return
            session.add(
                User(
                    email=settings.bootstrap_admin_email.lower(),
                    hashed_password=password_helper.hash(settings.bootstrap_admin_password),
                    role="admin",
                    client_id=settings.bootstrap_admin_client_id,
                    is_active=True,
                    is_superuser=False,
                    is_verified=True,
                )
            )
            await session.commit()
            print(f"Created bootstrap admin {settings.bootstrap_admin_email.lower()}")
    finally:
        await engine.dispose()


def main() -> None:
    """Entry point for `python scripts/seed_admin.py`."""
    asyncio.run(_seed())


if __name__ == "__main__":
    main()
