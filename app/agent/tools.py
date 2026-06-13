"""Five agent tools for the bounded LangGraph drafting pipeline (ToolError contract)."""

from __future__ import annotations

import json
from typing import Any

import structlog
from langchain_core.tools import tool
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.embedding.models import Chunk
from app.rag.schemas import RetrieveRequest
from app.triage.models import Finding

_log = structlog.get_logger(__name__)


class ToolError(Exception):
    """Raised by tools when they fail; carries retryability signal."""

    def __init__(self, message: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class EscalationSignal(Exception):
    """Raised by the escalate tool to signal a terminal escalation outcome."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ClaimDraft(BaseModel):
    """One claim the LLM proposes for the structured report."""

    field: str
    text: str
    source_ref: str | None = None


class DraftReportInput(BaseModel):
    """Input for the draft_report tool."""

    claims: list[ClaimDraft]
    draft_body: str
    # Corroboration metadata from the retrieve response (LLM passes through)
    corroboration_sources: list[dict] = []


class DraftFollowupInput(BaseModel):
    """Input for the draft_followup tool (emergency only)."""

    cover_message: str


class EscalateInput(BaseModel):
    """Input for the escalate tool."""

    reason: str


async def _validate_chunk_refs(session: AsyncSession, client_id: int, refs: list[str]) -> set[str]:
    """Return the subset of refs that are valid chunk IDs for this client."""
    if not refs:
        return set()
    int_refs = []
    for r in refs:
        try:
            int_refs.append(int(r))
        except (ValueError, TypeError):
            pass
    if not int_refs:
        return set()
    rows = (
        (
            await session.execute(
                select(Chunk.id).where(
                    Chunk.id.in_(int_refs),
                    Chunk.client_id == client_id,
                )
            )
        )
        .scalars()
        .all()
    )
    return {str(r) for r in rows}


def make_tools(
    session: AsyncSession,
    redis: Any,
    ms_client: Any,
    client: Any,
    app_state: Any,
    finding: Finding,
) -> list:
    """Factory: return the 5 bound tools for a single agent run."""

    @tool("retrieve")
    async def retrieve(query: str, top_k: int = 10) -> str:
        """Retrieve relevant pharmacovigilance passages from the corpus.

        Returns ranked passages with chunk_ids to use as source_refs in claims.
        Use top_k ≤ 20 for focused queries.
        """
        from app.rag import service as rag_service

        try:
            req = RetrieveRequest(query=query, top_k=min(max(top_k, 1), 20))
            response = await rag_service.retrieve(session, redis, ms_client, client, req, app_state)
        except Exception as exc:
            _log.warning(
                "agent.retrieve.error",
                client_id=client.id,
                finding_id=finding.id,
                error=str(exc),
            )
            raise ToolError(f"retrieve failed: {exc}", retryable=True) from exc

        if not response.results:
            raise ToolError(
                "no_evidence: corpus returned no results for this query", retryable=False
            )

        passages = [
            {
                "chunk_id": str(p.chunk_id),
                "text": p.text[:800],
                "title": p.title,
                "external_id": p.external_id,
                "source_reliability": p.source_reliability,
                "score": round(p.score, 4),
            }
            for p in response.results
        ]
        return json.dumps(
            {
                "passages": passages,
                "corroboration_count": response.corroboration_count,
                "corroboration_sources": [s.model_dump() for s in response.corroboration_sources],
            }
        )

    @tool("score_severity")
    async def score_severity() -> str:
        """Return the finding's severity bucket, drug, and reaction (read-only)."""
        return json.dumps(
            {
                "bucket": finding.bucket,
                "drug": finding.drug,
                "reaction": finding.reaction,
                "finding_id": finding.id,
            }
        )

    @tool("draft_report", args_schema=DraftReportInput)
    async def draft_report(
        claims: list[ClaimDraft],
        draft_body: str,
        corroboration_sources: list[dict] | None = None,
    ) -> str:
        """Submit the grounded structured report.

        Each claim must carry source_ref=chunk_id from a retrieved passage.
        Ungroundable claims (missing or invalid source_ref) are automatically dropped.
        Returns the validated claim list and corroboration summary.
        """
        all_refs = [c.source_ref for c in claims if c.source_ref]
        valid_refs = await _validate_chunk_refs(session, client.id, all_refs)

        grounded = [
            {
                "field": c.field,
                "text": c.text,
                "provenance": "drafted_grounded",
                "source_ref": c.source_ref,
            }
            for c in claims
            if c.source_ref and c.source_ref in valid_refs
        ]

        if not grounded:
            raise ToolError(
                "no_groundable_claims: all proposed claims lack valid evidence; "
                "retrieve more relevant passages or escalate",
                retryable=False,
            )

        # Compute verified corroboration count from distinct document_ids of valid chunks
        int_refs = [int(r) for r in valid_refs]
        doc_id_rows = (
            (
                await session.execute(
                    select(Chunk.document_id)
                    .where(Chunk.id.in_(int_refs), Chunk.client_id == client.id)
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
        corroboration_count = len(doc_id_rows)

        return json.dumps(
            {
                "claims": grounded,
                "draft_body": draft_body,
                "corroboration_count": corroboration_count,
                "corroboration_sources": corroboration_sources or [],
                "valid_claim_count": len(grounded),
                "dropped_claim_count": len(claims) - len(grounded),
            }
        )

    @tool("draft_followup", args_schema=DraftFollowupInput)
    async def draft_followup(cover_message: str) -> str:
        """Create the emergency author-outreach follow-up artifact (emergency bucket only).

        cover_message: a concise summary of the finding for the follow-up recipient.
        Only call this for emergency-severity findings.
        """
        return json.dumps(
            {
                "template_ref": "emergency_author_outreach_v1",
                "cover_message": cover_message,
                "finding_id": finding.id,
            }
        )

    @tool("escalate", args_schema=EscalateInput)
    async def escalate(reason: str) -> str:
        """Escalate this finding to a human operator — no report will be created.

        Use when: no relevant evidence found, grounding is impossible, or you cannot
        produce a compliant draft. reason should be one of:
        ungroundable_no_evidence | ungroundable_no_claims | cannot_comply.
        """
        raise EscalationSignal(reason)

    return [retrieve, score_severity, draft_report, draft_followup, escalate]
