"""US4/SC-007: the drafting-agent trace carries no unredacted PII/secret.

LangSmith auto-traces exactly the messages the agent sends to the model. Redaction is the
control (FR-024): app/agent/graph._redacted_messages redacts Human/Tool content before
chat_model.ainvoke, so whatever a trace captures is already redacted. This test plants PII +
a secret into the agent's input messages and asserts none survive in the messages the model
(and therefore the trace) would receive. The SystemMessage (our trusted prompt) is untouched.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.agent.graph import _redacted_messages
from app.core.config import Settings

pytestmark = pytest.mark.asyncio

_PII_TOKENS = ["John Smith", "00998877", "sk-ant-TRACESECRET0123456789", "123-45-6789"]


def _settings() -> Settings:
    s = Settings()
    s.redaction_enabled = True
    # tracing_enabled is irrelevant to the control: redaction happens regardless, and the trace
    # would only ever capture the already-redacted messages.
    s.tracing_enabled = True
    return s


async def test_agent_trace_messages_are_pii_free():
    messages = [
        SystemMessage(content="You are a pharmacovigilance drafting assistant."),
        HumanMessage(content="Finding for patient John Smith, MRN: 00998877, SSN 123-45-6789."),
        ToolMessage(
            content="Retrieved passage: contact sk-ant-TRACESECRET0123456789 re: hepatotoxicity.",
            tool_call_id="t1",
        ),
    ]
    redacted = await _redacted_messages(_settings(), messages)

    blob = "\n".join(str(m.content) for m in redacted)
    for token in _PII_TOKENS:
        assert token not in blob, f"PII/secret leaked into agent trace surface: {token!r}"
    # Clinical signal + the trusted system prompt survive.
    assert "hepatotoxicity" in blob
    assert "pharmacovigilance drafting assistant" in blob


async def test_redaction_disabled_is_passthrough():
    """With the test-only kill-switch off, messages pass through unchanged (prod refuses this)."""
    s = Settings()
    s.redaction_enabled = False
    messages = [HumanMessage(content="patient John Smith")]
    out = await _redacted_messages(s, messages)
    assert out[0].content == "patient John Smith"
