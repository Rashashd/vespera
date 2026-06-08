"""Ingestion domain enums (StrEnum + CHECK-mirrored String columns, spec-3 pattern)."""

from enum import StrEnum


class SourceName(StrEnum):
    """The seven configured literature/regulatory source identifiers."""

    PUBMED = "pubmed"
    EUROPEPMC = "europepmc"
    OPENFDA_FAERS = "openfda_faers"
    OPENFDA_LABEL = "openfda_label"
    FDA_MEDWATCH = "fda_medwatch"
    EMA = "ema"
    MHRA = "mhra"


class SourceReliability(StrEnum):
    """Ordered reliability tiers; higher rank = more authoritative (FR-005)."""

    REGULATORY_ALERT = "regulatory_alert"  # rank 3 — highest
    PEER_REVIEWED = "peer_reviewed"  # rank 2
    PREPRINT = "preprint"  # rank 1
    CASE_REPORT = "case_report"  # rank 0 — lowest

    @property
    def rank(self) -> int:
        return {"regulatory_alert": 3, "peer_reviewed": 2, "preprint": 1, "case_report": 0}[
            self.value
        ]


class IngestionRunStatus(StrEnum):
    """Lifecycle status of an ingestion run (FR-011, FR-024)."""

    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"


class SourceRunStatus(StrEnum):
    """Per-source outcome within a run."""

    SUCCESS = "success"
    FAILED = "failed"


class MeshValidity(StrEnum):
    """Save-time MeSH term validation result (FR-009)."""

    VALID = "valid"
    INVALID = "invalid"
    UNVALIDATED = "unvalidated"  # bundled artifact absent
