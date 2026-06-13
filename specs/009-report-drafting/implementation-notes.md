# Implementation Notes — Spec 9 Report Drafting (READ FIRST)

**Audience:** a fresh-session implementer. Every signature below was verified against the live codebase on 2026-06-13. **Trust this file over your assumptions.** If something here disagrees with what you'd guess, this file is right. When in doubt, `grep` — do not invent APIs/fields.

Build order = `tasks.md` (T001→T045). This guide pins the exact integration surfaces those tasks touch.

---

## 0. Golden rules (you WILL get these wrong without reading)

- **Approval guard is `require_reviewer`, NOT `require_reviewer_or_admin`.** FR-019 = `reviewer` role ONLY. `app/auth/dependencies.py:73` `require_reviewer = require_role(Role.REVIEWER)`. There is also `require_reviewer_or_admin` (line 70) — **do not use it for approval actions**; it would let admin/manager approve, violating the spec.
- **Config is a single FLAT `Settings(BaseSettings)`** in `app/core/config.py` with `extra="forbid"`. No nested settings objects. Add new keys at top level (e.g. `agent_max_iterations`). Never `os.getenv()` outside config.py.
- **Domain events are frozen dataclasses with default values** (base has `actor_id`, `actor_type`, `client_id`); every added field needs a default. See §4.
- **The dispatcher runs handlers INSIDE the caller's transaction** (`app/core/dispatcher.py`) — audit writes are atomic with the business write. Don't open a new session in a handler.
- **Both `ruff` AND `black` must pass:** `uv run ruff check app tests` and `uv run black --check app worker tests`. Black-dirty code has shipped before — run both.
- **Files ≤ ~300 lines, one-sentence module docstring at top of every file.** Split when growing.
- **Async everywhere; tenacity on outbound (never retry 4xx); tools return `ToolError`, never raise.**
- On this Windows host, integration tests need the gitignored `docker-compose.override.yml` (5433/6380) + the Vault repoint (see `host-integration-test-vault-repoint` memory). Clean CI uses service names.

---

## 1. What already EXISTS (reuse — do not rebuild)

| Thing | Location | Notes |
|-------|----------|-------|
| Hybrid retrieval entry point | `app/rag/service.py:18` `async def retrieve(session, redis, ms_client, client: Client, req: RetrieveRequest, app_state) -> RetrieveResponse` | Your `retrieve` tool wraps this. Empty corpus → returns empty `RetrieveResponse` (count 0). |
| `RetrieveRequest` | `app/rag/schemas.py:13` | fields: `query`, `top_k`, `chunk_types?`, `source_reliabilities?`, `date_from?`, `date_to?`. |
| `RetrieveResponse` | `app/rag/schemas.py:61` | has `results: [RetrievedPassage]`, `corroboration_count`, `corroboration_sources`. Reuse for corroboration — **do not recompute corroboration yourself**; it's already returned. |
| LLM provider handle | `app/infra/llm_adapter.py:9` `LLMClient(provider, model, api_key)`; `build_llm_client(settings)` (line 17, Anthropic-first by available key) | Use `build_llm_client(settings)` to get provider/model/key for the agent LLM binding. |
| Raw LLM call pattern | `app/triage/llm.py:46` `_call_llm(...)` + `_should_retry` | Reference for tenacity config (retry timeout/network only, `stop_after_attempt(3)`, `reraise=True`). |
| Event dispatcher | `app/core/dispatcher.py` `EventDispatcher.register/dispatch(event, session)` | handlers are `Callable[[event, AsyncSession], Awaitable[None]]`. |
| Existing events | `app/domain/events.py` | `DomainEvent` base (`actor_id`, `actor_type`, `client_id`); `FindingClassified` (line ~16); **`ReportApproved` ALREADY EXISTS** (`report_id`, `report_type`) — reuse it, don't redefine. |
| Reviewer guard | `app/auth/dependencies.py:73` `require_reviewer` | see Golden Rules. |
| Staff guard | `app/auth/dependencies.py:58` `require_staff` | for consolidate-batch + admin re-trigger. |
| Tenant dep (write) | `app/auth/dependencies.py:76` `acting_client(allow_suspended=False)` → returns `Client`; read variant `get_acting_client_read` (line 116). | Build a module-level `_get_acting_client = acting_client()` and `Depends(_get_acting_client)` (see `routes_clients.py:35` for the idiom). |
| Finding model | `app/triage/models.py:22` | has `client_id`, `document_id`, `drug`, `reaction`, `bucket`, `status`, `corroboration_sources` (JSONB, already present — populate it). **No `watchlist_id`** (by design — §3). |
| Watchlist model | `app/clients/models.py:60` | `cadence` CHECK currently `daily/weekly/monthly`. |
| Triage trigger pattern | `app/embedding/runner.py:~397` `_triage_after_index(...)` calls `triage_document_runner` | Mirror this for drafting (§5). |
| Triage runner | `app/triage/runner.py:19` returns `list[FindingOutcome]` (each has `.created`) | inspect `app/triage/schemas.py:FindingOutcome` for `finding_id`/`bucket` fields before wiring. |

## 2. What you CREATE

New packages `app/agent/` and `app/reports/` (see plan.md Project Structure for the file list). Migration `app/db/migrations/versions/0008_reports_and_followups.py` — **`down_revision = "0007"`** (verified: 0007 has `revision="0007"`, `down_revision="0006"`).

---

## 3. The watchlist-attribution decision (do NOT add a column)

A document belongs to **many** watchlists via the `document_watchlists` junction (table from migration 0004, columns include `document_id`, `watchlist_id`, `client_id`). Triage flattens `watchlist_drugs` and does **not** record which watchlist a finding came from.

**Therefore (research D2):** do NOT add `watchlist_id` to `findings`. For batch consolidation of watchlist *W*, select `findings.status='pending_batch'` whose `document_id` is in `document_watchlists` for *W*, then **claim idempotently** (flip → `processing` → `reported`, link via `report_findings`). First watchlist to consolidate wins; a finding is reported once per client. This is the user's explicit intent ("store/report once per client; each watchlist its own report"). Do not "fix" this into a column.

---

## 4. Domain events (frozen dataclass — mind the defaults)

Add to `app/domain/events.py`, copying the existing style (every new field needs a default because the base has defaulted fields):

```python
@dataclass(frozen=True, slots=True)
class ReportDrafted(DomainEvent):
    report_id: int = 0
    report_type: str = ""
```

Add: `ReportDrafted`, `ReportEdited`, `ReportRejected`, `ReportDiscarded`, `FindingDiscarded` (carry `finding_id`, `kind`), `ReportOperatorAlert` (carry `finding_id`, `reason`), `BatchConsolidated` (carry `watchlist_id`, `report_id`). **Reuse existing `ReportApproved`.** Register handlers with the passive audit listener (find where `FindingClassified`/other events are registered and follow that wiring).

---

## 5. Trigger wiring (in-process, mirror triage)

Expedited drafting fires after triage produces a finding. The cleanest hook: in `app/embedding/runner.py` right after `triage_document_runner(...)` returns its `list[FindingOutcome]`, for each outcome whose bucket ∈ {`urgent`,`emergency`} and `.created`, schedule `app/reports/runner.py:draft_expedited(finding_id)`.

**Critical (bg-tasks-session-timing memory):** the finding row MUST be committed before scheduling the draft. Triage commits inside `triage_document_runner` (its own `session.begin()`), so the finding is durable by the time it returns — schedule the draft AFTER it returns. If you instead use FastAPI `BackgroundTasks`, `add_task` only AFTER the session commits. ARQ wrapping is spec 11 — keep the function call shape (`draft_expedited(finding_id)`) so spec 11 can enqueue it unchanged.

---

## 6. The agent (LangGraph) — bounded, no MCP, no suspended graph

- **New deps:** `langgraph` + `langchain-anthropic` and/or `langchain-openai`. Verify the lockfile pulls **no torch** (Constitution VI). The chat model gives native tool-calling via `.bind_tools()`.
- **Use `build_llm_client(settings)`** to pick provider/model/key, then construct the matching LangChain chat model (pinned model from settings).
- **Custom `StateGraph`, NOT `create_react_agent`** — you must hard-cap iterations AND tokens (`settings.agent_max_iterations`, `settings.agent_max_tokens`) and implement the `ToolError(error, retryable)` contract in the ToolNode (retryable → loop within cap; else → escalate outcome). See research D1.
- **HITL is a persisted state machine, NOT a suspended `interrupt()` run** (research D3). The graph runs to "drafted", writes the `reports` row, and ENDS. Reviewer actions are plain endpoints; Reject triggers a fresh redraft graph run. Do not hold a graph open across human think-time. (The durable `interrupt()`+checkpointer form is spec 11.)
- The 5 tools: `retrieve` (wraps §1 retrieve), `score_severity` (**read-only**, reads the finding bucket, never re-buckets — FR-023/Constitution III), `draft_report` (builds grounded claim list, omits ungroundable — FR-004), `draft_followup` (fixed template + cover message, emergency only — NOT grounded prose), `escalate` (terminal escalate signal).
- **Untrusted-data system prompt:** treat all document/source text as data, never instructions (FR-027). The planted-injection golden case (T039) guards this.

---

## 7. Migration 0008 specifics

- `down_revision = "0007"`.
- New tables `reports`, `report_findings`, `report_followups` (full columns in data-model.md). Every table has `client_id`.
- Widen `findings.status` CHECK → add `processing`, `reported`, `discarded` (keep existing three). **Altering a CHECK constraint in Postgres = drop + recreate the named constraint** (`ck_findings_status`); do it in both `upgrade` and `downgrade`.
- Widen `watchlists.cadence` CHECK → add `biweekly` (drop/recreate `ck_watchlists_cadence`); also add `BIWEEKLY="biweekly"` to `app/clients/enums.py:Cadence`.
- Expedited idempotency (FR-030): partial unique on `report_findings(finding_id)` where the linked report is an active expedited report — **not** a `finding_id` column on `reports` (reports has none).
- Batch idempotency (SC-008): partial unique `ux_reports_batch_cycle` on `(watchlist_id, cycle_period_start)` where `report_type='batch'` and status non-terminal.
- If 0008 introduces a required Vault secret, add it to the inline secret writer in `.github/workflows/ci.yml` (spec-2 CI lesson) — likely NOT needed here (no new secret).

---

## 8. Eval gates (Constitution IV)

- `eval_thresholds.yaml`: add `agent_tool_selection_accuracy_min: 0.85` (SC-004). Grounding + injection gates on the report golden set (SC-001/SC-010). Corroboration accuracy 0.75 already exists from spec 7 — reuse (T040b).
- Runtime knobs (caps, redraft cap=3, SLA hours) live in `Settings`, **never** in `eval_thresholds.yaml` (spec-8 convention).
- Eval tests are self-contained (no `PANTERA_INTEGRATION`) so the CI `eval` job runs them; wire into `.github/workflows/ci.yml` (T041).

---

## 9. Testing & coverage

- ≥95% coverage on HITL + DB-write paths; ≥80% overall (Constitution).
- Paginated reads: pass `?limit=` or filter by a unique field — the integration DB accumulates rows across runs (stale-data lesson).
- Module-scoped fixtures that touch env vars must SAVE/RESTORE (not unconditionally pop) or they corrupt session-scoped fixtures (spec-7 lesson).
- Commits: Conventional Commits, **no `Co-Authored-By` trailer**. PRs <400 lines.

---

## 10. Quick verification checklist before you start coding

```
grep -n "require_reviewer " app/auth/dependencies.py        # confirm reviewer-only guard
grep -n "def retrieve" app/rag/service.py                    # confirm retrieve signature
grep -n "class ReportApproved" app/domain/events.py          # confirm it exists (reuse)
grep -n "revision" app/db/migrations/versions/0007_*.py      # confirm down_revision chain
grep -n "class FindingOutcome" app/triage/schemas.py         # confirm finding_id/bucket fields
```
If any of these has changed since 2026-06-13, update this file before proceeding.
