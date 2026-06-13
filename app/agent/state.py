"""TypedDict agent state for the bounded LangGraph drafting graph."""

from __future__ import annotations

from typing import Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class DraftingState(TypedDict):
    """State threaded through the bounded agent loop.

    messages: append-only conversation history (LangGraph add_messages reducer).
    iterations_used: number of tool-calling rounds consumed so far.
    tokens_used: cumulative token count across LLM calls this run.
    escalated: True when the agent explicitly escalates instead of drafting.
    draft_result: final DraftResult from the draft_report tool, or None.
    finding_id: the finding being drafted for.
    client_id: tenant boundary — all retrieval is scoped to this client.
    prior_draft_body: prior draft text passed in for redraft runs.
    redraft_comment: reviewer comment from the reject action for redraft runs.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    iterations_used: int
    tokens_used: int
    escalated: bool
    escalation_reason: str
    draft_result: dict | None
    followup_result: dict | None
    finding_id: int
    client_id: int
    prior_draft_body: str
    redraft_comment: str
