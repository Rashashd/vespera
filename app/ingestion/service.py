"""Ingestion persistence: dedup upsert, provenance, watermark, run record management (D10)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.enums import (
    IngestionRunStatus,
    SourceName,
    SourceReliability,
    SourceRunStatus,
)
from app.ingestion.models import (
    Document,
    DocumentSource,
    DocumentWatchlist,
    IngestionRun,
    IngestionRunSource,
    SourceWatermark,
)

# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------


async def create_run(
    session: AsyncSession,
    *,
    client_id: int,
    watchlist_id: int,
    triggered_by_user_id: int,
) -> IngestionRun:
    """Insert a new ingestion run in `running` status."""
    run = IngestionRun(
        client_id=client_id,
        watchlist_id=watchlist_id,
        triggered_by_user_id=triggered_by_user_id,
        status=IngestionRunStatus.RUNNING.value,
    )
    session.add(run)
    await session.flush()
    await session.refresh(run)
    return run


async def get_run(session: AsyncSession, client_id: int, run_id: int) -> IngestionRun | None:
    """Fetch a run scoped to the caller's client; cross-tenant ⇒ None."""
    run = await session.get(IngestionRun, run_id)
    if run is None or run.client_id != client_id:
        return None
    return run


async def list_runs(
    session: AsyncSession,
    client_id: int,
    watchlist_id: int,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[IngestionRun]:
    """List runs for a watchlist, newest started_at first."""
    stmt = (
        select(IngestionRun)
        .where(
            IngestionRun.client_id == client_id,
            IngestionRun.watchlist_id == watchlist_id,
        )
        .order_by(IngestionRun.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list((await session.scalars(stmt)).all())


async def finish_run(
    session: AsyncSession,
    run: IngestionRun,
    status: IngestionRunStatus,
    *,
    fetched: int,
    created: int,
    skipped: int,
    errored: int,
) -> None:
    """Update a run to its terminal status with aggregate counts and finished_at."""
    run.status = status.value
    run.finished_at = datetime.now(UTC)
    run.fetched_count = fetched
    run.created_count = created
    run.skipped_count = skipped
    run.errored_count = errored
    session.add(run)
    await session.flush()


async def create_source_record(
    session: AsyncSession,
    *,
    run_id: int,
    client_id: int,
    source: SourceName,
    status: SourceRunStatus,
    error: str | None = None,
    fetched: int = 0,
    created: int = 0,
    skipped: int = 0,
    errored: int = 0,
) -> IngestionRunSource:
    """Insert a per-source outcome row for the run."""
    src = IngestionRunSource(
        run_id=run_id,
        client_id=client_id,
        source=source.value,
        status=status.value,
        error=error,
        fetched_count=fetched,
        created_count=created,
        skipped_count=skipped,
        errored_count=errored,
    )
    session.add(src)
    await session.flush()
    return src


# ---------------------------------------------------------------------------
# Startup sweep: reconcile interrupted runs
# ---------------------------------------------------------------------------


async def reconcile_interrupted_runs(session: AsyncSession) -> int:
    """Flip any lingering `running` runs → `failed` (FR-024, D8). Returns count updated."""
    now = datetime.now(UTC)
    result = await session.execute(
        update(IngestionRun)
        .where(IngestionRun.status == IngestionRunStatus.RUNNING.value)
        .values(status=IngestionRunStatus.FAILED.value, finished_at=now)
    )
    await session.flush()
    return result.rowcount  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Watermark
# ---------------------------------------------------------------------------


async def get_watermark(
    session: AsyncSession, watchlist_id: int, source: SourceName
) -> SourceWatermark | None:
    """Read the per-(watchlist, source) watermark."""
    result = await session.execute(
        select(SourceWatermark).where(
            SourceWatermark.watchlist_id == watchlist_id,
            SourceWatermark.source == source.value,
        )
    )
    return result.scalar_one_or_none()


async def advance_watermark(
    session: AsyncSession,
    *,
    client_id: int,
    watchlist_id: int,
    source: SourceName,
    watermark_at: datetime | None,
    cursor: str | None = None,
) -> None:
    """Upsert the watermark; only called when the source run succeeded (FR-021)."""
    stmt = (
        pg_insert(SourceWatermark)
        .values(
            client_id=client_id,
            watchlist_id=watchlist_id,
            source=source.value,
            watermark_at=watermark_at,
            cursor=cursor,
        )
        .on_conflict_do_update(
            index_elements=["watchlist_id", "source"],
            set_={"watermark_at": watermark_at, "cursor": cursor, "updated_at": datetime.now(UTC)},
        )
    )
    await session.execute(stmt)
    await session.flush()


# ---------------------------------------------------------------------------
# Document dedup upsert
# ---------------------------------------------------------------------------


async def _try_flush(session: AsyncSession) -> bool:
    """Savepoint flush; return False on unique violation (race-safe, spec-3 pattern)."""
    try:
        async with session.begin_nested():
            await session.flush()
        return True
    except IntegrityError:
        return False


def _highest_reliability(reliabilities: list[str]) -> str:
    """Return the highest-rank SourceReliability value from a list."""
    return max(reliabilities, key=lambda r: SourceReliability(r).rank)


async def upsert_document(
    session: AsyncSession,
    *,
    client_id: int,
    normalized_external_id: str,
    source: SourceName,
    source_external_id: str,
    source_reliability: SourceReliability,
    raw_payload: dict,
    title: str | None,
    summary: str | None,
    published_at: datetime | None,
    origin_url: str | None,
    watchlist_id: int,
    run_id: int,
) -> tuple[Document, bool]:
    """Upsert a document and its source/provenance rows; return (doc, created).

    - New document: INSERT via ON CONFLICT DO NOTHING on the unique index, then reload.
    - Existing document: add new DocumentSource (if not present), update source_reliability to
      highest rank, bump last_fetched_at, upsert DocumentWatchlist provenance.
    Race-safety: uses the savepoint flush pattern from spec 3.
    """
    # Try to insert the document; ON CONFLICT DO NOTHING on the dedup unique index.
    doc_stmt = (
        pg_insert(Document)
        .values(
            client_id=client_id,
            normalized_external_id=normalized_external_id,
            source_reliability=source_reliability.value,
            title=title,
            summary=summary,
            published_at=published_at,
            origin_url=origin_url,
        )
        .on_conflict_do_nothing(index_elements=["client_id", "normalized_external_id"])
        .returning(Document.id)
    )
    new_doc_id = await session.scalar(doc_stmt)
    created = new_doc_id is not None

    # Load the document (whether newly created or pre-existing).
    if not created:
        result = await session.execute(
            select(Document).where(
                Document.client_id == client_id,
                Document.normalized_external_id == normalized_external_id,
            )
        )
        doc = result.scalar_one()
    else:
        doc = await session.get(Document, new_doc_id)

    # Upsert the contributing DocumentSource row (one per source per document).
    src_stmt = (
        pg_insert(DocumentSource)
        .values(
            document_id=doc.id,
            client_id=client_id,
            source=source.value,
            source_external_id=source_external_id,
            source_reliability=source_reliability.value,
            raw_payload=raw_payload,
        )
        .on_conflict_do_nothing(index_elements=["document_id", "source"])
    )
    await session.execute(src_stmt)

    if not created:
        # Recompute document reliability as the highest across all contributing sources.
        all_sources = list(
            (
                await session.scalars(
                    select(DocumentSource.source_reliability).where(
                        DocumentSource.document_id == doc.id
                    )
                )
            ).all()
        )
        all_sources.append(source_reliability.value)
        new_reliability = _highest_reliability(all_sources)
        doc.source_reliability = new_reliability
        doc.last_fetched_at = datetime.now(UTC)
        session.add(doc)

    # Upsert provenance link (idempotent — one row per document+watchlist).
    prov_stmt = (
        pg_insert(DocumentWatchlist)
        .values(
            document_id=doc.id,
            watchlist_id=watchlist_id,
            client_id=client_id,
            first_run_id=run_id if created else None,
        )
        .on_conflict_do_nothing(index_elements=["document_id", "watchlist_id"])
    )
    await session.execute(prov_stmt)

    if not await _try_flush(session):
        # Concurrent race on an insert that ON CONFLICT should have handled — reload and continue.
        result = await session.execute(
            select(Document).where(
                Document.client_id == client_id,
                Document.normalized_external_id == normalized_external_id,
            )
        )
        doc = result.scalar_one()
        created = False

    return doc, created
