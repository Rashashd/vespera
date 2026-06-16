"""In-process Presidio redaction: redact(text) -> RedactionResult.

Process-singleton analyzer/anonymizer (lru_cache, mirrors app/triage/ner.py:_get_nlp). Uses
en_core_web_sm for PII NER (torch-free — NOT scispaCy) plus custom secret/medical-record
recognizers. Egress-only: callers redact before any external-LLM call, log, trace, or derived
summary; the persisted report body/findings/chunks are never redacted. Offload analyze() with
asyncio.to_thread from async paths (analyze is CPU-bound).
"""

from __future__ import annotations

import asyncio
from collections import Counter
from functools import lru_cache
from typing import Any

from app.redaction.models import RedactedEntity, RedactionResult
from app.redaction.recognizers import (
    medical_record_recognizer,
    secret_recognizer,
    ssn_recognizer,
)

# PII entities Presidio is asked to find (built-ins + our custom SECRET/MEDICAL_RECORD).
_ENTITIES = [
    "PERSON",
    "DATE_TIME",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "LOCATION",
    "US_SSN",
    "CREDIT_CARD",
    "IP_ADDRESS",
    "MEDICAL_RECORD",
    "SECRET",
]


@lru_cache(maxsize=1)
def _get_analyzer() -> Any:
    """Build the singleton Presidio analyzer with en_core_web_sm + custom recognizers."""
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    provider = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        }
    )
    analyzer = AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en"])
    analyzer.registry.add_recognizer(secret_recognizer())
    analyzer.registry.add_recognizer(medical_record_recognizer())
    analyzer.registry.add_recognizer(ssn_recognizer())
    return analyzer


@lru_cache(maxsize=1)
def _get_anonymizer() -> Any:
    """Build the singleton Presidio anonymizer (default replace → <ENTITY_TYPE>)."""
    from presidio_anonymizer import AnonymizerEngine

    return AnonymizerEngine()


def redact(text: str) -> RedactionResult:
    """Redact PII + secrets from text; return redacted text + (category, count) entities only.

    Never stores or logs the original values. Empty/whitespace input is returned unchanged.
    Synchronous + CPU-bound (spaCy) — call via asyncio.to_thread from async code.
    """
    if not text or not text.strip():
        return RedactionResult(text=text, entities=[])

    analyzer = _get_analyzer()
    results = analyzer.analyze(text=text, language="en", entities=_ENTITIES)
    if not results:
        return RedactionResult(text=text, entities=[])

    anonymized = _get_anonymizer().anonymize(text=text, analyzer_results=results)
    counts = Counter(r.entity_type for r in results)
    entities = [RedactedEntity(type=etype, count=count) for etype, count in sorted(counts.items())]
    return RedactionResult(text=anonymized.text, entities=entities)


async def redact_async(settings: Any, text: str) -> str:
    """Redact at an egress point, honoring the test-only kill-switch; offloads analyze().

    No-op (returns text unchanged) only when settings.redaction_enabled is False, which
    production refuses to boot with (startup.check_security_boundary). Used before every
    external-LLM call / derived summary so PII never leaves the trust boundary (FR-012).
    """
    if not getattr(settings, "redaction_enabled", True):
        return text
    result = await asyncio.to_thread(redact, text)
    return result.text
