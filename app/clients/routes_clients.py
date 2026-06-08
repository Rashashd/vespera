"""Routes for the caller's own client: GET /clients/me (read) and PATCH /clients/me (rename)."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import current_active_user, require_admin
from app.auth.models import User
from app.clients import service
from app.clients.schemas import ClientRead, ClientUpdate
from app.core.dependencies import get_session
from app.domain.events import ClientUpdated

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("/me", response_model=ClientRead)
async def read_my_client(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> ClientRead:
    """Return the caller's own client; any active user of the client may view it (FR-013)."""
    client = await service.get_client(session, user.client_id)
    if client is None:  # defensive: every user resolves to a real client post-migration
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
