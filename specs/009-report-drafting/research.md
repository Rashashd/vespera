# Phase 0 Research: Report Drafting (Bounded Agent + HITL)

Decisions resolving the unknowns in the Technical Context. Each: **Decision / Rationale / Alternatives considered**. Verified against the live codebase (spec 7 `app/rag`, spec 8 `app/triage`, `app/domain`, `app/core`).

---

## D1 — LangGraph agent shape & LLM binding (no MCP)

**Decision.** Add `langgraph` plus a provider-pinned LangChain chat-model adapter (`langchain-anthropic` / `langchain-openai`, selected by `settings.preferred_provider`, model pinned by `settings.anthropic_model` / `settings.openai_model`). Build a **custom `StateGraph`** with an explicit bounded loop (LLM-decides-tool → ToolNode → loop), not the prebuilt `create_react_agent`. The graph state carries `iterations_used` and `tokens_used`; an edge guard halts and escalates when either cap (`settings.agent_max_iterations`, `settings.agent_max_tokens`) is hit. Tools are bound via `.bind_tools()` for native provider function-calling.

**Rationale.** Constitution VI requires LangGraph direct tool-calling and forbids MCP. A custom `StateGraph` lets us enforce the constitution's iteration **and** token caps precisely, implement the `ToolError(error, retryable)` contract in the ToolNode (retryable → loop within cap; non-retryable → escalate), and keep the loop auditable for the tool-selection golden set (SC-004). LangChain chat models give native function-calling without hand-rolling JSON-schema dispatch.

**Alternatives considered.** (a) Prebuilt `create_react_agent` — rejected: harder to hard-cap tokens and to interpose the `ToolError`/escalation contract; less control for the eval trace. (b) Raw `httpx` tool-calling like `app/triage/llm.py` — rejected: re-implements provider function-calling plumbing LangGraph already provides and diverges from the constitution's named approach. (c) MCP tool server — rejected outright (Constitution VI).

---

## D2 — Watchlist attribution for batch grouping

**Decision.** Do **not** add `watchlist_id` to `findings`. Derive a finding's watchlist membership through the existing `document_watchlists` junction at consolidation time. Batch consolidation for watchlist *W* selects `pending_batch` findings whose `document_id ∈ document_watchlists(watchlist_id=W)`, and **claims them idempotently**: a claimed finding flips `findings.status → reported` and is linked via `report_findings`, so it cannot be re-reported by another of the same client's watchlists. First watchlist to consolidate wins.

**Rationale.** A document can belong to multiple watchlists (`document_watchlists` is many-to-many with `client_id`). The user's explicit intent is "store/report a finding once per client" while "each watchlist gets its own report." Derivation + idempotent claiming delivers exactly that with no redundant column and no per-(finding, watchlist) state matrix. It reconciles the spec's "findings carry their watchlist of origin" to **"findings are attributable to watchlists via `document_watchlists`"** (a strengthening, not a contradiction — captured as a spec note).

**Alternatives considered.** (a) `watchlist_id` FK on findings — rejected: forces an artificial single-watchlist choice that contradicts the many-to-many reality and needs backfill. (b) `finding_watchlist_state` matrix (per-watchlist reporting state) — rejected: heavier than v1 needs and enables the same finding to be reported in two of one client's watchlists, which the user explicitly does not want. (c) Triage runs per-watchlist to stamp origin — rejected: spec-8 triage flattens `watchlist_drugs`; changing its grain is out of scope and risks duplicate findings.

**Edge consequence pinned:** `drop-from-this-report` returns the finding to `pending_batch` (re-eligible for the same watchlist next cycle); `discard-permanently` → `discarded` (terminal).

---

## D3 — HITL realization (persisted state machine vs suspended graph)

**Decision.** The HITL approval gate is the **persisted `reports` status machine** + reviewer-only endpoints. The agent graph runs to "drafted" and ends; the draft is persisted. Reviewer actions are ordinary authenticated endpoint calls: Approve/Edit→Approve are pure state transitions; Reject-with-comment triggers a **fresh** bounded graph run (redraft) seeded with prior draft + comment; the 4th rejection sets `needs_manual_revision`. No LangGraph run is held suspended across human think-time.

**Rationale.** Durability now without spec-11: the draft lives in Postgres, so a process restart never loses an in-flight approval. The gate stays absolute (no transition to `approved` without a reviewer-bound audit event). Cleanly testable as a state machine. The durable `interrupt()`+checkpointer form is the natural spec-11 (ARQ) evolution and is noted as such.

**Alternatives considered.** Live `interrupt()` + checkpointer suspended run — rejected for v1: requires durable orchestration that is explicitly spec-11 scope; fragile in-process across long human latency. Recorded in plan Complexity Tracking against Principle I.

---

## D4 — `reports` / `report_findings` / `report_followups` schema (migration 0008)

**Decision.** New tables (full shapes in data-model.md):
- `reports` — id, client_id, report_type (`expedited`|`batch`), status, structured_fields (JSONB, with per-claim provenance), draft_body, corroboration summary, revision_count, reviewer_comments (JSONB history), sla_deadline (expedited), watchlist_id + cycle_period (batch), timestamps.
- `report_findings` — report↔finding junction (batch membership + per-finding state: `included` / `dropped` / `discarded`).
- `report_followups` — emergency author-outreach artifact (finding_id, expedited report_id, template_ref, cover_message, recipient placeholder); **not** in the reviewer queue.
- `findings.status` CHECK widened: add `processing`, `reported`, `discarded` (keep existing `pending_expedited`/`pending_batch`/`classified`).
- `watchlists.cadence` CHECK widened: add `biweekly`; mirror in `app/clients/enums.py:Cadence`.

**Rationale.** Matches the Key Entities in the spec and the guide's `reports` shape; reuses the existing `findings.corroboration_sources` JSONB (already present) for corroboration persistence. `report_findings` carries the Q4 drop/discard semantics without bloating `findings`. `report_followups` keeps the follow-up out of the drafts-only reviewer queue.

**Alternatives considered.** Single `reports` table with a `followup` type — rejected: would surface follow-ups in the reviewer queue (violates "reviewer sees only written reports"). Storing batch membership as a JSON array on `reports` — rejected: per-finding drop/discard state + audit needs first-class rows.

---

## D5 — Claim provenance (drafted-grounded vs reviewer-attested)

**Decision.** Store report content as a structured claim list inside `structured_fields` (JSONB), each claim carrying `provenance` (`drafted_grounded` | `reviewer_attested`) and, for grounded claims, the supporting source/passage reference. Machine drafting writes `drafted_grounded`; Edit-then-Approve flips edited/added claims to `reviewer_attested`. The CI grounding gate (SC-001) evaluates only `drafted_grounded` claims. The client-facing rendering omits provenance labels (audit-only).

**Rationale.** Implements the pass-2 hybrid clarification with one JSONB shape; keeps the grounding gate's scope objective and the audit trail honest without scaring the client.

**Alternatives considered.** Free-text `draft_body` only (no claim structure) — rejected: can't scope the grounding gate or tag edits. Separate provenance table — rejected: over-normalized for v1; JSONB on the report suffices.

---

## D6 — Trigger wiring (in-process, no ARQ)

**Decision.** Expedited drafting fires **in-process after the triage finding upsert**, mirroring how triage fires after indexing in spec 8: commit the finding, then `BackgroundTasks.add_task(...)` the drafting runner (commit-before-add_task per the bg-tasks-session-timing memory). Batch consolidation fires from a **manual/admin per-watchlist endpoint** (`POST /clients/{id}/watchlists/{wid}/consolidate-batch`). Durable ARQ/cron wrapping = spec 11 (which calls the same runner/endpoint).

**Rationale.** Keeps the triage request off the agent's latency; durable queueing is explicitly spec-11. Reuses the established BackgroundTasks pattern and its session-timing fix.

**Alternatives considered.** Synchronous drafting inside the triage request — rejected: blocks the hot path. ARQ now — rejected: spec-11 scope.

---

## D7 — Eval gates & golden sets (eval_thresholds.yaml)

**Decision.** Add to `eval_thresholds.yaml`: `agent_tool_selection_accuracy_min: 0.85` (SC-004, ≥15-example `tests/data/agent_tool_selection_golden.jsonl`), report grounding gate (SC-001, every drafted claim resolvable on `tests/data/report_grounding_golden.jsonl`), and the planted-injection red-team case (SC-010). Corroboration accuracy ≥0.75 already exists from spec 7; reuse/extend for report-level corroboration (SC-003). Runtime knobs (agent caps, redraft cap = 3, SLA window) live in `Settings`, **not** the eval file (per the spec-8 convention). CI `eval` job runs these self-contained (no `PANTERA_INTEGRATION`).

**Rationale.** Constitution IV — every agent/grounding decision backed by a committed number that blocks regressions. Mirrors the spec-8 eval-gate wiring and threshold-placement convention.

**Alternatives considered.** Putting caps/SLA in `eval_thresholds.yaml` — rejected (spec-8 lesson: that file holds only CI thresholds).

---

## D8 — Domain events & audit

**Decision.** Reuse the existing `ReportApproved` event (`app/domain/events.py:27`); add `ReportDrafted`, `ReportEdited`, `ReportRejected`, `ReportDiscarded`, `FindingDiscarded` (per-finding), `ReportOperatorAlert` (agent-side escalation), and `BatchConsolidated`. All carry `client_id` (+ `finding_id`/`report_id` where applicable). The passive audit-log listener records every reviewer decision (FR-021, SC-009). Operator-alert escalations log a `report.operator_alert` structured event (mirrors triage's `triage.operator_alert`).

**Rationale.** Constitution Engineering Standards — modules raise typed events; audit is a passive listener. Reuses the dispatcher (`app/core/dispatcher.py`).

**Alternatives considered.** Direct audit writes from the service — rejected: violates the decoupling-via-domain-events standard.

---

## Resolved unknowns summary

| Unknown | Resolution |
|---------|-----------|
| Agent framework integration | D1 — custom bounded `StateGraph` + LangChain chat model `.bind_tools()`, no MCP |
| How findings map to a watchlist batch | D2 — derive via `document_watchlists`, idempotent report-once claim |
| HITL across human think-time | D3 — persisted reports state machine; redraft = fresh graph run |
| Reports persistence | D4 — migration 0008: reports + report_findings + report_followups; widen findings/cadence |
| Reviewer-edit grounding scope | D5 — per-claim provenance in JSONB; gate scopes to drafted-grounded |
| Trigger mechanism | D6 — in-process commit-then-BackgroundTasks (expedited) + manual endpoint (batch) |
| Eval gates | D7 — tool-selection ≥0.85, grounding, injection; thresholds in eval_thresholds.yaml |
| Events/audit | D8 — reuse ReportApproved + add report lifecycle events; passive audit listener |
