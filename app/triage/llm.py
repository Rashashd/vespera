"""Outbound LLM calls for triage: low-confidence YES/NO resolution and valence assessment."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import httpx
import structlog
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import Settings
from app.core.dispatcher import EventDispatcher
from app.guardrails.egress import guard_text
from app.infra.llm_adapter import LLMClient, build_llm_client
from app.observability.tracing import traced_llm_call
from app.redaction import redact_async

_log = structlog.get_logger(__name__)
_PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


@lru_cache(maxsize=4)
def _load_prompt(name: str) -> str:
    return (_PROMPT_DIR / name).read_text(encoding="utf-8")


class _AdverseResult(BaseModel):
    adverse: bool


class _ValenceResult(BaseModel):
    valence: str


def _should_retry(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError))


@traced_llm_call  # FR-032: trace the triage call site (inputs/outputs redacted to non-PII metadata)
@retry(
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
async def _call_llm(
    llm: LLMClient,
    system_prompt: str,
    user_content: str,
    max_tokens: int,
    *,
    session: object | None = None,
    settings: Settings | None = None,
    client_id: int | None = None,
) -> str:
    """Make the raw LLM HTTP call; retries on timeout/network, never on 4xx."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        if llm.provider == "anthropic":
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": llm.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": llm.model,
                    "max_tokens": max_tokens,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_content}],
                },
            )
            resp.raise_for_status()
            body = resp.json()
            in_tok = body.get("usage", {}).get("input_tokens", 0)
            out_tok = body.get("usage", {}).get("output_tokens", 0)
            text = body["content"][0]["text"]
        else:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {llm.api_key}",
                    "content-type": "application/json",
                },
                json={
                    "model": llm.model,
                    "max_tokens": max_tokens,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                },
            )
            resp.raise_for_status()
            body = resp.json()
            in_tok = body.get("usage", {}).get("prompt_tokens", 0)
            out_tok = body.get("usage", {}).get("completion_tokens", 0)
            text = body["choices"][0]["message"]["content"]

    # Best-effort usage capture (FR-033); never re-raises
    if session is not None and settings is not None and client_id is not None:
        try:
            from sqlalchemy.ext.asyncio import AsyncSession as _AS

            from app.observability.usage import record_usage as _rec

            if isinstance(session, _AS):
                await _rec(
                    session=session,
                    settings=settings,
                    call_site="triage",
                    model=llm.model,
                    client_id=client_id,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    finding_id=None,
                )
        except Exception:
            pass

    return text


async def resolve_yes_no(
    text: str,
    source_reliability: str,
    settings: Settings,
    client_id: int,
    document_id: int,
    session: object | None = None,
    dispatcher: EventDispatcher | None = None,
) -> bool:
    """Ask the LLM: is this document an adverse drug reaction? Returns True=YES.

    Raises on failure (incl. a blocked/unavailable guardrail) so the caller escalates.
    """
    llm = build_llm_client(settings)
    prompt_template = _load_prompt("triage_lowconf_resolve.txt")
    system_prompt = prompt_template.split("<document>")[0].strip()
    # Egress order (FR-012): redact → guard(input) → call → guard(output). A block/outage
    # raises → triage fail-safe escalates.
    user_content = await redact_async(settings, text)

    await guard_text(
        settings,
        text=user_content,
        direction="input",
        client_id=client_id,
        call_site="triage",
        session=session,
        dispatcher=dispatcher,
    )
    raw = await _call_llm(
        llm,
        system_prompt,
        user_content,
        settings.triage_llm_max_tokens,
        session=session,
        settings=settings,
        client_id=client_id,
    )
    await guard_text(
        settings,
        text=raw,
        direction="output",
        client_id=client_id,
        call_site="triage",
        session=session,
        dispatcher=dispatcher,
    )
    result = _AdverseResult.model_validate(json.loads(raw))
    return result.adverse


async def assess_valence(
    text: str,
    source_reliability: str,
    settings: Settings,
    client_id: int,
    document_id: int,
    session: object | None = None,
    dispatcher: EventDispatcher | None = None,
) -> str:
    """Ask the LLM for valence of a NO-classified finding. Returns 'positive' or 'irrelevant'.

    On any failure (incl. a blocked/unavailable guardrail), returns 'positive' (fail-safe
    default per FR-016); the guardrail event is still audited before falling back.
    """
    log = _log.bind(client_id=client_id, document_id=document_id)
    try:
        llm = build_llm_client(settings)
        prompt_template = _load_prompt("triage_valence.txt")
        system_prompt = (
            prompt_template.split("<document>")[0]
            .strip()
            .format(source_reliability=source_reliability)
        )
        # Egress order (FR-012): redact → guard(input) → call → guard(output).
        user_content = await redact_async(settings, text)

        await guard_text(
            settings,
            text=user_content,
            direction="input",
            client_id=client_id,
            call_site="triage",
            session=session,
            dispatcher=dispatcher,
        )
        raw = await _call_llm(
            llm,
            system_prompt,
            user_content,
            settings.triage_llm_max_tokens,
            session=session,
            settings=settings,
            client_id=client_id,
        )
        await guard_text(
            settings,
            text=raw,
            direction="output",
            client_id=client_id,
            call_site="triage",
            session=session,
            dispatcher=dispatcher,
        )
        result = _ValenceResult.model_validate(json.loads(raw))
        if result.valence not in ("positive", "irrelevant"):
            raise ValueError(f"unexpected valence: {result.valence!r}")
        return result.valence
    except Exception as exc:
        log.warning("triage.llm.valence_failed", reason=str(exc))
        return "positive"
