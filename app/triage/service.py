"""Triage orchestration: thin coordinator delegating to per-stage modules (FR-002–FR-011)."""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.dispatcher import EventDispatcher
from app.domain.events import FindingClassified
from app.infra.modelserver_client import ModelserverClient, ModelserverError
from app.observability.sentry import capture_operator_alert
from app.triage import llm as llm_module
from app.triage import prefilter
from app.triage.classify import resolve_adverse
from app.triage.enums import Bucket
from app.triage.ner import NerUnavailable, extract_entities, reaction_or_sentinel
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
    # A NER outage must NOT masquerade as "no entities found" (which would silently drop the
    # whole document). Surface it as an alerted, typed failure and re-raise so the after-index
    # hook marks the document degraded (Constitution III) instead of swallowing it.
    try:
        drugs_found, reactions_found = await extract_entities(document_text)
    except NerUnavailable as exc:
        log.error(
            "triage.operator_alert",
            stage="ner",
            reason=str(exc),
            client_id=client_id,
            document_id=document_id,
        )
        capture_operator_alert(
            "triage.operator_alert",
            stage="ner",
            client_id=client_id,
            document_id=document_id,
            error_class=type(exc).__name__,
        )
        raise
    log.info("triage.ner.extracted", drugs=len(drugs_found), reactions=len(reactions_found))

    # --- Stage 2: Drug pre-filter (match against watchlist) ---
    normalized_watchlist = {d.strip().lower() for d in watchlist_drugs}
    matched_drugs = [d for d in drugs_found if d in normalized_watchlist]

    if not matched_drugs:
        log.info("triage.prefilter.no_drug_match", document_id=document_id)
        return outcomes

    # --- Stage 2b: Substantive-mention filter (US2, FR-001) ---
    matched_drugs = await prefilter.filter_substantive_drugs(
        document_text,
        matched_drugs,
        client_id=client_id,
        document_id=document_id,
    )
    if not matched_drugs:
        log.info("triage.prefilter.all_incidental", document_id=document_id)
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
        if outcome is not None:
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
) -> FindingOutcome | None:
    """Classify a single drug+reaction pair and persist the finding.

    On classifier OUTAGE (ModelserverError) the verdict is forced to YES and escalated
    (resolution_path="escalated") rather than skipped — a classifier failure MUST escalate,
    not suppress (Constitution III) — mirroring the low-confidence path in classify.py:55-57.
    Raises on DB/persist failure so the caller's transaction rolls back (FR-018).
    """

    # --- Stage 3: Three-stage classify decision ---
    async def _llm_resolve(text: str, reliability: str) -> bool:
        return await llm_module.resolve_yes_no(
            text,
            reliability,
            settings,
            client_id,
            document_id,
            session=session,
            dispatcher=dispatcher,
        )

    try:
        verdict, model_confidence, resolution_path, classifier_version = await resolve_adverse(
            text=document_text,
            ms_client=ms_client,
            settings=settings,
            llm_resolve_fn=_llm_resolve,
            source_reliability=source_reliability,
            client_id=client_id,
            document_id=document_id,
        )
    except ModelserverError as exc:
        # Fail SAFE (Constitution III): a classifier OUTAGE must escalate, never suppress.
        # Mirror the low-confidence+LLM-failure path (classify.py:55-57): force verdict=YES with
        # resolution_path="escalated" and no model confidence, so the pair is still severity-
        # bucketed, persisted, and surfaced to a human instead of being silently dropped.
        log.error(
            "triage.operator_alert",
            stage="classify",
            reason=str(exc),
            client_id=client_id,
            document_id=document_id,
        )
        capture_operator_alert(
            "triage.operator_alert",
            stage="classify",
            client_id=client_id,
            document_id=document_id,
            error_class=type(exc).__name__,
        )
        # No classifier_version: the classifier never ran (a NULL version is how a triage-outage
        # escalation is told apart from a low-confidence one in the finding/audit record).
        verdict, model_confidence, resolution_path, classifier_version = (
            True,
            None,
            "escalated",
            None,
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
        # NO verdict → LLM valence assessment; assess_valence defaults to "positive" on failure
        valence = await llm_module.assess_valence(
            document_text,
            source_reliability,
            settings,
            client_id,
            document_id,
            session=session,
            dispatcher=dispatcher,
        )
        bucket = Bucket.POSITIVE if valence == "positive" else Bucket.IRRELEVANT

    status = bucket_to_status(bucket)

    # --- Stage 5: Idempotent upsert + atomic audit dispatch (FR-011) ---
    try:
        finding_id, created = await upsert_finding(
            session,
            client_id=client_id,
            document_id=document_id,
            drug=drug,
            reaction=reaction,
            bucket=bucket,
            resolution_path=resolution_path,
            model_confidence=model_confidence,
            classifier_version=classifier_version,
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
                classifier_version=classifier_version,
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
    except Exception as exc:
        log.error(
            "triage.operator_alert",
            stage="persist",
            reason=str(exc),
            client_id=client_id,
            document_id=document_id,
        )
        capture_operator_alert(
            "triage.operator_alert",
            stage="persist",
            client_id=client_id,
            document_id=document_id,
            error_class=type(exc).__name__,
        )
        raise  # trigger transaction rollback (no finding without its audit row)

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
