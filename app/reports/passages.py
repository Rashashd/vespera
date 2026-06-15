"""Passage-text resolution endpoint (FR-029): GET /clients/{id}/passages/{chunk_id}."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import acting_client, current_active_principal
from app.auth.models import User
from app.auth.schemas import UserType
from app.clients.models import Client
from app.core.dependencies import get_session
from app.embedding.models import Chunk
from app.ingestion.models import Document
from app.reports.models import Report
from app.reports.schemas import PassageResponse

router = APIRouter(prefix="/clients/{client_id}", tags=["passages"])

_get_client_read = acting_client(allow_suspended=True)

_PORTAL_STATUSES = ("approved", "sent", "delivered")


async def _client_visible_chunk_ids(session: AsyncSession, client_id: int) -> set[int]:
    """Chunk ids a client-user may read: those cited by the client's approved+sent reports.

    Prevents a client-user from enumerating the whole corpus via /passages/{id}; staff are
    not subject to this (they may read any chunk for the acting client, FR-029).
    """
    rows = (
        await session.execute(
            select(Report.structured_fields, Report.corroboration_sources).where(
                Report.client_id == client_id,
                Report.status.in_(_PORTAL_STATUSES),
            )
        )
    ).all()
    allowed: set[int] = set()
    for structured_fields, corroboration_sources in rows:
        for claim in structured_fields or []:
            ref = claim.get("source_ref")
            if ref is not None:
                try:
                    allowed.add(int(ref))
                except (ValueError, TypeError):
                    pass
        for src in corroboration_sources or []:
            for cid in src.get("passage_chunk_ids") or []:
                try:
                    allowed.add(int(cid))
                except (ValueError, TypeError):
                    pass
    return allowed


@router.get("/passages/{chunk_id}", response_model=PassageResponse)
async def get_passage(
    chunk_id: int,
    principal: User = Depends(current_active_principal),
    client: Client = Depends(_get_client_read),
    session: AsyncSession = Depends(get_session),
) -> PassageResponse:
    """Return the exact passage text for a chunk (reviewer + client-user safe via acting_client)."""
    chunk = (
        await session.execute(
            select(Chunk).where(Chunk.id == chunk_id, Chunk.client_id == client.id)
        )
    ).scalar_one_or_none()

    if chunk is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="PASSAGE_UNAVAILABLE")

    # Client-users may only read passages cited by their approved+sent reports (not the whole
    # corpus). Staff (reviewer/admin/manager) may read any chunk for the acting client (FR-029).
    if principal.user_type == UserType.CLIENT.value:
        allowed = await _client_visible_chunk_ids(session, client.id)
        if chunk_id not in allowed:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="PASSAGE_UNAVAILABLE")

    # Fetch document title / external_id
    doc = await session.get(Document, chunk.document_id)
    title = doc.title if doc else None
    external_id = doc.normalized_external_id if doc else None

    return PassageResponse(
        chunk_id=chunk.id,
        text=chunk.text,
        section=chunk.section,
        source_reliability=chunk.source_reliability,
        date=chunk.date,
        document_id=chunk.document_id,
        title=title,
        external_id=external_id,
    )
