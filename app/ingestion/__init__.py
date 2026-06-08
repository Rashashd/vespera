"""Ingestion package: literature and regulatory record ingestion (spec 4)."""

# Importing adapter modules here triggers their self-registration in ENABLED_ADAPTERS
# (each module appends its adapter at import time, spec-3 registry pattern).
from app.ingestion.adapters import (  # noqa: F401  # EMA/MHRA sequenced last (schedule-risk)  # noqa: F401
    ema,
    europepmc,
    fda_medwatch,
    mhra,
    openfda,
    pubmed,
)
