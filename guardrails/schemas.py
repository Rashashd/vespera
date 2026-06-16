"""Standalone request/response schemas for the guardrails sidecar (mirrors app/guardrails)."""

from typing import Literal

from pydantic import BaseModel


class GuardRequest(BaseModel):
    """One payload (prompt or model output) to evaluate against the platform rails."""

    text: str
    direction: Literal["input", "output"]
    client_id: int
    call_site: Literal["triage", "agent", "intake"]


class GuardResponse(BaseModel):
    """Rail evaluation result; never echoes the input text or any PII."""

    action: Literal["allow", "block"]
    rail: str | None = None
    reason: str | None = None
    checked: list[str] = []
