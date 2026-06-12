"""Staleness sweep: INDEXED documents with zero findings past the configured age (SC-001)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.embedding.enums import DocumentIndexStatus
from app.embedding.models import DocumentIndexState
from app.ingestion.models import Document
from app.triage.models import Finding

_log = structlog.get_logger(__name__)


async def find_stale_documents(session: AsyncSession, client_id: int) -> list[int]:
    """Return document_ids that are INDEXED but have no findings and exceed the staleness age.

    These documents were embedded but never triaged (or triage was silently skipped).
    The operator alert is logged here; routing to a paging/remediation system is spec 11.
    """
    settings = get_settings()
    cutoff = datetime.now(tz=UTC) - timedelta(minutes=settings.triage_staleness_max_age_minutes)

    # INDEXED documents older than cutoff with zero findings rows
    stale_doc_ids_sq = (
        select(DocumentIndexState.document_id)
        .where(
            DocumentIndexState.status == DocumentIndexStatus.INDEXED,
            DocumentIndexState.updated_at < cutoff,
        )
        .scalar_subquery()
    )

    finding_exists_sq = select(Finding.document_id).where(Finding.document_id == Document.id)

    stmt = select(Document.id).where(
        Document.client_id == client_id,
        Document.id.in_(stale_doc_ids_sq),
        ~finding_exists_sq.exists(),
    )

    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def sweep_client(session: AsyncSession, client_id: int) -> int:
    """Log an operator signal for every stale document found; return count."""
    log = _log.bind(client_id=client_id)
    stale_ids = await find_stale_documents(session, client_id)

    for doc_id in stale_ids:
        log.warning(
            "triage.operator_alert",
            stage="sweep",
            document_id=doc_id,
            reason="indexed_with_no_finding_past_staleness_window",
        )

    if stale_ids:
        log.info("triage.sweep.done", stale_count=len(stale_ids))

    return len(stale_ids)


async def sweep_all_clients(session: AsyncSession, client_ids: list[int]) -> dict[int, int]:
    """Run the staleness sweep across a list of clients; return {client_id: stale_count}."""
    results: dict[int, int] = {}
    for cid in client_ids:
        results[cid] = await sweep_client(session, cid)
    return results
