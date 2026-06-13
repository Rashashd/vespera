---
description: "Task list for spec 9 — Report Drafting (Bounded Agent + HITL)"
---

# Tasks: Report Drafting (Bounded Agent + Human-in-the-Loop)

**Input**: Design documents from `specs/009-report-drafting/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

> **READ FIRST before implementing any task:** `specs/009-report-drafting/implementation-notes.md` (T001 authors it). It pins exact signatures/fields verified against the live codebase. A fresh-session implementer WILL hallucinate APIs without it.

**Tests**: Included — the constitution mandates CI eval gates (tool-selection, grounding, injection) and each user story has Independent Test criteria.

## Format: `[ID] [P?] [Story] Description`
- **[P]**: parallelizable (different files, no incomplete dependency)
- **[Story]**: US1–US4 for story phases only

---

## Phase 1: Setup (Shared Infrastructure)

- [ ] T001 Author `specs/009-report-drafting/implementation-notes.md` — verify against live code: `app.rag.service.retrieve` signature, `app/triage/llm.py` `_call_llm`/provider-branch + `LLMClient`, `app/core/dispatcher.py` dispatch, `app/domain/events.py` (existing `ReportApproved`/`FindingClassified`), `acting_client()` location, `Finding`/`Watchlist` models, `document_watchlists` columns, alembic `0007` down_revision chain, BackgroundTasks commit-before-add_task pattern. Pin every signature with file:line.
- [ ] T002 Add dependencies via `uv`: `langgraph`, and provider chat adapter(s) `langchain-anthropic` / `langchain-openai` (verify NO torch pulled — Constitution VI). Update `pyproject.toml` + lockfile.
- [ ] T003 [P] Create package skeletons with module docstrings: `app/agent/__init__.py`, `app/reports/__init__.py`, and `app/agent/prompts/` dir.
- [ ] T004 [P] Add agent/report settings to `app/core/config.py` flat `Settings`: `agent_max_iterations=8`, `agent_max_tokens=8000`, `agent_llm_max_tokens=2048`, `report_redraft_cap=3`, `expedited_sla_hours=24` (extra="forbid").
- [ ] T005 [P] Add eval thresholds to `eval_thresholds.yaml`: `agent_tool_selection_accuracy_min: 0.85`; report grounding gate key; reuse corroboration `0.75`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Blocks all user stories. Complete before Phase 3.**

- [ ] T006 Add `BIWEEKLY = "biweekly"` to `Cadence` in `app/clients/enums.py`.
- [ ] T007 Write migration `app/db/migrations/versions/0008_reports_and_followups.py` (down_revision `0007`): create `reports`, `report_findings`, `report_followups` (per data-model.md); widen `findings.status` CHECK (+`processing`,`reported`,`discarded`); widen `watchlists.cadence` CHECK (+`biweekly`); all indexes incl. partial uniques `ux_reports_batch_cycle`, `ux_report_findings_unique`, `ux_report_followups_finding`. Include downgrade.
- [ ] T008 [P] ORM models in `app/reports/models.py`: `Report`, `ReportFinding`, `ReportFollowup` (match 0008; `client_id` on all).
- [ ] T009 [P] Enums in `app/reports/enums.py`: `ReportType`, `ReportStatus`, `ClaimProvenance`, `FindingReportState`.
- [ ] T010 [P] Pydantic schemas in `app/reports/schemas.py`: `ReportResponse`, `ReportSummary`, reviewer action bodies (reject comment, edit payload) — no ORM leakage.
- [ ] T011 Add domain events to `app/domain/events.py`: `ReportDrafted`, `ReportEdited`, `ReportRejected`, `ReportDiscarded`, `FindingDiscarded`, `ReportOperatorAlert`, `BatchConsolidated` (reuse existing `ReportApproved`); register in passive audit listener.
- [ ] T012 LLM binding in `app/agent/llm_binding.py`: provider-pinned LangChain chat model from `settings.preferred_provider`/pinned model, `.bind_tools()`; tenacity on transport errors (never 4xx), reusing the `app/triage/llm.py` posture.
- [ ] T013 Agent state + bounded graph scaffold in `app/agent/state.py` + `app/agent/graph.py`: TypedDict state with `iterations_used`/`tokens_used`; `StateGraph` loop (LLM→ToolNode→guard); cap-exceeded edge → escalate outcome. No tool bodies yet.
- [ ] T014 Tool contract + `ToolError(error, retryable)` plumbing in `app/agent/tools.py`: register the 5 tool stubs with Pydantic input schemas; ToolNode catches → ToolError (never raises).

**Checkpoint:** migration applies, models import, empty graph runs and returns an escalate outcome.

---

## Phase 3: User Story 1 — Expedited grounded draft (P1) 🎯 MVP

**Goal:** an `urgent`/`emergency` finding becomes a grounded, structured expedited report in `drafted` status.
**Independent test:** seed an emergency finding w/ 3 corroborating papers → draft → report with corroboration_count=3, all sources listed, every drafted claim has a resolvable source_ref, SLA set.

- [ ] T015 [US1] Implement `retrieve` tool in `app/agent/tools.py` wrapping `app.rag.service.retrieve` (client-scoped, client-wide corpus); map empty corpus → ToolError(retryable=False) for escalation.
- [ ] T016 [US1] Implement `score_severity` tool (read/confirm-only) — reads finding bucket, surfaces into structured fields; never re-buckets (FR-023).
- [ ] T017 [US1] Implement `draft_report` tool: build structured_fields claim-list with `drafted_grounded` provenance + per-claim source_ref; omit ungroundable claims (FR-004); compute corroboration via grouped distinct sources (FR-007/008/009). Prompts in `app/agent/prompts/` (untrusted-data system prompt + draft).
- [ ] T018 [US1] Report drafting service in `app/reports/service.py`: persist `Report`(expedited)+`ReportFinding`, set `sla_deadline` from settings, idempotent per finding (FR-030 incl. terminal-no-resurrect), emit `ReportDrafted`.
- [ ] T019 [US1] In-process trigger `app/reports/runner.py:draft_expedited(finding_id)` + wire into the triage finding path (commit-then-`BackgroundTasks.add_task`, per bg-tasks memory).
- [ ] T020 [US1] Optional admin re-trigger route `POST /clients/{id}/findings/{fid}/draft` in `app/reports/routes.py` (staff guard, acting_client, 409 on terminal finding).
- [ ] T021 [P] [US1] Unit tests: grounding omission, corroboration count, idempotency, score_severity read-only (`tests/unit/test_expedited_drafting.py`).
- [ ] T022 [US1] Integration test: full expedited draft against live stack (`tests/integration/test_expedited_report.py`, quickstart Scenario 1).

**Checkpoint:** US1 independently demoable — emergency finding → grounded drafted report.

---

## Phase 4: User Story 2 — Mandatory reviewer approval gate (P2)

**Goal:** reviewer-only Approve / Edit→Approve / Reject(×3)→escalate / Discard over US1 drafts.
**Independent test:** seed a drafted report → exercise each action as `reviewer`; non-reviewer refused.

- [ ] T023 [US2] HITL state machine in `app/reports/service.py`: transitions per data-model state diagram; optimistic status check (409 on concurrent/stale).
- [ ] T024 [US2] Reviewer routes in `app/reports/routes.py` (reviewer-only guard + acting_client): `approve`, `edit-approve` (edits→`reviewer_attested`, no grounding block), `reject` (redraft run via fresh graph invocation, `revision_count++`, comment history; 4th → `needs_manual_revision`), `discard`. Emit events.
- [ ] T025 [P] [US2] Reviewer queue read routes: `GET /clients/{id}/reports?status=...` (drafts-only, excludes followups/alerts) + `GET .../reports/{rid}` (full citation set, all N sources — FR-020). Paginate (`?limit=`).
- [ ] T026 [US2] Redraft path: `redraft_report(report_id, comment)` re-invokes bounded graph seeded with prior draft + comment; cap at `report_redraft_cap`.
- [ ] T027 [P] [US2] Unit tests: state machine transitions, redraft cap → escalate, role refusal, edit provenance (`tests/unit/test_hitl_state_machine.py`).
- [ ] T028 [US2] Integration test: each reviewer action + audit event assertions + non-reviewer 403 (`tests/integration/test_reviewer_actions.py`, quickstart Scenario 3).

**Checkpoint:** US1+US2 = draft → human approval gate working end-to-end.

---

## Phase 5: User Story 3 — Consolidated batch per watchlist (P3)

**Goal:** one batch report per watchlist cycle; per-finding drop/discard; empty→no report.
**Independent test:** seed 5 minor+2 positive for watchlist W → consolidate → one batch; drop/discard work; re-run idempotent.

- [ ] T029 [US3] Consolidation grouping in `app/reports/consolidation.py`: select `pending_batch` findings via `document_watchlists(W)` join (research D2); idempotent claim → `processing`→`reported` + `report_findings`; skip if none (FR-013).
- [ ] T030 [US3] Batch report builder in `app/reports/service.py`: exec summary + positive section + minor section grouped by reaction + per-finding detail with full sources (FR-012); one `Report`(batch) w/ watchlist_id + cycle_period; emit `BatchConsolidated`+`ReportDrafted`; idempotent via `ux_reports_batch_cycle`.
- [ ] T031 [US3] Consolidate endpoint `POST /clients/{id}/watchlists/{wid}/consolidate-batch` (staff guard); 201 report / 204 none.
- [ ] T032 [US3] Per-finding actions in `app/reports/routes.py`: `.../findings/{fid}/drop` (→`pending_batch`) and `.../findings/{fid}/discard` (→terminal `discarded`); emit `FindingDiscarded`; auto-discard report when last included finding removed (FR-013a).
- [ ] T033 [P] [US3] Unit tests: grouping via junction, first-watchlist-wins claim, drop vs discard semantics, empty→auto-discard, idempotency (`tests/unit/test_batch_consolidation.py`).
- [ ] T034 [US3] Integration test: batch consolidation + per-finding removal + isolation across two clients (`tests/integration/test_batch_report.py`, quickstart Scenario 4 & 6a).

**Checkpoint:** all three report flows working; reviewer queue holds expedited + batch.

---

## Phase 6: User Story 4 — Bounded agent safety & follow-up (P4)

**Goal:** caps→escalate, ToolError fail-soft, operator alerts, emergency follow-up artifact; eval gate.
**Independent test:** ungroundable finding→operator alert (no queue item); forced tool failure→no crash; emergency→follow-up artifact; tool-selection golden set ≥0.85.

- [ ] T035 [US4] Wire escalation outcomes in `app/agent/graph.py` + `app/reports/runner.py`: ungroundable / loop-cap / token-cap / non-retryable tool failure → `ReportOperatorAlert` + `report.operator_alert` structured log; NO reviewer-queue row (FR-025/026).
- [ ] T036 [US4] Implement `draft_followup` tool + `app/reports/service.py` persistence: fixed template_ref + auto cover_message summarizing finding; create `report_followups` for `emergency` only; linked to finding+expedited report; NOT in reviewer queue (FR-006).
- [ ] T037 [US4] Implement `escalate` tool (returns terminal escalate signal) and confirm all 5 tools honor `ToolError` contract (never raise).
- [ ] T038 [P] [US4] Author `tests/data/agent_tool_selection_golden.jsonl` (≥15 examples incl. correct-none cases) + `tests/integration/test_agent_tool_selection.py` (accuracy ≥0.85, self-contained eval).
- [ ] T039 [P] [US4] Author `tests/data/report_grounding_golden.jsonl` incl. a planted-injection case; `tests/integration/test_report_grounding.py` (grounding gate SC-001 + injection SC-010).
- [ ] T040 [US4] Integration test: operator-alert paths + emergency follow-up artifact (`tests/integration/test_agent_safety.py`, quickstart Scenarios 2 & 5).
- [ ] T040a [P] [US4] Redaction/logging assertion in `tests/unit/test_report_logging.py`: assert structlog binds `client_id` + `finding_id` and never emits PII or secrets in the drafting/agent/report paths (FR-031); covers the "IDs only" posture (full Presidio deferred to spec 12).
- [ ] T040b [P] [US4] Corroboration-accuracy eval in `tests/integration/test_report_corroboration.py`: assert report corroboration count + listed sources match distinct corroborating docs ≥ 0.75 on the report golden set (SC-003), reusing the spec-7 corroboration harness.

**Checkpoint:** all user stories complete; safety substrate proven.

---

## Phase 7: Polish & Cross-Cutting

- [ ] T041 Wire the new eval tests into the CI `eval` job (`.github/workflows/ci.yml`); if 0008 adds a required Vault secret, add it to the inline secret writer (spec-2 CI lesson). Ensure `lfs: true` unaffected.
- [ ] T042 [P] Coverage pass: ≥95% on HITL + DB-write paths (Constitution testing gate); ≥80% overall.
- [ ] T043 [P] Lint/format gate: `uv run ruff check app tests` AND `uv run black --check app worker tests` clean.
- [ ] T044 [P] Docs: short runbook `docs/` for report drafting + reviewer actions; update `implementation-notes.md` with any drift found during implementation.
- [ ] T045 Run full quickstart validation (Scenarios 1–6) against live stack; record results.

---

## Dependencies & Execution Order

- **Setup (P1)** → **Foundational (P2)** → user stories.
- **US1 (P3)** depends on Foundational. **MVP = Setup + Foundational + US1.**
- **US2 (P4)** depends on US1 (needs drafts to review).
- **US3 (P5)** depends on Foundational + US1 drafting tooling (reuses agent); independent of US2.
- **US4 (P6)** hardens across US1–US3 (caps/escalation/follow-up/eval); do after the happy paths exist.
- **Polish (P7)** last.

**Parallel opportunities:** T003/T004/T005 (setup); T008/T009/T010 (models/enums/schemas); within stories the `[P]` test-authoring tasks (T021, T027, T033, T038, T039) run alongside impl of sibling files.

## Implementation Strategy

1. **MVP first:** Phases 1–3 (Setup → Foundational → US1) → demoable grounded expedited draft.
2. **Add the gate:** Phase 4 (US2) → the regulatory HITL spine.
3. **Add batch:** Phase 5 (US3).
4. **Harden:** Phase 6 (US4) + Phase 7 eval/CI — required before merge (Constitution IV gates).
