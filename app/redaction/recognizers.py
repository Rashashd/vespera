"""Custom Presidio recognizers for secrets + medical-record identifiers, plus a fast
regex scrubber for the logging path (no spaCy — log processors run on the event loop).
"""

from __future__ import annotations

import re

from presidio_analyzer import Pattern, PatternRecognizer

# --- Secret/key patterns (category SECRET). Anchored on key-like prefixes/shapes so ordinary
# identifiers are not redacted. (name, regex, score). ---
SECRET_PATTERNS: list[tuple[str, str, float]] = [
    ("openai_key", r"sk-(?:ant-)?[A-Za-z0-9_\-]{16,}", 0.9),
    ("aws_access_key", r"\bAKIA[0-9A-Z]{16}\b", 0.9),
    ("github_pat", r"\bghp_[A-Za-z0-9]{30,}\b", 0.9),
    ("jwt", r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b", 0.95),
    (
        "keyword_secret",
        r"(?i)(?:api[_-]?key|secret|token|password|passwd|bearer)"
        r"['\"\s:=]+([A-Za-z0-9_\-\.]{12,})",
        0.7,
    ),
]

# --- Medical-record / case-number patterns (category MEDICAL_RECORD). ---
MEDICAL_RECORD_PATTERNS: list[tuple[str, str, float]] = [
    ("mrn_prefixed", r"\bMRN[:#\-\s]*\d{5,}\b", 0.85),
    (
        "mrn_labelled",
        r"(?i)\b(?:medical\s+record|case)\s*(?:number|no\.?|#)?[:#\-\s]*\d{5,}\b",
        0.8,
    ),
]

# --- US SSN (category US_SSN) — custom recognizer for deterministic detection (Presidio's
# built-in is context-dependent and not reliably triggered without surrounding cues). ---
SSN_PATTERNS: list[tuple[str, str, float]] = [
    ("ssn_dashed", r"\b\d{3}-\d{2}-\d{4}\b", 0.6),
]


def secret_recognizer() -> PatternRecognizer:
    """PatternRecognizer for API keys/tokens (category SECRET)."""
    return PatternRecognizer(
        supported_entity="SECRET",
        patterns=[Pattern(name, regex, score) for name, regex, score in SECRET_PATTERNS],
    )


def medical_record_recognizer() -> PatternRecognizer:
    """PatternRecognizer for medical-record / case numbers (category MEDICAL_RECORD)."""
    return PatternRecognizer(
        supported_entity="MEDICAL_RECORD",
        patterns=[Pattern(name, regex, score) for name, regex, score in MEDICAL_RECORD_PATTERNS],
    )


def ssn_recognizer() -> PatternRecognizer:
    """PatternRecognizer for US SSNs (category US_SSN) — deterministic regex."""
    return PatternRecognizer(
        supported_entity="US_SSN",
        patterns=[Pattern(name, regex, score) for name, regex, score in SSN_PATTERNS],
    )


# --- Fast regex scrubber for logs/traces (no spaCy NER; safe to run synchronously). ---
# Catches secrets + structured identifiers; free-text names need the Presidio path (LLM egress).
_SSN = (r"\b\d{3}-\d{2}-\d{4}\b", "<US_SSN>")
_EMAIL = (r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", "<EMAIL_ADDRESS>")
_PHONE = (r"\b(?:\+?\d{1,2}[\s.\-]?)?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}\b", "<PHONE_NUMBER>")

_SCRUB_RULES: list[tuple[re.Pattern, str]] = (
    [(re.compile(rgx), "<SECRET>") for _n, rgx, _s in SECRET_PATTERNS]
    + [(re.compile(rgx), "<MEDICAL_RECORD>") for _n, rgx, _s in MEDICAL_RECORD_PATTERNS]
    + [
        (re.compile(_SSN[0]), _SSN[1]),
        (re.compile(_EMAIL[0]), _EMAIL[1]),
        (re.compile(_PHONE[0]), _PHONE[1]),
    ]
)


def scrub_text(text: str) -> str:
    """Fast, spaCy-free redaction of secrets + structured identifiers (for log/trace values)."""
    if not text:
        return text
    for pattern, placeholder in _SCRUB_RULES:
        text = pattern.sub(placeholder, text)
    return text
