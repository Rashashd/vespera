"""Execution tests for the bounded drafting graph (app/agent/graph.py).

The audit found graph.py effectively unexercised: the "tool-selection" eval is a rule-based
oracle (no graph) and report-runner mocks run_agent. This drives the REAL compiled StateGraph
end to end through run_agent, with a fake chat model (canned tool calls) + fake tools + mocked
guard/usage, exercising every branch: normal draft, followup, unknown tool, tool
escalation/retryable/unexpected errors, iteration and token caps, guard block/outage, a fatal
graph error, the no-draft fall-through, and the redraft entry path.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

import app.agent.graph as graph_mod
from app.agent.tools import EscalationSignal, ToolError
from app.core.config import Settings
from app.guardrails.client import GuardrailsUnavailable
from app.guardrails.egress import GuardBlocked

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- fakes


class _FakeChatModel:
    """Returns canned responses in order (repeating the last); raises if a response is an
    Exception. bind_tools is a no-op passthrough."""

    def __init__(self, responses: list) -> None:
        self._responses = responses
        self._i = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        response = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        if isinstance(response, Exception):
            raise response
        return response


class _FakeTool:
    def __init__(self, name: str, result=None, raises: Exception | None = None) -> None:
        self.name = name
        self._result = result
        self._raises = raises

    async def ainvoke(self, args):
        if self._raises is not None:
            raise self._raises
        return self._result


def _ai_tool(name: str, args: dict | None = None, call_id: str = "c1", total_tokens: int = 0):
    """An AIMessage carrying one tool call (and optional usage for the token-cap path)."""
    usage = None
    if total_tokens:
        usage = {"input_tokens": 1, "output_tokens": 1, "total_tokens": total_tokens}
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args or {}, "id": call_id, "type": "tool_call"}],
        usage_metadata=usage,
    )


def _ai_done(content: str = "no more tools"):
    return AIMessage(content=content)


def _settings(**over) -> Settings:
    s = Settings()
    s.guardrails_enabled = False  # real guard_text is a no-op unless a test patches it
    s.redaction_enabled = False
    s.agent_max_iterations = over.pop("max_iter", 8)
    s.agent_max_tokens = over.pop("max_tokens", 1_000_000)
    for key, value in over.items():
        setattr(s, key, value)
    return s


_FINDING = SimpleNamespace(id=1, drug="Warfarin", reaction="bleeding", bucket="urgent")
_CLIENT = SimpleNamespace(id=10)


async def _run(
    monkeypatch,
    *,
    responses: list,
    tools: list,
    settings: Settings,
    record_usage=None,
    **run_kwargs,
):
    """Wire the fakes and drive run_agent to completion."""
    monkeypatch.setattr(
        "app.agent.llm_binding.build_agent_chat_model", lambda s: _FakeChatModel(responses)
    )
    monkeypatch.setattr(graph_mod, "make_tools", lambda *a, **k: tools)
    monkeypatch.setattr("app.observability.usage.record_usage", record_usage or AsyncMock())
    return await graph_mod.run_agent(
        finding=_FINDING,
        client=_CLIENT,
        session=AsyncMock(),
        redis=AsyncMock(),
        ms_client=AsyncMock(),
        app_state=SimpleNamespace(dispatcher=None),
        settings=settings,
        **run_kwargs,
    )


# --------------------------------------------------------------------------- tests


async def test_happy_draft_path_returns_draft_result(monkeypatch):
    """draft_report tool call → draft_result populated, not escalated."""
    tools = [_FakeTool("draft_report", result='{"draft_body": "Report text", "claims": []}')]
    result = await _run(
        monkeypatch,
        responses=[_ai_tool("draft_report"), _ai_done()],
        tools=tools,
        settings=_settings(),
    )
    assert result["escalated"] is False
    assert result["draft_result"] == {"draft_body": "Report text", "claims": []}


async def test_draft_followup_populates_followup_result(monkeypatch):
    tools = [
        _FakeTool("draft_followup", result='{"cover_message": "Urgent", "template_ref": "t1"}')
    ]
    result = await _run(
        monkeypatch,
        responses=[_ai_tool("draft_followup"), _ai_done()],
        tools=tools,
        settings=_settings(),
    )
    assert result["followup_result"] == {"cover_message": "Urgent", "template_ref": "t1"}


async def test_unknown_tool_falls_through_to_no_draft(monkeypatch):
    """A tool call for a name not in the tool map → unknown_tool message, then no draft."""
    result = await _run(
        monkeypatch,
        responses=[_ai_tool("does_not_exist"), _ai_done()],
        tools=[_FakeTool("draft_report", result="{}")],
        settings=_settings(),
    )
    assert result["escalated"] is True
    assert result["escalation_reason"] == "no_draft_produced"


async def test_tool_escalation_signal_escalates(monkeypatch):
    tools = [_FakeTool("score_severity", raises=EscalationSignal("severity_unresolvable"))]
    result = await _run(
        monkeypatch,
        responses=[_ai_tool("score_severity")],
        tools=tools,
        settings=_settings(),
    )
    assert result["escalated"] is True
    assert result["escalation_reason"] == "severity_unresolvable"


async def test_tool_error_non_retryable_escalates(monkeypatch):
    tools = [_FakeTool("retrieve", raises=ToolError("no_groundable_claims", retryable=False))]
    result = await _run(
        monkeypatch,
        responses=[_ai_tool("retrieve")],
        tools=tools,
        settings=_settings(),
    )
    assert result["escalated"] is True
    assert result["escalation_reason"] == "no_groundable_claims"


async def test_tool_error_retryable_does_not_escalate(monkeypatch):
    """A retryable ToolError is surfaced to the model and the loop continues (no escalation)."""
    tools = [_FakeTool("retrieve", raises=ToolError("transient", retryable=True))]
    result = await _run(
        monkeypatch,
        responses=[_ai_tool("retrieve"), _ai_done()],
        tools=tools,
        settings=_settings(),
    )
    assert result["escalated"] is True  # ended with no draft...
    assert result["escalation_reason"] == "no_draft_produced"  # ...but NOT via tool escalation


async def test_unexpected_tool_exception_is_caught(monkeypatch):
    """An unexpected tool exception becomes a tool_error message; the loop keeps going."""
    tools = [_FakeTool("retrieve", raises=ValueError("boom"))]
    result = await _run(
        monkeypatch,
        responses=[_ai_tool("retrieve"), _ai_done()],
        tools=tools,
        settings=_settings(),
    )
    assert result["escalation_reason"] == "no_draft_produced"


async def test_iteration_cap_escalates_loop_cap(monkeypatch):
    """Model always requests a (non-draft) tool → loop hits the iteration cap."""
    tools = [_FakeTool("retrieve", result="[]")]
    result = await _run(
        monkeypatch,
        responses=[_ai_tool("retrieve")],  # repeats forever
        tools=tools,
        settings=_settings(max_iter=2),
    )
    assert result["escalated"] is True
    assert result["escalation_reason"] == "loop_cap"


async def test_token_cap_escalates_token_cap(monkeypatch):
    """One response over the token budget → loop hits the token cap."""
    tools = [_FakeTool("retrieve", result="[]")]
    result = await _run(
        monkeypatch,
        responses=[_ai_tool("retrieve", total_tokens=5000)],
        tools=tools,
        settings=_settings(max_iter=10, max_tokens=1000),
    )
    assert result["escalated"] is True
    assert result["escalation_reason"] == "token_cap"


async def test_guardrail_block_escalates(monkeypatch):
    async def _blocked(*a, **k):
        raise GuardBlocked("injection", "input")

    monkeypatch.setattr(graph_mod, "guard_text", _blocked)
    result = await _run(
        monkeypatch,
        responses=[_ai_tool("retrieve")],
        tools=[_FakeTool("retrieve", result="[]")],
        settings=_settings(),
    )
    assert result["escalated"] is True
    assert result["escalation_reason"] == "guardrail_blocked:injection"


async def test_guardrail_outage_escalates(monkeypatch):
    async def _outage(*a, **k):
        raise GuardrailsUnavailable("sidecar down")

    monkeypatch.setattr(graph_mod, "guard_text", _outage)
    result = await _run(
        monkeypatch,
        responses=[_ai_tool("retrieve")],
        tools=[_FakeTool("retrieve", result="[]")],
        settings=_settings(),
    )
    assert result["escalated"] is True
    assert result["escalation_reason"] == "guardrails_unavailable"


async def test_fatal_graph_error_escalates(monkeypatch):
    """An unexpected error inside the model call propagates out and is caught by run_agent."""
    result = await _run(
        monkeypatch,
        responses=[RuntimeError("model exploded")],
        tools=[_FakeTool("retrieve", result="[]")],
        settings=_settings(),
    )
    assert result["escalated"] is True
    assert result["escalation_reason"].startswith("graph_error:")


async def test_no_tool_call_first_turn_is_no_draft(monkeypatch):
    result = await _run(
        monkeypatch,
        responses=[_ai_done()],
        tools=[_FakeTool("draft_report", result="{}")],
        settings=_settings(),
    )
    assert result["escalated"] is True
    assert result["escalation_reason"] == "no_draft_produced"


async def test_redaction_enabled_redacts_untrusted_messages(monkeypatch):
    """With redaction on, Human/Tool message content is redacted before the guard/model call."""

    async def _redact(settings, text):
        return f"[R]{text}"

    monkeypatch.setattr(graph_mod, "redact_async", _redact)
    tools = [_FakeTool("draft_report", result='{"draft_body": "x", "claims": []}')]
    result = await _run(
        monkeypatch,
        responses=[_ai_tool("draft_report"), _ai_done()],
        tools=tools,
        settings=_settings(redaction_enabled=True),
    )
    assert result["draft_result"] == {"draft_body": "x", "claims": []}


async def test_usage_record_failure_is_swallowed(monkeypatch):
    """A best-effort usage-capture failure must never break the draft (FR-033)."""
    tools = [_FakeTool("draft_report", result='{"draft_body": "x", "claims": []}')]
    result = await _run(
        monkeypatch,
        responses=[_ai_tool("draft_report"), _ai_done()],
        tools=tools,
        settings=_settings(),
        record_usage=AsyncMock(side_effect=RuntimeError("usage table down")),
    )
    assert result["escalated"] is False
    assert result["draft_result"] == {"draft_body": "x", "claims": []}


async def test_redraft_path_loads_redraft_prompt_and_drafts(monkeypatch):
    """prior_draft_body/redraft_comment select the redraft system prompt and still draft."""
    tools = [_FakeTool("draft_report", result='{"draft_body": "v2", "claims": []}')]
    result = await _run(
        monkeypatch,
        responses=[_ai_tool("draft_report"), _ai_done()],
        tools=tools,
        settings=_settings(),
        prior_draft_body="v1 body",
        redraft_comment="add more grounding",
    )
    assert result["escalated"] is False
    assert result["draft_result"] == {"draft_body": "v2", "claims": []}
