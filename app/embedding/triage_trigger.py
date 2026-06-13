"""After-index hook: run triage on a freshly-indexed document, then schedule expedited drafting."""

import asyncio
from collections.abc import Callable
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.modelserver_client import ModelserverClient

_log = structlog.get_logger(__name__)


async def trigger_triage(
    *,
    session_factory: Callable[[], AsyncSession],
    document: Any,
    chunk_texts: list[str],
    client_id: int,
    modelserver_client: ModelserverClient,
    dispatcher: Any,
    app_state: Any = None,
) -> None:
    """Call triage then schedule expedited drafting for urgent/emergency findings (FR-009)."""
    try:
        from app.clients.models import Client, WatchlistItem
        from app.triage.runner import triage_document_runner

        document_text = " ".join(chunk_texts)

        # Load watchlist drug items for this document's provenance watchlists.
        watchlist_ids = [dw.watchlist_id for dw in (document.provenance or [])]
        watchlist_drugs: list[str] = []
        custom_keywords: list[dict] = []

        if watchlist_ids:
            async with session_factory() as session:
                items_result = await session.execute(
                    select(WatchlistItem).where(
                        WatchlistItem.watchlist_id.in_(watchlist_ids),
                        WatchlistItem.item_type == "drug",
                    )
                )
                watchlist_drugs = [i.value for i in items_result.scalars().all()]

                client_result = await session.execute(select(Client).where(Client.id == client_id))
                client_obj = client_result.scalar_one_or_none()
                if client_obj is not None:
                    custom_keywords = client_obj.custom_severity_keywords or []

        if not watchlist_drugs:
            _log.info(
                "triage.skip.no_watchlist_drugs",
                document_id=document.id,
                client_id=client_id,
            )
            return

        outcomes = await triage_document_runner(
            session_factory=session_factory,
            document_id=document.id,
            client_id=client_id,
            document_text=document_text,
            source_reliability=document.source_reliability,
            watchlist_drugs=watchlist_drugs,
            custom_keywords=custom_keywords,
            ms_client=modelserver_client,
            dispatcher=dispatcher,
        )

        # Schedule expedited drafting for urgent/emergency findings (spec 9).
        # Triage already committed, so findings are durable before we schedule.
        if app_state is not None:
            from app.reports.runner import draft_expedited
            from app.triage.enums import Bucket

            for outcome in outcomes:
                if (
                    outcome.created
                    and outcome.finding_id is not None
                    and outcome.bucket in (Bucket.URGENT, Bucket.EMERGENCY)
                ):
                    asyncio.create_task(draft_expedited(outcome.finding_id, app_state))
    except Exception as exc:
        _log.error(
            "triage.after_index.failed",
            document_id=document.id,
            client_id=client_id,
            error=str(exc),
            exc_info=True,
        )
