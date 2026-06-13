# Implementation Plan: Report Drafting (Bounded Agent + Human-in-the-Loop)

**Branch**: `009-report-drafting` | **Date**: 2026-06-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/009-report-drafting/spec.md`

> **READ FIRST before `/speckit-implement`:** `specs/009-report-drafting/implementation-notes.md` (anti-hallucination guide — exact signatures, fields, and patterns verified against the live codebase). To be authored after `/speckit-tasks`, per the project standing rule.

## Summary

Spec 9 converts severity-bucketed **findings** (spec 8) into **grounded, structured safety reports** drafted by a **bounded LangGraph agent**, and holds every report behind a **mandatory `reviewer`-only approval gate** before it is eligible for delivery. Two report modes: **expedited** (one per `urgent`/`emergency` finding, drafted immediately, SLA-deadlined) and **batch** (one consolidated document per watchlist per cadence cycle). The agent runs a hard-capped tool loop (`retrieve`, `score_severity`, `draft_report`, `draft_followup`, `escalate`); every claim cites a retrieved passage or is omitted; every failure fails toward a human (agent-side failures → operator alert; 4th rejection → `needs_manual_revision` in the reviewer queue). `emergency` findings additionally produce a fixed author-outreach follow-up artifact (template + cover message; sending deferred).

**Technical approach:** new `app/agent/` package (LangGraph bounded drafting graph + tools + prompts) and `app/reports/` package (Report/ReportFinding/Followup ORM, HITL state machine, reviewer + consolidation endpoints). Reuses spec-7 hybrid retrieval (`app.rag.service.retrieve`), spec-8 findings + the tenacity-wrapped provider-branch LLM pattern (`app/triage/llm.py`), the domain-event dispatcher + passive audit listener, and `acting_client()` route scoping. Migration **0008** adds `reports` + `report_findings` + `report_followups`, widens `findings.status`, and adds `biweekly` to the watchlist cadence. New CI eval gate: agent-tool-selection accuracy (≥0.85) + report grounding + planted-injection red-team.

## Technical Context

**Language/Version**: Python 3.13 + `uv`

**Primary Dependencies**: FastAPI, SQLAlchemy 2 (async), Pydantic v2, **LangGraph (new)** for the bounded tool-calling agent, a LangChain chat-model binding for native function-calling (`langchain-anthropic` / `langchain-openai`, provider-pinned), `httpx` + `tenacity` (existing outbound pattern), `structlog`, Alembic. Retrieval via existing `app/rag`; LLM via existing provider-branch pattern.

**Storage**: PostgreSQL + pgvector (reports/findings relational; retrieval reuses existing `chunks`). Redis (existing query-embedding cache; no new Redis state required for v1 HITL).

**Testing**: `pytest` (unit + integration; integration needs `PANTERA_INTEGRATION=1` + docker compose). New golden sets under `tests/data/`. CI eval job extended.

**Target Platform**: Linux server (modular monolith); no new serving container (LangGraph runs in-process in the API; ARQ durability is spec 11).

**Project Type**: Backend web service (modular monolith) — single project.

**Performance Goals**: Expedited draft available in the reviewer queue within minutes of finding creation (SC-007). Agent loop hard-capped on iterations + tokens (cost + safety). No latency added to the triage request hot path (drafting runs via commit-then-BackgroundTasks, mirroring spec 8).

**Constraints**: No torch in any serving container (N/A here — no model serving added). No MCP servers (LangGraph direct tool-calling). Tools return `ToolError(error, retryable)`, never raise. Async throughout. Files ≤ ~300 lines. Secrets only via Vault. PRs < 400 lines. Reviewer-only approval is absolute.

**Scale/Scope**: ~31 functional requirements + 11 success criteria. New packages `app/agent/`, `app/reports/`; migration 0008; ~5 agent tools; ~6 reviewer/consolidation endpoints; new domain events; one new CI eval gate. Estimated 30–40 tasks.

## Constitution Check

*GATE: must pass before Phase 0 and re-checked after Phase 1 design.*

| Principle | Status | How this plan satisfies it |
|-----------|--------|----------------------------|
| **I. Human-in-the-Loop Authority** (NON-NEGOTIABLE) | ✅ PASS | No report reaches `approved`/ready-to-send without a logged `reviewer` decision (FR-014/019/021). Drafting and sending are separate — this feature stops at `approved`. Redrafts capped at 3 (FR-016). **Design note:** the HITL "approval node" is realized as the persisted reports state-machine + reviewer-only endpoints rather than a single LangGraph run held suspended across human think-time; the durable checkpointer-backed `interrupt()` form is the spec-11 evolution. The gate's *absoluteness* is unchanged. Recorded in Complexity Tracking. |
| **II. Grounding Is the Grade** (NON-NEGOTIABLE) | ✅ PASS | Every machine-drafted claim cites a retrieved passage or is omitted (FR-004, grounded defined objectively). Multi-source corroboration count + all-N sources surfaced (FR-007/008/009). Grounding + planted-injection are CI-gated (SC-001/SC-010). Reviewer edits are a trusted human override tagged `reviewer-attested` (out of the automated gate, in the audit trail). |
| **III. Triage Fails Safe** | ✅ PASS | `score_severity` is read/confirm-only — it never re-buckets; the transparent spec-8 keyword rule stays the single source of truth (FR-023). |
| **IV. Every Decision Backed by a Number** | ✅ PASS | New committed thresholds in `eval_thresholds.yaml`: agent-tool-selection ≥0.85 (SC-004), corroboration accuracy ≥0.75 (SC-003), report grounding gate (SC-001). CI eval job blocks regressions. |
| **V. Multi-Tenant Isolation** (NON-NEGOTIABLE) | ✅ PASS | All drafting/retrieval/persistence client-scoped (FR-028). Corroboration is client-wide but never crosses the client boundary. `acting_client()` + `client_id` on every new row. Operator (staff `reviewer`) access is attributed + audited. |
| **VI. Lean, Reproducible, Justified Architecture** | ✅ PASS | No new serving container; LangGraph in-process, direct tool-calling, **no MCP**. LLM provider pinned (existing config). `uv`-managed. New deps (`langgraph`, one chat-model adapter) justified below. Files ≤300 lines; two packages split by concern (agent = drafting; reports = persistence/HITL/API). |
| **VII. Own Every Line (Spec-Driven)** | ✅ PASS | spec → plan → tasks → implement followed; implementation-notes.md ships before implement; Conventional Commits, PRs <400 lines. |

**Security & Standards gates:** Async throughout; Pydantic validates API bodies + LangGraph tool inputs + LLM structured output; tenacity on all outbound (never retry 4xx); `ToolError` contract; bounded agent (iteration + token caps); config in `Settings` (`extra="forbid"`); structlog with `client_id`/`finding_id` bound; PII/secret redaction posture (FR-031). **Open constitution deviation (documented):** NeMo Guardrails sidecar is absent in this feature — mitigated by the hardened untrusted-data system prompt + CI planted-injection case; full guardrails close in spec 12 (same posture as spec 8).

**Result: PASS** (one justified realization note for Principle I; one documented deferral for guardrails — both in Complexity Tracking).

## Project Structure

### Documentation (this feature)

```text
specs/009-report-drafting/
├── plan.md                  # This file
├── research.md              # Phase 0 — key design decisions
├── data-model.md            # Phase 1 — reports/findings schema + events
├── quickstart.md            # Phase 1 — end-to-end validation scenarios
├── contracts/               # Phase 1 — endpoint contracts
│   ├── drafting.md          #   expedited trigger + agent-run contract
│   ├── reviewer-actions.md  #   approve / edit / reject / discard + per-finding
│   └── batch-consolidation.md  # per-watchlist consolidate endpoint
├── checklists/
│   ├── requirements.md      # spec-quality (passing)
│   └── release-gate.md      # requirements-quality release gate
├── implementation-notes.md  # READ-FIRST anti-hallucination guide (pre-implement)
└── tasks.md                 # /speckit-tasks output (not created here)
```

### Source Code (repository root)

```text
app/
├── agent/                   # NEW — bounded LangGraph drafting pipeline
│   ├── __init__.py
│   ├── graph.py             # StateGraph: bounded loop (iteration + token caps), interrupt-free draft/redraft runs
│   ├── state.py             # TypedDict agent state + cap counters
│   ├── tools.py             # retrieve / score_severity / draft_report / draft_followup / escalate (ToolError contract)
│   ├── llm_binding.py       # provider-pinned chat model with .bind_tools() (reuses provider/config)
│   └── prompts/             # versioned prompts (untrusted-data system prompt, draft, redraft, followup)
├── reports/                 # NEW — report persistence + HITL + API
│   ├── __init__.py
│   ├── models.py            # Report, ReportFinding, ReportFollowup ORM
│   ├── enums.py             # ReportType, ReportStatus, ClaimProvenance, FindingReportState
│   ├── schemas.py           # Pydantic request/response (no ORM leakage)
│   ├── service.py           # HITL state machine + batch consolidation orchestration
│   ├── consolidation.py     # per-watchlist batch grouping (via document_watchlists), idempotent claim
│   ├── runner.py            # in-process expedited-drafting trigger (commit-then-BackgroundTasks)
│   └── routes.py            # reviewer actions + trigger + consolidate (acting_client + reviewer guard)
├── triage/models.py         # EXTEND findings.status enum usage (no struct change beyond migration)
├── clients/enums.py         # EXTEND Cadence with BIWEEKLY
├── clients/models.py        # EXTEND watchlists cadence CHECK (via migration 0008)
├── domain/events.py         # ADD ReportDrafted/Edited/Rejected/Discarded, FindingDiscarded, ReportOperatorAlert, BatchConsolidated (ReportApproved exists)
├── core/config.py           # ADD agent caps + SLA + redraft cap settings
└── db/migrations/versions/0008_reports_and_followups.py   # NEW migration

tests/
├── unit/                    # agent tools, state caps, HITL state machine, consolidation grouping
├── integration/             # end-to-end draft→review→approve; batch; isolation; idempotency
└── data/
    ├── agent_tool_selection_golden.jsonl   # ~15 examples (SC-004, ≥0.85)
    └── report_grounding_golden.jsonl       # grounding + planted-injection (SC-001/SC-010)
```

**Structure Decision**: Single backend project (modular monolith). Two new packages split by concern — `app/agent/` owns the LangGraph drafting brain (graph, tools, prompts, LLM binding); `app/reports/` owns persistence, the HITL state machine, batch consolidation, and the reviewer API. The split keeps each file under the ~300-line limit and isolates the agent (testable against golden sets) from the durable report lifecycle (testable as a state machine). This mirrors the spec-8 separation of `service`/`routes`/`models` and the standing `app/<domain>/` convention.

## Complexity Tracking

| Item | Why needed / chosen | Simpler alternative rejected because |
|------|---------------------|--------------------------------------|
| **New dep: `langgraph` + one LangChain chat-model adapter** | Constitution VI mandates LangGraph direct tool-calling (no MCP). Native provider function-calling is needed for the fixed tool set; LangChain chat models provide `.bind_tools()` cleanly and pin the provider/model. | Hand-rolling tool-calling over raw `httpx` (as triage does) re-implements function-call plumbing and JSON-schema tool dispatch LangGraph/LangChain already provide, and diverges from the constitution's named approach. |
| **HITL gate realized as persisted reports state-machine, not a suspended LangGraph `interrupt()` run** (Principle I realization note) | A graph held suspended across human think-time (hours/days) in-process is fragile and lost on restart; persisting the draft to `reports` and re-invoking the graph for redraft is durable now and survives restarts. The gate stays absolute. | A live `interrupt()`+checkpointer suspended run needs durable orchestration that is explicitly spec-11 (ARQ) scope; pulling it forward violates the lean/bounded-now principle and duplicates spec-11. Documented as the spec-11 evolution. |
| **NeMo Guardrails absent** (documented deferral) | Same posture as spec 8: hardened untrusted-data system prompt + CI planted-injection golden case mitigate injection now; full sidecar is spec 12. | Adding the guardrails sidecar here is spec-12 scope (security boundary container) and out of this feature's slice. |
| **Batch attribution derived via `document_watchlists` (no `watchlist_id` on findings)** | A document can belong to multiple watchlists; deriving membership + idempotent "report-once-per-client" claiming honors the user's "store/report once per client" intent without a redundant column or per-(finding,watchlist) state explosion. | A `watchlist_id` column forces an artificial single-watchlist choice and contradicts the many-to-many reality; a per-(finding,watchlist) reporting matrix is heavier than v1 needs. See research.md D2. |
