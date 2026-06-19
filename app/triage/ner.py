"""scispaCy BC5CDR NER: extracts drug (CHEMICAL) and reaction (DISEASE) entities."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

import structlog

_log = structlog.get_logger(__name__)

_UNSPECIFIED = "unspecified"


class NerUnavailable(RuntimeError):
    """The BC5CDR NER model could not load or run.

    Raised so triage marks the document degraded and surfaces the failure, rather than
    mistaking a model outage for 'no entities found' and silently dropping the document with
    zero findings (Constitution III — triage fails safe, it never suppresses).
    """


@lru_cache(maxsize=1)
def _get_nlp() -> Any:
    """Load the BC5CDR model once; cached at module/process level (heavy resource)."""
    import spacy

    return spacy.load("en_ner_bc5cdr_md")


def _extract_sync(text: str) -> tuple[list[str], list[str]]:
    """CPU-bound NER extraction; call via asyncio.to_thread in async contexts."""
    nlp = _get_nlp()
    doc = nlp(text)
    chemicals = [e.text.strip().lower() for e in doc.ents if e.label_ == "CHEMICAL"]
    diseases = [e.text.strip().lower() for e in doc.ents if e.label_ == "DISEASE"]
    return chemicals, diseases


async def extract_entities(text: str) -> tuple[list[str], list[str]]:
    """Return (drug_entities, reaction_entities) extracted from text via BC5CDR NER.

    Drugs map to CHEMICAL labels; reactions map to DISEASE labels.
    Both are normalized (strip + lower) for matching and the finding key.

    Raises NerUnavailable when the model cannot load or run — a model outage MUST be a loud,
    typed signal, never a silent ([], []) result that looks identical to 'no entities found'.
    """
    try:
        return await asyncio.to_thread(_extract_sync, text)
    except Exception as exc:  # spacy.load / model exec failure → fail safe, do not return empty
        raise NerUnavailable(str(exc)) from exc


def reaction_or_sentinel(reactions: list[str]) -> str:
    """Return the first reaction entity, or the 'unspecified' sentinel when none found."""
    return reactions[0] if reactions else _UNSPECIFIED
