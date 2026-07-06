"""Unit tests for triage LLM call internals: provider request shaping + valence success path.

Covers app/triage/llm.py's raw _call_llm HTTP bodies (OpenAI + Anthropic) and assess_valence's
success/parse paths, which the failsafe and egress-order tests never reach (they exercise guard
outages and the error fallback only). The httpx layer is stubbed so no real API call is made; the
best-effort usage-capture branch (needs a live AsyncSession) is covered in the integration suite.
"""

from __future__ import annotations

import types

import pytest

import app.triage.llm as triage_llm
from app.core.config import Settings

pytestmark = pytest.mark.asyncio


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:  # stub is always 200
        return None

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient: records the POST and returns a canned body."""

    calls: list[dict] = []

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url: str, **kwargs):
        type(self).calls.append({"url": url, **kwargs})
        return _FakeResponse(self._payload)


def _patch_httpx(monkeypatch, payload: dict) -> type[_FakeAsyncClient]:
    _FakeAsyncClient.calls = []
    monkeypatch.setattr(triage_llm.httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(payload))
    return _FakeAsyncClient


def _llm(provider: str):
    return types.SimpleNamespace(provider=provider, api_key="test-key", model="test-model")


async def test_call_llm_anthropic_shapes_request_and_reads_content(monkeypatch):
    payload = {
        "content": [{"text": '{"adverse": true}'}],
        "usage": {"input_tokens": 11, "output_tokens": 3},
    }
    client = _patch_httpx(monkeypatch, payload)
    out = await triage_llm._call_llm(_llm("anthropic"), "SYS", "USER", 64)
    assert out == '{"adverse": true}'
    call = client.calls[0]
    assert call["url"].endswith("/v1/messages")
    assert call["headers"]["x-api-key"] == "test-key"
    assert call["json"]["system"] == "SYS"


async def test_call_llm_openai_shapes_request_and_reads_content(monkeypatch):
    payload = {
        "choices": [{"message": {"content": '{"adverse": false}'}}],
        "usage": {"prompt_tokens": 9, "completion_tokens": 2},
    }
    client = _patch_httpx(monkeypatch, payload)
    out = await triage_llm._call_llm(_llm("openai"), "SYS", "USER", 64)
    assert out == '{"adverse": false}'
    call = client.calls[0]
    assert call["url"].endswith("/chat/completions")
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["json"]["response_format"] == {"type": "json_object"}


def _settings() -> Settings:
    s = Settings()
    s.guardrails_enabled = False  # guard is a no-op; we exercise the valence success path
    s.redaction_enabled = False
    return s


def _stub_valence(monkeypatch, reply: str) -> None:
    monkeypatch.setattr(triage_llm, "build_llm_client", lambda s: _llm("openai"))
    monkeypatch.setattr(
        triage_llm, "_load_prompt", lambda name: "SYS {source_reliability}\n<document>"
    )

    async def _reply(*a, **k):
        return reply

    monkeypatch.setattr(triage_llm, "_call_llm", _reply)


async def test_assess_valence_returns_parsed_positive(monkeypatch):
    _stub_valence(monkeypatch, '{"valence": "positive"}')
    assert await triage_llm.assess_valence("text", "peer_reviewed", _settings(), 1, 1) == "positive"


async def test_assess_valence_returns_parsed_irrelevant(monkeypatch):
    _stub_valence(monkeypatch, '{"valence": "irrelevant"}')
    result = await triage_llm.assess_valence("text", "peer_reviewed", _settings(), 1, 1)
    assert result == "irrelevant"


async def test_assess_valence_unexpected_value_falls_back_positive(monkeypatch):
    """An out-of-domain valence raises internally and hits the 'positive' fail-safe (FR-016)."""
    _stub_valence(monkeypatch, '{"valence": "banana"}')
    assert await triage_llm.assess_valence("text", "peer_reviewed", _settings(), 1, 1) == "positive"
