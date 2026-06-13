"""Audit atomicity: a failed audit write rolls back the originating change (US4 / FR-013a)."""

import os

import pytest

from app.core.dispatcher import EventDispatcher
from app.domain.events import ClientErased


async def test_handler_failure_propagates():
    """A handler exception propagates out of dispatch so the caller's transaction rolls back."""
    dispatcher = EventDispatcher()

    async def failing_handler(event, session):
        raise RuntimeError("audit write failed")

    dispatcher.register(ClientErased, failing_handler)
    event = ClientErased(actor_id=0, actor_type="system", erased_client_id=9)
    with pytest.raises(RuntimeError):
        await dispatcher.dispatch(event, session=None)  # type: ignore[arg-type]


@pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Postgres) with the baseline migration applied",
)
async def test_audit_failure_rolls_back_state(tmp_path):
    """Against real Postgres: an in-transaction failure leaves no audit_log row."""
    from sqlalchemy import func, select

    from app.audit.models import AuditLog
    from app.core.config import Settings
    from app.core.startup import load_secrets_from_vault
    from app.db.base import create_engine, create_session_factory

    settings = Settings()
    await load_secrets_from_vault(settings)
    engine = create_engine(settings.database_url)
    factory = create_session_factory(engine)

    before = await _count_rows(factory, AuditLog, func, select)
    with pytest.raises(RuntimeError):
        async with factory() as session:
            async with session.begin():
                session.add(
                    AuditLog(
                        actor_id=0,
                        actor_type="system",
                        action="Test",
                        target="t",
                        event_type="Test",
                    )
                )
                raise RuntimeError("simulated downstream failure after audit add")
    after = await _count_rows(factory, AuditLog, func, select)
    assert after == before  # rolled back — no orphan audit row
    await engine.dispose()


async def _count_rows(factory, model, func, select) -> int:
    async with factory() as session:
        result = await session.execute(select(func.count()).select_from(model))
        return int(result.scalar_one())
