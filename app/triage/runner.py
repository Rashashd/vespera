"""Per-document triage entrypoint invoked by the embedding runner (FR-009)."""

from __future__ import annotations

from collections.abc import Callable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dispatcher import EventDispatcher
from app.infra.modelserver_client import ModelserverClient
from app.triage.schemas import FindingOutcome
from app.triage.service import triage_document

_log = structlog.get_logger(__name__)


async def triage_document_runner(
    session_factory: Callable[[], AsyncSession],
    document_id: int,
    client_id: int,
    document_text: str,
    source_reliability: str,
    watchlist_drugs: list[str],
    custom_keywords: list[dict],
    ms_client: ModelserverClient,
    dispatcher: EventDispatcher,
) -> list[FindingOutcome]:
    """Triage a single document; persist findings atomically.

    Wraps triage_document() in its own transaction.
    Returns FindingOutcome list (may be empty if document is filtered).
    """
    log = _log.bind(client_id=client_id, document_id=document_id)
    settings = get_settings()

    async with session_factory() as session:
        async with session.begin():
            outcomes = await triage_document(
                session=session,
                document_id=document_id,
                client_id=client_id,
                document_text=document_text,
                source_reliability=source_reliability,
                watchlist_drugs=watchlist_drugs,
                custom_keywords=custom_keywords,
                ms_client=ms_client,
                settings=settings,
                dispatcher=dispatcher,
            )

    log.info(
        "triage.runner.done",
        document_id=document_id,
        findings_created=sum(1 for o in outcomes if o.created),
        findings_total=len(outcomes),
    )
    return outcomes
