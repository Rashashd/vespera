"""Document browse endpoints (contracts/documents.md)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_acting_client_read
from app.clients.models import Client
from app.core.dependencies import get_session
from app.ingestion.enums import SourceName, SourceReliability
from app.ingestion.models import Document, DocumentSource, DocumentWatchlist
from app.ingestion.schemas import DocumentDetailOut, DocumentOut

router = APIRouter(prefix="/clients/{client_id}/documents", tags=["documents"])


async def _get_doc(session: AsyncSession, client_id: int, document_id: int) -> Document | None:
    """Fetch a document scoped to the target client; cross-tenant ⇒ None."""
    stmt = (
        select(Document)
        .where(Document.id == document_id, Document.client_id == client_id)
        .options(
            selectinload(Document.sources),
            selectinload(Document.provenance),
        )
    )
    return (await session.scalars(stmt)).first()


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    watchlist_id: int | None = Query(default=None),
    source: SourceName | None = Query(default=None),
    reliability: SourceReliability | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    target: Client = Depends(get_acting_client_read),
    session: AsyncSession = Depends(get_session),
) -> list[DocumentOut]:
    """List the target client's ingested documents, newest last_fetched_at first (SC-004)."""
    stmt = (
        select(Document)
        .where(Document.client_id == target.id)
        .options(selectinload(Document.sources), selectinload(Document.provenance))
        .order_by(Document.last_fetched_at.desc())
        .limit(limit)
        .offset(offset)
    )

    if reliability is not None:
        stmt = stmt.where(Document.source_reliability == reliability.value)

    if source is not None:
        stmt = stmt.where(
            Document.id.in_(
                select(DocumentSource.document_id).where(
                    DocumentSource.client_id == target.id,
                    DocumentSource.source == source.value,
                )
            )
        )

    if watchlist_id is not None:
        stmt = stmt.where(
            Document.id.in_(
                select(DocumentWatchlist.document_id).where(
                    DocumentWatchlist.client_id == target.id,
                    DocumentWatchlist.watchlist_id == watchlist_id,
                )
            )
        )

    docs = list((await session.scalars(stmt)).all())
    return [DocumentOut.from_orm(d) for d in docs]


@router.get("/{document_id}", response_model=DocumentDetailOut)
async def get_document(
    document_id: int,
    target: Client = Depends(get_acting_client_read),
    session: AsyncSession = Depends(get_session),
) -> DocumentDetailOut:
    """Document detail with per-source metadata; cross-tenant → 404 (SC-004)."""
    doc = await _get_doc(session, target.id, document_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DOCUMENT_NOT_FOUND")
    return DocumentDetailOut.from_orm(doc)
