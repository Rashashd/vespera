"""Unit tests for the pure budget-state derivation (warn at 80%, soft-cap at 100%)."""

from decimal import Decimal

import pytest

from app.clients.service import derive_budget_state


def test_null_budget_is_always_ok():
    """No cap set ⇒ status is always ok regardless of spend (D4)."""
    assert derive_budget_state(None, Decimal("999")) == "ok"


@pytest.mark.parametrize(
    "spend,expected",
    [
        (Decimal("0"), "ok"),
        (Decimal("79.99"), "ok"),
        (Decimal("80"), "warning"),  # exact 80% boundary warns
        (Decimal("99.99"), "warning"),
        (Decimal("100"), "soft_capped"),  # exact 100% boundary caps
        (Decimal("150"), "soft_capped"),
    ],
)
def test_boundaries_for_budget_100(spend, expected):
    """With budget=100: <80 ok, [80,100) warning, ≥100 soft_capped."""
    assert derive_budget_state(Decimal("100"), spend) == expected
