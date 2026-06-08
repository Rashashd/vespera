"""Operator path to onboard / suspend / reactivate a client tenant (mirrors seed_admin.py)."""

import argparse
import asyncio

# Register the users table on Base.metadata so the audit_log → users FK resolves at flush time.
from app.auth import models as _auth_models  # noqa: F401
from app.clients import service
from app.clients.enums import ClientStatus
from app.core.config import get_settings
from app.core.dispatcher import EventDispatcher
from app.core.startup import load_secrets_from_vault
from app.db.base import create_engine, create_session_factory
from app.db.models import SYSTEM_ACTOR_ID
from app.domain.events import ClientCreated, ClientSuspended, ClientUpdated


def _build_dispatcher() -> EventDispatcher:
    """A dispatcher with the audit handler registered so operator actions are audited too."""
    from app.audit.handler import register_audit_handlers

    dispatcher = EventDispatcher()
    register_audit_handlers(dispatcher)
    return dispatcher


async def _create(name: str) -> None:
    """Create an active client and print its id; audited as a system action."""
    settings = get_settings()
    await load_secrets_from_vault(settings)
    engine = create_engine(settings.database_url)
    dispatcher = _build_dispatcher()
    try:
        factory = create_session_factory(engine)
        async with factory() as session:
            async with session.begin():
                try:
                    client = await service.create_client(session, name)
                except service.NameConflict as exc:
                    raise SystemExit(
                        f"A client named {name!r} already exists (case-insensitive)."
                    ) from exc
                await dispatcher.dispatch(
                    ClientCreated(
                        actor_id=SYSTEM_ACTOR_ID,
                        actor_type="system",
                        client_id=client.id,
                        target_client_id=client.id,
                        name=client.name,
                    ),
                    session,
                )
                created_id = client.id
        print(f"Created client {created_id}: {name}")
    finally:
        await engine.dispose()


async def _set_status(client_id: int, status: ClientStatus) -> None:
    """Suspend or reactivate an existing client; audited as a system action."""
    settings = get_settings()
    await load_secrets_from_vault(settings)
    engine = create_engine(settings.database_url)
    dispatcher = _build_dispatcher()
    try:
        factory = create_session_factory(engine)
        async with factory() as session:
            async with session.begin():
                client = await service.get_client(session, client_id)
                if client is None:
                    raise SystemExit(f"No client with id {client_id}.")
                await service.set_client_status(session, client, status)
                event = (
                    ClientSuspended(
                        actor_id=SYSTEM_ACTOR_ID,
                        actor_type="system",
                        client_id=client.id,
                        target_client_id=client.id,
                    )
                    if status is ClientStatus.SUSPENDED
                    else ClientUpdated(
                        actor_id=SYSTEM_ACTOR_ID,
                        actor_type="system",
                        client_id=client.id,
                        target_client_id=client.id,
                        changes={"status": status.value},
                    )
                )
                await dispatcher.dispatch(event, session)
        print(f"Client {client_id} is now {status.value}.")
    finally:
        await engine.dispose()


def main() -> None:
    """Entry point for `python scripts/seed_client.py`."""
    parser = argparse.ArgumentParser(description="Onboard or change the status of a client.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--name", help="create a new active client with this name")
    group.add_argument("--suspend", type=int, metavar="CLIENT_ID", help="suspend a client")
    group.add_argument("--activate", type=int, metavar="CLIENT_ID", help="reactivate a client")
    args = parser.parse_args()

    if args.name:
        asyncio.run(_create(args.name))
    elif args.suspend is not None:
        asyncio.run(_set_status(args.suspend, ClientStatus.SUSPENDED))
    else:
        asyncio.run(_set_status(args.activate, ClientStatus.ACTIVE))


if __name__ == "__main__":
    main()
