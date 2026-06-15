"""Token → USD cost computation for tracked LLM call sites (FR-033)."""

from __future__ import annotations

from decimal import Decimal

import structlog

from app.core.config import Settings

_log = structlog.get_logger(__name__)


def compute_cost(model: str, in_tok: int, out_tok: int, settings: Settings) -> Decimal:
    """Return USD cost as Decimal; unknown model → 0 + warning (never raises)."""
    price_in = settings.llm_price_per_1k_input_usd.get(model)
    price_out = settings.llm_price_per_1k_output_usd.get(model)
    if price_in is None or price_out is None:
        _log.warning("observability.pricing.unknown_model", model=model)
        return Decimal("0")
    cost = Decimal(str(in_tok)) / 1000 * Decimal(str(price_in)) + Decimal(
        str(out_tok)
    ) / 1000 * Decimal(str(price_out))
    return cost.quantize(Decimal("0.000001"))
