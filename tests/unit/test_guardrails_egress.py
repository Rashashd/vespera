"""Unit tests for guard_text: fail-safe raising + atomic audit emission + kill-switch."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain.events import GuardrailRefused, GuardrailUnavailable
from app.guardrails import egress
from app.guardrails.client import GuardrailsUnavailable
from app.guardrails.egress import GuardBlocked, guard_text
from app.guardrails.schemas import GuardResponse

pytestmark = pytest.mark.asyncio


class _FakeDispatcher:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def dispatch(self, event, session) -> None:
        self.events.append(event)


class _FakeClient:
    """Stands in for GuardrailsClient; behaviour controlled by `result` or `raises`."""

    def __init__(self, *, result=None, raises=None) -> None:
        self._result = result
        self._raises = raises

    @classmethod
    def make(cls, **kw):
        inst = cls(**kw)

        def _from_settings(_settings):
            return inst

        return _from_settings

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def guard(self, text, direction, client_id, call_site) -> GuardResponse:
        if self._raises is not None:
            raise self._raises
        return self._result


def _settings(enabled=True) -> Settings:
    s = Settings()
    s.guardrails_enabled = enabled
    return s


async def test_allow_is_noop(monkeypatch):
    allow = GuardResponse(action="allow", checked=[])
    monkeypatch.setattr(egress.GuardrailsClient, "from_settings", _FakeClient.make(result=allow))
    disp = _FakeDispatcher()
    await guard_text(
        _settings(),
        text="ok",
        direction="input",
        client_id=1,
        call_site="triage",
        session=AsyncSession(),
        dispatcher=disp,
    )
    assert disp.events == []


async def test_block_raises_and_emits_refused(monkeypatch):
    block = GuardResponse(action="block", rail="injection", checked=["injection"])
    monkeypatch.setattr(egress.GuardrailsClient, "from_settings", _FakeClient.make(result=block))
    disp = _FakeDispatcher()
    with pytest.raises(GuardBlocked):
        await guard_text(
            _settings(),
            text="bad",
            direction="input",
            client_id=7,
            call_site="triage",
            session=AsyncSession(),
            dispatcher=disp,
        )
    assert len(disp.events) == 1
    ev = disp.events[0]
    assert isinstance(ev, GuardrailRefused)
    assert ev.rail == "injection" and ev.client_id == 7 and ev.call_site == "triage"


async def test_unavailable_raises_and_emits(monkeypatch):
    monkeypatch.setattr(
        egress.GuardrailsClient,
        "from_settings",
        _FakeClient.make(raises=GuardrailsUnavailable("down")),
    )
    disp = _FakeDispatcher()
    with pytest.raises(GuardrailsUnavailable):
        await guard_text(
            _settings(),
            text="x",
            direction="input",
            client_id=3,
            call_site="intake",
            session=AsyncSession(),
            dispatcher=disp,
        )
    assert len(disp.events) == 1
    ev = disp.events[0]
    assert isinstance(ev, GuardrailUnavailable)
    assert ev.call_site == "intake" and ev.fail_action == "quarantine"


async def test_disabled_is_noop(monkeypatch):
    def _boom(_s):
        raise AssertionError("client must not be constructed when disabled")

    monkeypatch.setattr(egress.GuardrailsClient, "from_settings", _boom)
    # Should not raise and not touch the client.
    await guard_text(
        _settings(enabled=False),
        text="anything",
        direction="input",
        client_id=1,
        call_site="triage",
    )
