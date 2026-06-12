"""StrEnums for the triage domain — mirrored by CHECK constraints in migration 0007."""

from enum import StrEnum


class Bucket(StrEnum):
    """Severity bucket assigned to a finding; drives queue routing."""

    IRRELEVANT = "irrelevant"
    POSITIVE = "positive"
    MINOR = "minor"
    URGENT = "urgent"
    EMERGENCY = "emergency"


class FindingStatus(StrEnum):
    """Queue routing status; bucket→status invariant enforced in routing.py."""

    PENDING_EXPEDITED = "pending_expedited"
    PENDING_BATCH = "pending_batch"
    CLASSIFIED = "classified"


class ResolutionPath(StrEnum):
    """How the YES/NO adverse-event verdict was resolved (FR-002)."""

    MODEL = "model"
    LLM = "llm"
    ESCALATED = "escalated"
