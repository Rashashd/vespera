"""Unit tests for scheduling budget gate (spec 11 T027, FR-019a/b/c, Constitution III)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scheduling.budget_policy import gate


def _make_watchlist(policy: str = "continue", budget: Decimal | None = Decimal("100")) -> MagicMock:
    wl = MagicMock()
    wl.budget_exceeded_policy = policy
    wl.budget_amount = budget
    return wl


def _make_session(watchlist: MagicMock | None) -> AsyncMock:
    session = AsyncMock()
    session.get = AsyncMock(return_value=watchlist)
    return session


def _make_dispatcher() -> AsyncMock:
    dispatcher = AsyncMock()
    dispatcher.dispatch = AsyncMock()
    return dispatcher


# ── No watchlist (defensive default) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_no_watchlist_returns_continue():
    session = _make_session(None)
    dispatcher = _make_dispatcher()
    result = await gate(session, watchlist_id=99, client_id=1, dispatcher=dispatcher)
    assert result == "continue"
    dispatcher.dispatch.assert_not_called()


# ── Budget OK → always continue, no event ────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_ok_budget_continue_policy():
    session = _make_session(_make_watchlist(policy="continue"))
    dispatcher = _make_dispatcher()
    with patch(
        "app.clients.watchlists.read_figures",
        new=AsyncMock(return_value=("ok", Decimal("10"))),
    ):
        result = await gate(session, watchlist_id=1, client_id=1, dispatcher=dispatcher)
    assert result == "continue"
    dispatcher.dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_gate_ok_budget_pause_policy_still_continue():
    """Policy is only applied when budget is soft_capped — ok budget ignores policy."""
    session = _make_session(_make_watchlist(policy="pause"))
    dispatcher = _make_dispatcher()
    with patch(
        "app.clients.watchlists.read_figures",
        new=AsyncMock(return_value=("ok", Decimal("10"))),
    ):
        result = await gate(session, watchlist_id=1, client_id=1, dispatcher=dispatcher)
    assert result == "continue"
    dispatcher.dispatch.assert_not_called()


# ── Warning → dispatches event, still continue ───────────────────────────────


@pytest.mark.asyncio
async def test_gate_warning_dispatches_event_returns_continue():
    session = _make_session(_make_watchlist(policy="continue"))
    dispatcher = _make_dispatcher()
    with patch(
        "app.clients.watchlists.read_figures",
        new=AsyncMock(return_value=("warning", Decimal("82"))),
    ):
        result = await gate(session, watchlist_id=1, client_id=1, dispatcher=dispatcher)
    assert result == "continue"
    dispatcher.dispatch.assert_awaited_once()
    event = dispatcher.dispatch.call_args[0][0]
    assert event.state == "warning"
    assert event.client_id == 1
    assert event.watchlist_id == 1


@pytest.mark.asyncio
async def test_gate_warning_with_pause_policy_still_continue():
    """Warning threshold does NOT apply the policy — only soft_capped does."""
    session = _make_session(_make_watchlist(policy="pause"))
    dispatcher = _make_dispatcher()
    with patch(
        "app.clients.watchlists.read_figures",
        new=AsyncMock(return_value=("warning", Decimal("82"))),
    ):
        result = await gate(session, watchlist_id=1, client_id=1, dispatcher=dispatcher)
    assert result == "continue"
    dispatcher.dispatch.assert_awaited_once()


# ── Soft-capped → returns policy, dispatches event ───────────────────────────


@pytest.mark.asyncio
async def test_gate_soft_capped_continue_policy():
    session = _make_session(_make_watchlist(policy="continue"))
    dispatcher = _make_dispatcher()
    with patch(
        "app.clients.watchlists.read_figures",
        new=AsyncMock(return_value=("soft_capped", Decimal("100"))),
    ):
        result = await gate(session, watchlist_id=1, client_id=1, dispatcher=dispatcher)
    assert result == "continue"
    dispatcher.dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_gate_soft_capped_critical_only_policy():
    session = _make_session(_make_watchlist(policy="critical_only"))
    dispatcher = _make_dispatcher()
    with patch(
        "app.clients.watchlists.read_figures",
        new=AsyncMock(return_value=("soft_capped", Decimal("120"))),
    ):
        result = await gate(session, watchlist_id=1, client_id=1, dispatcher=dispatcher)
    assert result == "critical_only"
    dispatcher.dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_gate_soft_capped_pause_policy():
    session = _make_session(_make_watchlist(policy="pause"))
    dispatcher = _make_dispatcher()
    with patch(
        "app.clients.watchlists.read_figures",
        new=AsyncMock(return_value=("soft_capped", Decimal("200"))),
    ):
        result = await gate(session, watchlist_id=1, client_id=1, dispatcher=dispatcher)
    assert result == "pause"
    dispatcher.dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_gate_soft_capped_dispatches_event_with_correct_state():
    session = _make_session(_make_watchlist(policy="pause"))
    dispatcher = _make_dispatcher()
    with patch(
        "app.clients.watchlists.read_figures",
        new=AsyncMock(return_value=("soft_capped", Decimal("200"))),
    ):
        await gate(session, watchlist_id=5, client_id=3, dispatcher=dispatcher)
    event = dispatcher.dispatch.call_args[0][0]
    assert event.state == "soft_capped"
    assert event.watchlist_id == 5
    assert event.client_id == 3
    assert event.actor_id == 0
    assert event.actor_type == "system"


# ── Constitution III: gate() is only called for drafting stages ───────────────


def test_gate_signature_is_async():
    """gate() MUST be async — callers must await it; sync call at a drafting site is a bug."""
    import inspect

    assert inspect.iscoroutinefunction(gate)


@pytest.mark.asyncio
async def test_gate_null_budget_returns_continue():
    """Watchlist with no budget cap is always continue regardless of spend."""
    session = _make_session(_make_watchlist(policy="pause", budget=None))
    dispatcher = _make_dispatcher()
    with patch(
        "app.clients.watchlists.read_figures",
        new=AsyncMock(return_value=("ok", Decimal("0"))),
    ):
        result = await gate(session, watchlist_id=1, client_id=1, dispatcher=dispatcher)
    assert result == "continue"
    dispatcher.dispatch.assert_not_called()
