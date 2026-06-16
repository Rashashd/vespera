"""US5/SC-001/SC-008: egress order (redact → guard → call) + guarded-path inventory.

Confirms the triage path applies redaction before the guardrails check before the external LLM
call (closes spec-8 deviation a), and inventories the four guarded egress sites (triage
resolution, triage valence, drafting agent, document intake) each routing through guard().
"""

from __future__ import annotations

import inspect

import pytest

import app.agent.graph as agent_graph
import app.ingestion.runner as ingestion_runner
import app.triage.llm as triage_llm
from app.core.config import Settings

pytestmark = pytest.mark.asyncio


async def test_triage_resolve_order_redact_guard_call(monkeypatch):
    """resolve_yes_no order must be redact → guard(input) → call → guard(output) (FR-012)."""
    calls: list[str] = []

    async def fake_redact(settings, text):
        calls.append("redact")
        return text

    async def fake_guard(settings, *, text, direction, **kwargs):
        calls.append(f"guard:{direction}")

    async def fake_call(*args, **kwargs):
        calls.append("call")
        return '{"adverse": true}'

    monkeypatch.setattr(triage_llm, "redact_async", fake_redact)
    monkeypatch.setattr(triage_llm, "guard_text", fake_guard)
    monkeypatch.setattr(triage_llm, "_call_llm", fake_call)
    monkeypatch.setattr(triage_llm, "build_llm_client", lambda s: object())
    monkeypatch.setattr(triage_llm, "_load_prompt", lambda name: "SYSTEM PROMPT\n<document>")

    result = await triage_llm.resolve_yes_no("patient text", "peer_reviewed", Settings(), 1, 1)

    assert result is True
    assert calls == ["redact", "guard:input", "call", "guard:output"]


def test_guarded_path_inventory():
    """All four external-LLM/intake egress sites route through the guardrails boundary."""
    triage_src = inspect.getsource(triage_llm)
    agent_src = inspect.getsource(agent_graph)
    intake_src = inspect.getsource(ingestion_runner)

    # Triage: both resolve_yes_no and assess_valence guard with call_site="triage".
    assert triage_src.count('call_site="triage"') >= 2
    # Drafting agent egress.
    assert 'call_site="agent"' in agent_src
    # Document intake egress.
    assert 'call_site="intake"' in intake_src
    # Redaction precedes the guard at the triage egress (deviation a closure).
    assert "redact_async" in triage_src and "redact_async" in agent_src
