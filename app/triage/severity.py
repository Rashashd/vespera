"""Severity bucketing: ICH keyword rule + regulatory-alert floor + custom keywords (FR-003/004)."""

from __future__ import annotations

from app.clients.enums import SeverityLevel
from app.triage.enums import Bucket
from app.triage.keywords.ich_seriousness import ICH_KEYWORDS

# Maps the string tier name from keyword dicts to SeverityLevel for rank comparison.
_TIER_TO_SEVERITY: dict[str, SeverityLevel] = {
    "serious": SeverityLevel.SERIOUS,
    "life-threatening": SeverityLevel.LIFE_THREATENING,
}

# Bucket assigned when a YES verdict has no ICH keyword match (mild adverse effect).
_DEFAULT_YES_BUCKET = Bucket.MINOR


def _ich_bucket(text: str) -> Bucket:
    """Return the highest-rank ICH bucket matching any keyword in text, or MINOR."""
    lower = text.lower()
    best: str = "minor"
    best_rank = -1
    for keyword, tier in ICH_KEYWORDS.items():
        if keyword in lower:
            rank = (
                SeverityLevel.LIFE_THREATENING.rank
                if tier == "emergency"
                else SeverityLevel.SERIOUS.rank
            )
            if rank > best_rank:
                best_rank = rank
                best = tier
    return Bucket(best) if best_rank >= 0 else _DEFAULT_YES_BUCKET


def _apply_regulatory_floor(bucket: Bucket, source_reliability: str) -> Bucket:
    """Regulatory-alert documents get at least URGENT (FR-003)."""
    if source_reliability == "regulatory_alert":
        if bucket in (Bucket.MINOR, Bucket.POSITIVE, Bucket.IRRELEVANT):
            return Bucket.URGENT
    return bucket


def _apply_custom_keywords(
    bucket: Bucket,
    text: str,
    custom_keywords: list[dict],
) -> Bucket:
    """Escalate-only via per-client custom keywords (FR-004); never downgrade.

    Each entry: {"keyword": str, "tier": "serious"|"life-threatening"}.
    """
    if not custom_keywords:
        return bucket
    lower = text.lower()
    best_rank = (
        SeverityLevel(_tier_to_bucket_name(bucket)).rank
        if bucket in (Bucket.URGENT, Bucket.EMERGENCY)
        else -1
    )
    for entry in custom_keywords:
        kw = entry.get("keyword", "").lower()
        tier = entry.get("tier", "")
        if kw and tier and kw in lower:
            sev = _TIER_TO_SEVERITY.get(tier)
            if sev and sev.rank > best_rank:
                best_rank = sev.rank
    if best_rank >= SeverityLevel.LIFE_THREATENING.rank:
        return Bucket.EMERGENCY
    if best_rank >= SeverityLevel.SERIOUS.rank:
        if bucket not in (Bucket.EMERGENCY,):
            return Bucket.URGENT
    return bucket


def _tier_to_bucket_name(bucket: Bucket) -> str:
    """Map bucket to SeverityLevel string for rank comparison."""
    mapping = {
        Bucket.EMERGENCY: "life-threatening",
        Bucket.URGENT: "serious",
        Bucket.MINOR: "non-serious",
        Bucket.POSITIVE: "non-serious",
        Bucket.IRRELEVANT: "non-serious",
    }
    return mapping[bucket]


def assign_bucket(
    *,
    verdict: bool,
    text: str,
    source_reliability: str,
    custom_keywords: list[dict] | None = None,
) -> Bucket:
    """Assign a severity bucket to an adverse-event verdict.

    YES verdict → ICH keyword match → regulatory floor → custom keyword escalation.
    NO verdict → IRRELEVANT (valence applied separately in service.py for YES=False cases).
    """
    if not verdict:
        return Bucket.IRRELEVANT

    bucket = _ich_bucket(text)
    bucket = _apply_regulatory_floor(bucket, source_reliability)
    if custom_keywords:
        bucket = _apply_custom_keywords(bucket, text, custom_keywords)
    return bucket
