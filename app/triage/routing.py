"""Bucket→status mapping and idempotent finding upsert (FR-006/007/008/010)."""

from __future__ import annotations

from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.triage.enums import Bucket, FindingStatus
from app.triage.models import Finding

_log = structlog.get_logger(__name__)

_BUCKET_TO_STATUS: dict[Bucket, FindingStatus] = {
    Bucket.EMERGENCY: FindingStatus.PENDING_EXPEDITED,
    Bucket.URGENT: FindingStatus.PENDING_EXPEDITED,
    Bucket.MINOR: FindingStatus.PENDING_BATCH,
    Bucket.POSITIVE: FindingStatus.PENDING_BATCH,
    Bucket.IRRELEVANT: FindingStatus.CLASSIFIED,
}


def bucket_to_status(bucket: Bucket) -> FindingStatus:
    """Return the queue status for a given severity bucket."""
    return _BUCKET_TO_STATUS[bucket]


async def upsert_finding(
    session: AsyncSession,
    *,
    client_id: int,
    document_id: int,
    drug: str,
    reaction: str,
    bucket: Bucket,
    resolution_path: str,
    model_confidence: float | None,
) -> tuple[int, bool]:
    """Insert a finding idempotently; return (finding_id, created).

    ON CONFLICT (document_id, drug, reaction) DO NOTHING → returns existing id when conflict.
    created=False means the finding already existed; skip re-dispatching the audit event.
    """
    status = bucket_to_status(bucket)
    confidence_val = (
        Decimal(str(round(model_confidence, 4))) if model_confidence is not None else None
    )

    stmt = (
        pg_insert(Finding)
        .values(
            client_id=client_id,
            document_id=document_id,
            drug=drug,
            reaction=reaction,
            bucket=bucket.value,
            status=status.value,
            model_confidence=confidence_val,
            resolution_path=resolution_path,
            corroboration_sources=None,
        )
        .on_conflict_do_nothing(index_elements=["document_id", "drug", "reaction"])
        .returning(Finding.id)
    )
    result = await session.execute(stmt)
    row = result.fetchone()

    if row is not None:
        return row[0], True

    # Conflict: fetch the existing finding id
    existing = await session.execute(
        select(Finding.id).where(
            Finding.document_id == document_id,
            Finding.drug == drug,
            Finding.reaction == reaction,
        )
    )
    existing_id = existing.scalar_one()
    _log.info(
        "triage.routing.idempotent",
        client_id=client_id,
        document_id=document_id,
        finding_id=existing_id,
    )
    return existing_id, False
