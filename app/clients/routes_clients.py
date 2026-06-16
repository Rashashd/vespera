"""Client lifecycle and own-client routes (spec 3 + spec 4b; contracts/client-lifecycle.md)."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    acting_client,
    current_active_user,
    require_admin,
    require_manager,
    require_staff,
)
from app.auth.models import User
from app.clients import service
from app.clients.models import Client
from app.clients.schemas import (
    ClientCreate,
    ClientOut,
    ClientRead,
    ClientUpdate,
    ReportEmailUpdate,
    SeverityKeywordsUpdate,
)
from app.core.dependencies import get_session
from app.domain.events import (
    ClientCreated,
    ClientReactivated,
    ClientReportEmailChanged,
    ClientSuspended,
    ClientUpdated,
)

router = APIRouter(prefix="/clients", tags=["clients"])

_get_acting_client = acting_client()
_get_acting_client_read = acting_client(allow_suspended=True)


# --- Spec 3: own-client routes (client-user backwards compat) ----------------


@router.get("/me", response_model=ClientRead)
async def read_my_client(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> ClientRead:
    """Return the caller's own client; any active user of the client may view it (FR-013)."""
    if user.client_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CLIENT_NOT_FOUND")
    client = await service.get_client(session, user.client_id)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CLIENT_NOT_FOUND")
    return ClientRead.model_validate(client)


@router.patch("/me", response_model=ClientRead)
async def rename_my_client(
    payload: ClientUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ClientRead:
    """Rename the caller's own client (admin only, FR-013); audited in the same transaction."""
    if admin.client_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CLIENT_NOT_FOUND")
    client = await service.get_client(session, admin.client_id)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CLIENT_NOT_FOUND")

    if payload.name is not None and payload.name != client.name:
        try:
            await service.rename_client(session, client, payload.name)
        except service.NameConflict as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="CLIENT_NAME_TAKEN"
            ) from exc
        await request.app.state.dispatcher.dispatch(
            ClientUpdated(
                actor_id=admin.id,
                actor_type="human",
                client_id=admin.client_id,
                target_client_id=client.id,
                changes={"name": client.name},
            ),
            session,
        )

    await session.refresh(client)
    return ClientRead.model_validate(client)


# --- Spec 4b: roster (require_staff) and lifecycle (require_manager) ---------


@router.get("", response_model=list[ClientOut])
async def list_clients(
    _staff: User = Depends(require_staff),
    session: AsyncSession = Depends(get_session),
) -> list[ClientOut]:
    """List all clients ordered by id (staff-only roster; FR-008)."""
    clients = await service.list_clients(session)
    return [ClientOut.model_validate(c) for c in clients]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ClientOut)
async def create_client(
    payload: ClientCreate,
    request: Request,
    manager: User = Depends(require_manager),
    session: AsyncSession = Depends(get_session),
) -> ClientOut:
    """Create a new client (manager-only; contracts/client-lifecycle.md)."""
    try:
        email_reg = service.validate_email_address(payload.report_email_regular)
        email_urg = service.validate_email_address(payload.report_email_urgent)
    except service.InvalidEmail as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="INVALID_EMAIL"
        ) from exc

    try:
        client = await service.create_client(
            session,
            payload.name,
            report_email_regular=email_reg,
            report_email_urgent=email_urg,
            urgent_severity_threshold=(
                payload.urgent_severity_threshold.value
                if payload.urgent_severity_threshold
                else None
            ),
        )
    except service.NameConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="CLIENT_NAME_TAKEN"
        ) from exc

    await request.app.state.dispatcher.dispatch(
        ClientCreated(
            actor_id=manager.id,
            actor_type="human",
            client_id=None,
            target_client_id=client.id,
            name=client.name,
        ),
        session,
    )
    await session.refresh(client)
    return ClientOut.model_validate(client)


@router.get("/{client_id}", response_model=ClientOut)
async def get_client_detail(
    _staff: User = Depends(require_staff),
    target: Client = Depends(_get_acting_client_read),
) -> ClientOut:
    """Return a named client's full detail (staff-only; FR-008)."""
    return ClientOut.model_validate(target)


@router.post("/{client_id}/suspend", response_model=ClientOut)
async def suspend_client(
    request: Request,
    manager: User = Depends(require_manager),
    target: Client = Depends(_get_acting_client_read),
    session: AsyncSession = Depends(get_session),
) -> ClientOut:
    """Suspend a client; idempotent, data preserved, no hard-delete (FR-011/FR-012)."""
    client = await service.suspend_client(session, target)
    await request.app.state.dispatcher.dispatch(
        ClientSuspended(
            actor_id=manager.id,
            actor_type="human",
            client_id=None,
            target_client_id=client.id,
        ),
        session,
    )
    await session.refresh(client)
    return ClientOut.model_validate(client)


@router.post("/{client_id}/reactivate", response_model=ClientOut)
async def reactivate_client(
    request: Request,
    manager: User = Depends(require_manager),
    target: Client = Depends(_get_acting_client_read),
    session: AsyncSession = Depends(get_session),
) -> ClientOut:
    """Reactivate a suspended client (FR-011)."""
    client = await service.reactivate_client(session, target)
    await request.app.state.dispatcher.dispatch(
        ClientReactivated(
            actor_id=manager.id,
            actor_type="human",
            client_id=None,
            target_client_id=client.id,
        ),
        session,
    )
    await session.refresh(client)
    return ClientOut.model_validate(client)


@router.patch("/{client_id}/report-emails", response_model=ClientOut)
async def set_report_emails(
    client_id: int,
    payload: ReportEmailUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    target: Client = Depends(_get_acting_client_read),
    session: AsyncSession = Depends(get_session),
) -> ClientOut:
    """Store per-client report delivery addresses (admin-only, storage only; FR-017/FR-018)."""
    try:
        email_reg = service.validate_email_address(payload.report_email_regular)
        email_urg = service.validate_email_address(payload.report_email_urgent)
    except service.InvalidEmail as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="INVALID_EMAIL"
        ) from exc

    changes: dict = {}
    if email_reg is not None:
        changes["report_email_regular"] = email_reg
    if email_urg is not None:
        changes["report_email_urgent"] = email_urg
    if payload.urgent_severity_threshold is not None:
        changes["urgent_severity_threshold"] = payload.urgent_severity_threshold.value

    client = await service.set_report_emails(
        session,
        target,
        report_email_regular=email_reg,
        report_email_urgent=email_urg,
        urgent_severity_threshold=(
            payload.urgent_severity_threshold.value if payload.urgent_severity_threshold else None
        ),
    )

    if changes:
        await request.app.state.dispatcher.dispatch(
            ClientReportEmailChanged(
                actor_id=admin.id,
                actor_type="human",
                client_id=admin.client_id,
                target_client_id=client_id,
                changes=changes,
            ),
            session,
        )

    await session.refresh(client)
    return ClientOut.model_validate(client)


@router.patch("/{client_id}/severity-keywords", response_model=ClientOut)
async def set_severity_keywords(
    client_id: int,
    payload: SeverityKeywordsUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    target: Client = Depends(_get_acting_client_read),
    session: AsyncSession = Depends(get_session),
) -> ClientOut:
    """Replace a client's custom severity-escalation keywords (admin-only; spec 8 FR-004)."""
    before = list(target.custom_severity_keywords or [])
    client = await service.set_severity_keywords(session, target, keywords=payload.keywords)

    if list(client.custom_severity_keywords) != before:
        await request.app.state.dispatcher.dispatch(
            ClientUpdated(
                actor_id=admin.id,
                actor_type="human",
                client_id=admin.client_id,
                target_client_id=client_id,
                changes={"custom_severity_keywords": list(client.custom_severity_keywords)},
            ),
            session,
        )

    await session.refresh(client)
    return ClientOut.model_validate(client)
