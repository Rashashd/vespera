"""Unit tests for redact() (Presidio) + scrub_text() (fast regex) + custom recognizers."""

from __future__ import annotations

import pytest

from app.redaction import redact, scrub_text


def test_redacts_person_mrn_and_secret():
    out = redact(
        "Patient John Smith MRN: 00123456 prescribed atorvastatin; key sk-ant-ABCDEF0123456789."
    )
    assert "John Smith" not in out.text
    assert "00123456" not in out.text
    assert "sk-ant-ABCDEF0123456789" not in out.text
    types = {e.type for e in out.entities}
    assert {"PERSON", "MEDICAL_RECORD", "SECRET"} <= types


def test_redacts_email_phone_ssn():
    out = redact("Reach jane.doe@example.com or 555-123-4567; SSN 123-45-6789.")
    assert "jane.doe@example.com" not in out.text
    assert "123-45-6789" not in out.text
    types = {e.type for e in out.entities}
    assert {"EMAIL_ADDRESS", "US_SSN"} <= types


def test_preserves_clinical_signal():
    """Drug + AE terms must survive redaction (FR-011)."""
    text = "Severe hepatotoxicity and thrombocytopenia after ondansetron and atorvastatin."
    out = redact(text)
    for term in ("hepatotoxicity", "thrombocytopenia", "ondansetron", "atorvastatin"):
        assert term in out.text
    assert out.entities == []


def test_entities_carry_no_values():
    out = redact("Contact John Smith at john@example.com.")
    for ent in out.entities:
        assert isinstance(ent.type, str) and isinstance(ent.count, int)
        # the model only has type + count fields — no place for the original value
        assert set(ent.model_dump().keys()) == {"type", "count"}


def test_empty_and_whitespace_unchanged():
    assert redact("").text == ""
    assert redact("   ").text == "   "
    assert redact("   ").entities == []


def test_scrub_text_catches_secret_ssn_mrn():
    out = scrub_text("token sk-ant-ABCDEF0123456789 MRN: 0099887 ssn 123-45-6789 me@x.com")
    assert "sk-ant-ABCDEF0123456789" not in out
    assert "0099887" not in out
    assert "123-45-6789" not in out
    assert "me@x.com" not in out


def test_scrub_text_preserves_clinical():
    text = "anaphylaxis after vaccine dose two"
    assert scrub_text(text) == text


@pytest.mark.asyncio
async def test_redact_async_respects_kill_switch():
    from app.core.config import Settings
    from app.redaction import redact_async

    s = Settings()
    s.redaction_enabled = False
    text = "John Smith SSN 123-45-6789"
    assert await redact_async(s, text) == text  # disabled → unchanged (test-only)
    s.redaction_enabled = True
    assert "123-45-6789" not in await redact_async(s, text)
