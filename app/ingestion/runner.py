"""Ingestion runner: fan-out over ENABLED_ADAPTERS, dedup, count aggregation, persistence (D8)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import structlog

from app.core.config import Settings
from app.core.dispatcher import EventDispatcher
from app.domain.events import DocumentQuarantined
from app.guardrails.client import GuardrailsUnavailable
from app.guardrails.egress import GuardBlocked, guard_text
from app.ingestion import service
from app.ingestion.adapters import ENABLED_ADAPTERS, RawRecord, SourceAdapter, WatchlistQuery
from app.ingestion.enums import (
    IngestionRunStatus,
    MeshValidity,
    SourceName,
    SourceRunStatus,
)
from app.ingestion.identifiers import normalize_id

_log = structlog.get_logger(__name__)


async def _fetch_one(
    adapter: SourceAdapter,
    query: WatchlistQuery,
    since: datetime | None,
    cap: int,
) -> tuple[SourceAdapter, list[RawRecord] | Exception]:
    """Call one adapter; catch all exceptions so the runner can isolate failures (FR-012)."""
    try:
        records = await adapter.fetch(query, since, cap)
        return adapter, records
    except Exception as exc:  # noqa: BLE001
        return adapter, exc


async def run_ingestion(
    *,
    run_id: int,
    client_id: int,
    watchlist_id: int,
    watchlist_items: list,  # ORM WatchlistItem rows (or duck-typed equivalent)
    session_factory: Callable,
    initial_lookback_days: int = 365,
    per_source_cap: int = 200,
    adapters: list[SourceAdapter] | None = None,
    settings: Settings | None = None,
    dispatcher: EventDispatcher | None = None,
) -> None:
    """Execute a full ingestion run: fan-out, dedup, persist, finish the run record.

    Uses the supplied session_factory so this function is framework-agnostic and callable from
    spec-11 ARQ without modification (D8). Each adapter is isolated: failure ≠ abort.

    When ``settings`` is provided, each fetched document passes an intake guardrails scan
    (FR-006a) before persistence; a blocked/unavailable scan quarantines that document
    (held out of indexing+triage, DocumentQuarantined audited) and the cycle continues.
    """
    used_adapters = adapters if adapters is not None else ENABLED_ADAPTERS
    log = _log.bind(run_id=run_id, client_id=client_id, watchlist_id=watchlist_id)

    # Build query from valid/unvalidated MeSH terms only (FR-010).
    drugs = [i.value for i in watchlist_items if i.item_type == "drug"]
    keywords = [i.value for i in watchlist_items if i.item_type == "keyword"]
    mesh_terms = [
        i.value
        for i in watchlist_items
        if i.item_type == "mesh"
        and (
            not hasattr(i, "mesh_validity")
            or i.mesh_validity is None
            or i.mesh_validity != MeshValidity.INVALID.value
        )
    ]
    query = WatchlistQuery(drugs=drugs, keywords=keywords, mesh_terms=mesh_terms)

    async with session_factory() as session:
        async with session.begin():
            # Read watermarks before fan-out.
            watermarks: dict[SourceName, datetime | None] = {}
            now = datetime.now(UTC)
            lookback_start = now - timedelta(days=initial_lookback_days)
            for adapter in used_adapters:
                wm = await service.get_watermark(session, watchlist_id, adapter.name)
                watermarks[adapter.name] = (
                    wm.watermark_at if wm and wm.watermark_at else lookback_start
                )

    # Fan-out: all adapters concurrently (FR-011 isolation handled below).
    results = await asyncio.gather(
        *[
            _fetch_one(
                adapter,
                query,
                watermarks[adapter.name],
                per_source_cap,
            )
            for adapter in used_adapters
        ]
    )

    # Persist each source's results, accumulating run-level counts.
    total_fetched = total_created = total_skipped = total_errored = 0
    source_statuses: list[SourceRunStatus] = []

    async with session_factory() as session:
        async with session.begin():
            for adapter, outcome in results:
                if isinstance(outcome, Exception):
                    error_msg = str(outcome)
                    log.warning(
                        "ingestion.source_failed",
                        source=adapter.name,
                        error=error_msg,
                    )
                    await service.create_source_record(
                        session,
                        run_id=run_id,
                        client_id=client_id,
                        source=adapter.name,
                        status=SourceRunStatus.FAILED,
                        error=error_msg,
                    )
                    source_statuses.append(SourceRunStatus.FAILED)
                    continue

                records: list[RawRecord] = outcome
                fetched = len(records)
                src_created = src_skipped = src_errored = 0

                # Within-run dedup: track normalized ids seen in this run.
                seen_in_run: set[str] = set()

                for record in records:
                    # Use record.source (not adapter.name) so OpenFDA label vs FAERS are
                    # tracked independently; also honours any record-level reliability override.
                    rec_source = record.source
                    rec_reliability = record.reliability or adapter.reliability
                    norm_id = normalize_id(
                        doi=record.doi,
                        pmid=record.pmid,
                        source=rec_source,
                        source_external_id=record.source_external_id,
                    )
                    if norm_id is None:
                        log.debug("ingestion.record_unidentifiable", source=rec_source)
                        src_errored += 1
                        continue

                    if norm_id in seen_in_run:
                        src_skipped += 1
                        continue
                    seen_in_run.add(norm_id)

                    # Intake guardrails scan (FR-006a): on block/outage, quarantine the
                    # document (held out of indexing+triage) and continue the cycle. Pass no
                    # dispatcher to guard_text so it raises without emitting a triage/agent
                    # event; intake emits DocumentQuarantined instead.
                    if settings is not None:
                        doc_text = "\n".join(p for p in (record.title, record.summary) if p)
                        try:
                            await guard_text(
                                settings,
                                text=doc_text,
                                direction="input",
                                client_id=client_id,
                                call_site="intake",
                            )
                        except (GuardBlocked, GuardrailsUnavailable) as exc:
                            reason = (
                                "intake_guard_blocked"
                                if isinstance(exc, GuardBlocked)
                                else "guardrails_unavailable"
                            )
                            log.warning(
                                "ingestion.document_quarantined",
                                source=rec_source,
                                norm_id=norm_id,
                                reason=reason,
                            )
                            if dispatcher is not None:
                                await dispatcher.dispatch(
                                    DocumentQuarantined(
                                        actor_id=0,
                                        actor_type="system",
                                        client_id=client_id,
                                        document_id=0,
                                        reason=reason,
                                    ),
                                    session,
                                )
                            src_skipped += 1
                            continue

                    try:
                        _, created = await service.upsert_document(
                            session,
                            client_id=client_id,
                            normalized_external_id=norm_id,
                            source=rec_source,
                            source_external_id=record.source_external_id,
                            source_reliability=rec_reliability,
                            raw_payload=record.raw_payload,
                            title=record.title,
                            summary=record.summary,
                            published_at=record.published_at,
                            origin_url=record.origin_url,
                            watchlist_id=watchlist_id,
                            run_id=run_id,
                        )
                        if created:
                            src_created += 1
                        else:
                            src_skipped += 1
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "ingestion.record_persist_failed",
                            source=rec_source,
                            norm_id=norm_id,
                            error=str(exc),
                        )
                        src_errored += 1

                # Advance watermark only on source success (FR-021).
                new_watermark = (
                    max(
                        (r.published_at for r in records if r.published_at),
                        default=None,
                    )
                    if records
                    else None
                )
                await service.advance_watermark(
                    session,
                    client_id=client_id,
                    watchlist_id=watchlist_id,
                    source=adapter.name,
                    watermark_at=new_watermark or watermarks[adapter.name],
                )

                await service.create_source_record(
                    session,
                    run_id=run_id,
                    client_id=client_id,
                    source=adapter.name,
                    status=SourceRunStatus.SUCCESS,
                    fetched=fetched,
                    created=src_created,
                    skipped=src_skipped,
                    errored=src_errored,
                )
                source_statuses.append(SourceRunStatus.SUCCESS)

                total_fetched += fetched
                total_created += src_created
                total_skipped += src_skipped
                total_errored += src_errored

                log.info(
                    "ingestion.source_done",
                    source=adapter.name,
                    fetched=fetched,
                    created=src_created,
                    skipped=src_skipped,
                    errored=src_errored,
                )

            # Derive overall run status (FR-011).
            if not source_statuses:
                overall = IngestionRunStatus.FAILED
            elif all(s == SourceRunStatus.SUCCESS for s in source_statuses):
                overall = IngestionRunStatus.SUCCESS
            elif any(s == SourceRunStatus.SUCCESS for s in source_statuses):
                overall = IngestionRunStatus.PARTIAL_SUCCESS
            else:
                overall = IngestionRunStatus.FAILED

            run = await session.get(service.IngestionRun, run_id)
            if run is not None:
                await service.finish_run(
                    session,
                    run,
                    overall,
                    fetched=total_fetched,
                    created=total_created,
                    skipped=total_skipped,
                    errored=total_errored,
                )

    log.info(
        "ingestion.run_done",
        status=overall.value,
        fetched=total_fetched,
        created=total_created,
        skipped=total_skipped,
        errored=total_errored,
    )


def build_watchlist_query(watchlist_items: list) -> WatchlistQuery:
    """Build a WatchlistQuery from ORM WatchlistItem rows (re-usable helper)."""
    drugs = [i.value for i in watchlist_items if i.item_type == "drug"]
    keywords = [i.value for i in watchlist_items if i.item_type == "keyword"]
    mesh_terms = [
        i.value
        for i in watchlist_items
        if i.item_type == "mesh"
        and (
            not hasattr(i, "mesh_validity")
            or i.mesh_validity is None
            or i.mesh_validity != MeshValidity.INVALID.value
        )
    ]
    return WatchlistQuery(drugs=drugs, keywords=keywords, mesh_terms=mesh_terms)
