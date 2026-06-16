"""Unit tests for the guardrails HTTP client: parse responses, fail-safe on errors."""

from __future__ import annotations

import httpx
import pytest

from app.guardrails.client import GuardrailsClient, GuardrailsUnavailable

pytestmark = pytest.mark.asyncio


def _client(handler) -> GuardrailsClient:
    return GuardrailsClient(
        base_url="http://guardrails:8002",
        token="tok",
        transport=httpx.MockTransport(handler),
    )


async def test_guard_parses_allow():
    def handler(request):
        assert request.headers["X-Service-Token"] == "tok"
        return httpx.Response(200, json={"action": "allow", "rail": None, "checked": []})

    async with _client(handler) as gc:
        resp = await gc.guard("hi", "input", 1, "triage")
    assert resp.action == "allow"


async def test_guard_parses_block():
    def handler(request):
        return httpx.Response(
            200,
            json={"action": "block", "rail": "injection", "reason": "x", "checked": ["injection"]},
        )

    async with _client(handler) as gc:
        resp = await gc.guard("bad", "input", 1, "triage")
    assert resp.action == "block"
    assert resp.rail == "injection"


async def test_guard_raises_unavailable_on_4xx():
    def handler(request):
        return httpx.Response(401, json={"detail": "bad token"})

    async with _client(handler) as gc:
        with pytest.raises(GuardrailsUnavailable):
            await gc.guard("hi", "input", 1, "triage")


async def test_guard_raises_unavailable_on_connect_error():
    def handler(request):
        raise httpx.ConnectError("refused")

    async with _client(handler) as gc:
        with pytest.raises(GuardrailsUnavailable):
            await gc.guard("hi", "input", 1, "triage")
