"""Triage orchestration: thin coordinator delegating to per-stage modules (FR-002–FR-011)."""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.dispatcher import EventDispatcher
from app.domain.events import FindingClassified
from app.infra.modelserver_client import ModelserverClient
from app.triage import llm as llm_module
from app.triage.classify import resolve_adverse
from app.triage.enums import Bucket
from app.triage.ner import extract_entities, reaction_or_sentinel
from app.triage.routing import bucket_to_status, upsert_finding
from app.triage.schemas import FindingOutcome
from app.triage.severity import assign_bucket

_log = structlog.get_logger(__name__)


async def triage_document(
    *,
    session: AsyncSession,
    document_id: int,
    client_id: int,
    document_text: str,
    source_reliability: str,
    watchlist_drugs: list[str],
    custom_keywords: list[dict],
    ms_client: ModelserverClient,
    settings: Settings,
    dispatcher: EventDispatcher,
) -> list[FindingOutcome]:
    """Classify one document and persist all findings within the caller's session.

    Returns a list of FindingOutcome DTOs (one per drug×reaction pair found).
    The dispatcher is called inside this function so audit rows are atomic with the finding write.
    Callers must wrap this in `async with session.begin()`.
    """
    log = _log.bind(client_id=client_id, document_id=document_id)
    outcomes: list[FindingOutcome] = []

    # --- Stage 1: NER entity extraction ---
    drugs_found, reactions_found = await extract_entities(document_text)
    log.info("triage.ner.extracted", drugs=len(drugs_found), reactions=len(reactions_found))

    # --- Stage 2: Drug pre-filter (match against watchlist) ---
    normalized_watchlist = {d.strip().lower() for d in watchlist_drugs}
    matched_drugs = [d for d in drugs_found if d in normalized_watchlist]

    if not matched_drugs:
        log.info("triage.prefilter.no_drug_match", document_id=document_id)
        return outcomes

    # For each matched drug, create one finding (using first reaction or sentinel)
    reaction = reaction_or_sentinel(reactions_found)

    for drug in matched_drugs:
        outcome = await _triage_one(
            session=session,
            document_id=document_id,
            client_id=client_id,
            drug=drug,
            reaction=reaction,
            document_text=document_text,
            source_reliability=source_reliability,
            custom_keywords=custom_keywords,
            ms_client=ms_client,
            settings=settings,
            dispatcher=dispatcher,
            log=log,
        )
        outcomes.append(outcome)

    return outcomes


async def _triage_one(
    *,
    session: AsyncSession,
    document_id: int,
    client_id: int,
    drug: str,
    reaction: str,
    document_text: str,
    source_reliability: str,
    custom_keywords: list[dict],
    ms_client: ModelserverClient,
    settings: Settings,
    dispatcher: EventDispatcher,
    log,
) -> FindingOutcome:
    """Classify a single drug+reaction pair and persist the finding."""

    # --- Stage 3: Three-stage classify decision ---
    async def _llm_resolve(text: str, reliability: str) -> bool:
        return await llm_module.resolve_yes_no(text, reliability, settings, client_id, document_id)

    verdict, model_confidence, resolution_path = await resolve_adverse(
        text=document_text,
        ms_client=ms_client,
        settings=settings,
        llm_resolve_fn=_llm_resolve,
        source_reliability=source_reliability,
        client_id=client_id,
        document_id=document_id,
    )

    # --- Stage 4: Severity bucketing ---
    if verdict:
        bucket = assign_bucket(
            verdict=True,
            text=document_text,
            source_reliability=source_reliability,
            custom_keywords=custom_keywords,
        )
    else:
        # NO verdict → LLM valence assessment
        valence = await llm_module.assess_valence(
            document_text, source_reliability, settings, client_id, document_id
        )
        bucket = Bucket.POSITIVE if valence == "positive" else Bucket.IRRELEVANT

    status = bucket_to_status(bucket)

    # --- Stage 5: Idempotent upsert + atomic audit dispatch ---
    finding_id, created = await upsert_finding(
        session,
        client_id=client_id,
        document_id=document_id,
        drug=drug,
        reaction=reaction,
        bucket=bucket,
        resolution_path=resolution_path,
        model_confidence=model_confidence,
    )

    if created:
        event = FindingClassified(
            actor_id=0,
            actor_type="system",
            client_id=client_id,
            finding_id=finding_id,
            bucket=bucket.value,
            confidence=model_confidence or 0.0,
            resolution_path=resolution_path,
            routing_outcome=status.value,
        )
        await dispatcher.dispatch(event, session)
        log.info(
            "triage.finding.created",
            finding_id=finding_id,
            bucket=bucket.value,
            resolution_path=resolution_path,
        )
    else:
        log.info("triage.finding.idempotent", finding_id=finding_id)

    return FindingOutcome(
        document_id=document_id,
        drug=drug,
        reaction=reaction,
        bucket=bucket,
        status=status,
        model_confidence=model_confidence,
        resolution_path=resolution_path,
        finding_id=finding_id,
        created=created,
    )
