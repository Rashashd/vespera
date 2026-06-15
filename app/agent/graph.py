"""Bounded LangGraph drafting graph — hard-capped on iterations and tokens (FR-022)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from app.agent.state import DraftingState
from app.agent.tools import EscalationSignal, ToolError, make_tools
from app.core.config import Settings
from app.triage.models import Finding

_log = structlog.get_logger(__name__)
_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPT_DIR / name).read_text(encoding="utf-8")


def _build_compiled_graph(
    settings: Settings,
    session: Any,
    redis: Any,
    ms_client: Any,
    client: Any,
    app_state: Any,
    finding: Finding,
) -> Any:
    """Build and compile the bounded StateGraph for one agent run."""
    from app.agent.llm_binding import build_agent_chat_model

    tools = make_tools(session, redis, ms_client, client, app_state, finding=finding)
    tool_map = {t.name: t for t in tools}
    chat_model = build_agent_chat_model(settings).bind_tools(tools)

    async def agent_node(state: DraftingState) -> dict:
        response = await chat_model.ainvoke(state["messages"])
        usage = getattr(response, "usage_metadata", None) or {}
        in_tok = usage.get("input_tokens", 0) if isinstance(usage, dict) else 0
        out_tok = usage.get("output_tokens", 0) if isinstance(usage, dict) else 0
        tokens_delta = usage.get("total_tokens", 0) if isinstance(usage, dict) else 0
        # Best-effort cost capture (FR-033); swallowed on failure
        try:
            from app.observability.usage import record_usage as _rec

            await _rec(
                session=session,
                settings=settings,
                call_site="agent",
                model=(
                    settings.anthropic_model
                    if settings.preferred_provider == "anthropic"
                    else settings.openai_model
                ),
                client_id=client.id,
                input_tokens=in_tok,
                output_tokens=out_tok,
                finding_id=finding.id,
            )
        except Exception:
            pass
        return {
            "messages": [response],
            "iterations_used": state["iterations_used"] + 1,
            "tokens_used": state["tokens_used"] + tokens_delta,
        }

    async def tool_node(state: DraftingState) -> dict:
        last = state["messages"][-1]
        if not isinstance(last, AIMessage) or not last.tool_calls:
            return {}

        tool_messages: list[ToolMessage] = []
        new_state: dict = {}

        for call in last.tool_calls:
            tool_fn = tool_map.get(call["name"])
            if tool_fn is None:
                tool_messages.append(
                    ToolMessage(
                        content=f"unknown_tool: {call['name']}",
                        tool_call_id=call["id"],
                        status="error",
                    )
                )
                continue
            try:
                result = await tool_fn.ainvoke(call["args"])
                content = result if isinstance(result, str) else json.dumps(result)
                tool_messages.append(ToolMessage(content=content, tool_call_id=call["id"]))
                if call["name"] == "draft_report":
                    new_state["draft_result"] = json.loads(content)
                elif call["name"] == "draft_followup":
                    new_state["followup_result"] = json.loads(content)
            except EscalationSignal as exc:
                new_state["escalated"] = True
                new_state["escalation_reason"] = exc.reason
                tool_messages.append(
                    ToolMessage(
                        content=f"escalated: {exc.reason}",
                        tool_call_id=call["id"],
                        status="error",
                    )
                )
            except ToolError as exc:
                if not exc.retryable:
                    new_state["escalated"] = True
                    new_state["escalation_reason"] = str(exc)
                tool_messages.append(
                    ToolMessage(
                        content=str(exc),
                        tool_call_id=call["id"],
                        status="error",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "agent.tool.unexpected_error",
                    tool=call["name"],
                    finding_id=finding.id,
                    error=str(exc),
                )
                tool_messages.append(
                    ToolMessage(
                        content=f"tool_error: {exc}",
                        tool_call_id=call["id"],
                        status="error",
                    )
                )

        return {"messages": tool_messages, **new_state}

    def should_continue(state: DraftingState) -> Literal["tools", END]:  # type: ignore[valid-type]
        if state.get("escalated"):
            return END
        last = state["messages"][-1] if state["messages"] else None
        if not isinstance(last, AIMessage) or not getattr(last, "tool_calls", None):
            return END
        if state["iterations_used"] >= settings.agent_max_iterations:
            return END
        if state["tokens_used"] >= settings.agent_max_tokens:
            return END
        return "tools"

    graph = StateGraph(DraftingState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


async def run_agent(
    *,
    finding: Finding,
    client: Any,
    session: Any,
    redis: Any,
    ms_client: Any,
    app_state: Any,
    settings: Settings,
    prior_draft_body: str = "",
    redraft_comment: str = "",
) -> dict:
    """Run the bounded drafting agent; return outcome dict.

    Returns:
        escalated: bool
        escalation_reason: str
        draft_result: dict | None  (claims, draft_body from draft_report tool)
        followup_result: dict | None  (cover_message, template_ref for emergency)
    """
    log = _log.bind(client_id=client.id, finding_id=finding.id)

    is_redraft = bool(prior_draft_body or redraft_comment)
    system_text = _load_prompt("system_redraft.txt" if is_redraft else "system_draft.txt")

    human_parts = [
        f"Finding ID: {finding.id}",
        f"Drug: {finding.drug}",
        f"Reaction: {finding.reaction}",
        f"Bucket: {finding.bucket}",
    ]
    if is_redraft and prior_draft_body:
        human_parts.append(f"\nPRIOR DRAFT:\n{prior_draft_body}")
    if redraft_comment:
        human_parts.append(f"\nREVIEWER COMMENT:\n{redraft_comment}")

    initial_state: DraftingState = {
        "messages": [
            SystemMessage(content=system_text),
            HumanMessage(content="\n".join(human_parts)),
        ],
        "iterations_used": 0,
        "tokens_used": 0,
        "escalated": False,
        "escalation_reason": "",
        "draft_result": None,
        "followup_result": None,
        "finding_id": finding.id,
        "client_id": client.id,
        "prior_draft_body": prior_draft_body,
        "redraft_comment": redraft_comment,
    }

    compiled = _build_compiled_graph(
        settings, session, redis, ms_client, client, app_state, finding
    )

    try:
        final_state = await compiled.ainvoke(initial_state)
    except Exception as exc:  # noqa: BLE001
        log.error("agent.graph.fatal_error", error=str(exc))
        return {
            "escalated": True,
            "escalation_reason": f"graph_error: {exc}",
            "draft_result": None,
            "followup_result": None,
        }

    escalated: bool = final_state.get("escalated", False)
    escalation_reason: str = final_state.get("escalation_reason", "")
    draft_result = final_state.get("draft_result")
    followup_result = final_state.get("followup_result")

    if not escalated and draft_result is None:
        # Loop ended without a draft — determine why
        if final_state.get("iterations_used", 0) >= settings.agent_max_iterations:
            escalation_reason = "loop_cap"
        elif final_state.get("tokens_used", 0) >= settings.agent_max_tokens:
            escalation_reason = "token_cap"
        else:
            escalation_reason = "no_draft_produced"
        escalated = True

    log.info(
        "agent.run.complete",
        escalated=escalated,
        reason=escalation_reason,
        iterations=final_state.get("iterations_used", 0),
        tokens=final_state.get("tokens_used", 0),
    )
    return {
        "escalated": escalated,
        "escalation_reason": escalation_reason,
        "draft_result": draft_result,
        "followup_result": followup_result,
    }
