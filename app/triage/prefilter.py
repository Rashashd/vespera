"""Substantive-mention pre-filter: verifies watchlist drugs are not merely incidental (FR-001)."""

from __future__ import annotations

import asyncio

import structlog

from app.triage.ner import _get_nlp

_log = structlog.get_logger(__name__)


def _check_substantive_sync(text: str, matched_drugs: list[str]) -> list[tuple[str, bool, str]]:
    """Return (drug, is_substantive, reason) for each drug. CPU-bound — call via to_thread.

    Substantive = drug sentence is in the title portion OR co-occurs with a DISEASE in the
    same sentence. Incidental = bare CHEMICAL in a summary sentence with no DISEASE co-occurrence.
    """
    nlp = _get_nlp()
    doc = nlp(text)

    # text = f"{title}\n{summary}"; title ends at the first newline
    newline_pos = text.find("\n")
    title_boundary = newline_pos if newline_pos >= 0 else len(text)

    results: list[tuple[str, bool, str]] = []
    for drug in matched_drugs:
        drug_lower = drug.strip().lower()
        substantive = False
        reason = "incidental_no_disease"

        for sent in doc.sents:
            chem_match = any(
                e.label_ == "CHEMICAL" and e.text.strip().lower() == drug_lower for e in sent.ents
            )
            if not chem_match:
                continue

            # Sentence starts within the title portion
            if sent.start_char < title_boundary:
                substantive = True
                reason = "title_mention"
                break

            # Same-sentence DISEASE co-occurrence
            if any(e.label_ == "DISEASE" for e in sent.ents):
                substantive = True
                reason = "same_sentence_disease"
                break

        results.append((drug, substantive, reason))

    return results


async def filter_substantive_drugs(
    text: str,
    matched_drugs: list[str],
    *,
    client_id: int,
    document_id: int,
) -> list[str]:
    """Return the subset of matched_drugs that are substantively mentioned in text.

    Emits triage.prefilter.filtered for each incidentally-mentioned drug.
    """
    if not matched_drugs:
        return []

    log = _log.bind(client_id=client_id, document_id=document_id)
    results = await asyncio.to_thread(_check_substantive_sync, text, matched_drugs)

    substantive = []
    for drug, is_substantive, reason in results:
        if is_substantive:
            substantive.append(drug)
        else:
            log.info("triage.prefilter.filtered", drug=drug, reason=reason)

    return substantive
