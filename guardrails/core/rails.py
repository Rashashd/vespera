"""Deterministic, torch-free heuristic platform rails for the guardrails sidecar.

Four rails — prompt-injection, jailbreak, topic-scope, cross-client — evaluated by
regex/keyword matching only (no LLM, no torch, no network) so the CI red-team gate is
stable. The first blocking rail short-circuits. A rule-engine error fails safe to
``block`` with reason ``rail_engine_error`` (never raises out of the sidecar).
"""

from __future__ import annotations

import re

# --- Rail 1: prompt injection (input) / injection echo (output). ---
# Attempts to override the system prompt, exfiltrate instructions, or inject a new role.
_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|preceding|earlier)\s+"
        r"(instruction|prompt|message|context|rule)",
        r"disregard\s+(all\s+|the\s+)?(previous|prior|above|preceding|system|earlier)",
        r"forget\s+(everything|all\s+(previous|prior)|your\s+instruction)",
        r"(reveal|show|print|repeat|output|give\s+me|tell\s+me)\s+(your|the)\s+"
        r"(system\s+)?(prompt|instruction|rule|guideline)",
        r"you\s+are\s+now\s+(a|an|the)\b",
        r"new\s+(instruction|rule|system\s+prompt|task)s?\s*:",
        r"override\s+(your|the|all)\s+(instruction|rule|setting|safety|config)",
        r"<\|?im_(start|end)\|?>",  # chat-template injection token
        r"(^|\n)\s*#{1,6}\s*system\b",  # markdown 'system' role header injection
        r"\[/?(system|inst|assistant)\]",  # bracketed role tokens
        r"\bact\s+as\s+(a\s+|an\s+)?(developer|root|admin|system|dba)\b",
    )
]

# --- Rail 2: jailbreak (input only). ---
_JAILBREAK_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bdo\s+anything\s+now\b",
        r"\bdeveloper\s+mode\b",
        r"\bjailbreak",
        r"(ignore|bypass|disable|turn\s+off|remove)\s+(your\s+)?"
        r"(safety|guideline|guardrail|restriction|filter|limitation)",
        r"pretend\s+(you\s+(are|have)|to\s+be)\b.{0,40}\b"
        r"(no\s+(rule|restriction|limit)|unrestricted|uncensored)",
        r"(with\s+no|without\s+any)\s+(rule|restriction|limit|filter|censorship|guardrail)",
        r"roleplay\s+as\s+.{0,40}\b(unrestricted|uncensored|evil|rogue)",
        r"\bDAN\b",  # the 'DAN' jailbreak persona (case-sensitive token)
    )
]
# DAN is matched case-sensitively to avoid catching ordinary words; build it separately.
_JAILBREAK_DAN = re.compile(r"\bDAN\b")

# --- Rail 3: topic scope. ---
# Pantera is a pharmacovigilance assistant. Block explicit off-domain TASK requests
# (imperative "write a poem / give me a recipe / translate ..."); clinical narrative is
# declarative and never trips these, keeping false-refusal at zero.
_TOPIC_OFFSCOPE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bwrite\s+(me\s+)?(a\s+|an\s+|some\s+)?"
        r"(poem|song|story|joke|essay|haiku|rap|script|novel|limerick)\b",
        r"\btell\s+me\s+a\s+joke\b",
        r"\b(give\s+me|share|suggest)\s+(a\s+)?(recipe|cocktail)\b",
        r"\bhow\s+(do\s+i|to)\s+(cook|bake|brew)\b",
        r"\bwhat('?s| is)\s+the\s+weather\b",
        r"\b(stock|share)\s+price\b",
        r"\btranslate\b.{0,30}\b(into|to)\s+"
        r"(french|spanish|german|chinese|italian|japanese|arabic|russian)\b",
        r"\bwrite\s+(me\s+)?(a\s+|an\s+|some\s+)?"
        r"(python|java|javascript|c\+\+|rust|go|sql|html)\b",
        r"\bwrite\s+(me\s+)?(a\s+)?(program|function|script|app|website)\b",
        r"\bwho\s+(won|will\s+win)\b.{0,30}\b(election|game|match|cup)\b",
    )
]

# --- Rail 4: cross-client. ---
# Attempts to reference another tenant's data. "all/other/another client" always blocks;
# an explicit "client N" only blocks when N differs from the acting client_id.
_CROSS_CLIENT_GENERIC = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(all|other|another|different|every|each)\s+(client|tenant|customer|account)s?\b",
        r"\bcross[\s-]?(client|tenant)\b",
        r"\b(other|another)\s+(compan(y|ies)|customer|organization)('s|s)?\s+"
        r"(data|finding|report|document|patient)",
        r"\b(every|all)\s+(compan(y|ies)|customer|organization)('s|s)?\s+(data|finding|report)",
    )
]
_CLIENT_REF = re.compile(
    r"\b(?:client|tenant|customer|account)[\s_#:=-]*(?:id[\s_#:=-]*)?(\d+)\b",
    re.IGNORECASE,
)


class RailError(Exception):
    """Raised internally if a rail evaluation fails; the engine converts it to fail-safe block."""


def _check_injection(text: str) -> str | None:
    for pat in _INJECTION_PATTERNS:
        if pat.search(text):
            return "prompt_injection_detected"
    return None


def _check_jailbreak(text: str) -> str | None:
    if _JAILBREAK_DAN.search(text):
        return "jailbreak_detected"
    for pat in _JAILBREAK_PATTERNS:
        if pat is _JAILBREAK_DAN:
            continue
        if pat.search(text):
            return "jailbreak_detected"
    return None


def _check_topic_scope(text: str) -> str | None:
    for pat in _TOPIC_OFFSCOPE_PATTERNS:
        if pat.search(text):
            return "off_topic_request"
    return None


def _check_cross_client(text: str, client_id: int) -> str | None:
    for pat in _CROSS_CLIENT_GENERIC:
        if pat.search(text):
            return "cross_client_reference"
    for match in _CLIENT_REF.finditer(text):
        referenced = int(match.group(1))
        if referenced != client_id:
            return "cross_client_reference"
    return None


# Rails applied per direction (contract): input → all four; output → injection-echo +
# topic_scope + cross_client (jailbreak is input-only).
_RAILS_FOR_DIRECTION: dict[str, tuple[str, ...]] = {
    "input": ("injection", "jailbreak", "topic_scope", "cross_client"),
    "output": ("injection", "topic_scope", "cross_client"),
}


def evaluate(text: str, direction: str, client_id: int) -> dict:
    """Evaluate one payload; return a dict with action/rail/reason/checked (never raises).

    Deterministic: the same input always yields the same result. The first blocking rail
    short-circuits. Any internal error fails safe to ``block`` with ``rail_engine_error``.
    """
    checked = list(_RAILS_FOR_DIRECTION.get(direction, _RAILS_FOR_DIRECTION["input"]))
    try:
        for rail in checked:
            if rail == "injection":
                reason = _check_injection(text)
            elif rail == "jailbreak":
                reason = _check_jailbreak(text)
            elif rail == "topic_scope":
                reason = _check_topic_scope(text)
            elif rail == "cross_client":
                reason = _check_cross_client(text, client_id)
            else:  # pragma: no cover - guarded by _RAILS_FOR_DIRECTION
                reason = None
            if reason:
                return {"action": "block", "rail": rail, "reason": reason, "checked": checked}
        return {"action": "allow", "rail": None, "reason": None, "checked": checked}
    except Exception:  # noqa: BLE001 - fail safe inside the sidecar (contract: never 5xx)
        return {"action": "block", "rail": None, "reason": "rail_engine_error", "checked": checked}
