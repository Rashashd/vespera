# READ FIRST — Implementation Notes (Spec 010 Frontend, anti-hallucination)

> **A weaker model will implement this spec cold.** Every claim below was verified against the live
> codebase on 2026-06-14 (branch `010-frontend`, off `master` @ spec 9 merged). Do **not** assume any
> API/field/import that is not pinned here. When in doubt, `grep` — don't invent.

---

## 0. Ground truth that bites if you guess

| You might assume… | Reality (verified) |
|---|---|
| `ReportStatus` has `sent`/`delivered` | **It does NOT.** `app/reports/enums.py`: `drafted, under_review, approved, rejected, discarded, needs_manual_revision`. `approved` is terminal. Delivery states = spec 13 (FR-006b). Render approved as **"Approved (pending delivery)"**. |
| `structured_fields` is a field-keyed object (Drug→…, Reaction→…) | **It is a LIST of claims**: `[{text, provenance, source_ref?}]` (`app/reports/schemas.py:Claim`). The PV fields live *inside* the claim texts + `draft_body`. Render the claim list + body; do NOT build a fixed field grid. |
| `ReportResponse` includes findings | **It does not.** Use the new findings endpoint (FR-031). |
| A claim's `source_ref` is a URL/DOI | **It is `str(chunks.id)`.** Verified in `app/agent/tools.py` (`_validate_chunk_refs` checks `Chunk.id`). Resolve via the passage endpoint (FR-029). |
| `corroboration_sources` is strongly typed | It's `list[dict]|null` on the wire. Each dict matches `app/rag/schemas.py:CorroborationSource`: `document_id, title, external_id, date, source_reliability, sources, passage_chunk_ids`. Parse defensively (Zod `.passthrough()`). |
| Reviewer routes can serve client-users | **No.** Queue/detail are `require_reviewer` (reviewer role only). FR-030 forbids widening them. Add separate portal routes. |
| Migration number | Latest on disk = `app/db/migrations/versions/0008_reports_and_followups.py`. **Your new migration is `0009`.** |
| Reports live under `alembic/versions/` | **No** — migrations are under `app/db/migrations/versions/`. |

## 1. Live API surface (spec 9) the SPA consumes — `app/reports/routes.py`

Prefix: `router = APIRouter(prefix="/clients/{client_id}", tags=["reports"])`.

- `GET /clients/{client_id}/reports?status=&limit=&offset=` → `list[ReportSummary]`, `require_reviewer`.
  Default (no `status`) returns only `{drafted, under_review, needs_manual_revision}`. Ordered
  `created_at desc`. `limit` 1–200 (default 50), `offset ≥ 0`. **(FR-006a tweak: add `status=all`.)**
- `GET /clients/{client_id}/reports/{report_id}` → `ReportResponse`, `require_reviewer`.
- `POST .../reports/{id}/approve` → `ReportSummary`.
- `POST .../reports/{id}/edit-approve` body `EditApproveRequest{draft_body, structured_fields:[Claim], comment}` → `ReportSummary`.
- `POST .../reports/{id}/reject` body `RejectRequest{comment (required, 1–2000)}` → `ReportSummary`.
- `POST .../reports/{id}/discard` body `DiscardRequest{reason?}` → `ReportSummary`.
- `POST .../reports/{id}/findings/{finding_id}/drop` → **204**.
- `POST .../reports/{id}/findings/{finding_id}/discard` body `FindingDiscardRequest{reason?}` → **204**.
- `POST .../findings/{finding_id}/draft` → re-trigger expedited draft (202 / 409 / 422). Admin/staff.

`ReportSummary` = `{id, client_id, report_type, status, corroboration_count, revision_count,
sla_deadline?, watchlist_id?, created_at, updated_at}`.
`ReportResponse` = summary minus nothing, plus `{structured_fields:[Claim], draft_body?,
corroboration_sources:[dict]?, reviewer_comments:[dict], cycle_period_start?, cycle_period_end?}`.

## 2. Auth — `app/auth/dependencies.py`

- `current_active_principal` — re-reads the user from DB (fresh authz, not token claims); for
  client-users also gates on client `status == "active"`.
- `require_reviewer = require_role(Role.REVIEWER)` — **reviewer role ONLY** (not staff-wide).
- `require_staff` — any staff role (manager/admin/reviewer), rejects client-users.
- `require_admin = require_role(MANAGER, ADMIN)`; `require_manager = MANAGER`.
- `acting_client(allow_suspended=False)` — loads `{client_id}` path param; **client-users get 404 on
  any client that isn't their own** (this is what makes a client-scoped route automatically safe for
  client-users). Use `acting_client(allow_suspended=True)` for read routes.

Login is the existing fastapi-users JWT route: `POST /auth/jwt/login` (rate-limited), returns a
bearer token. `Settings.auth_token_ttl_seconds = 28800` (~8h, no refresh token).

## 3. New backend files to ADD (do not rewrite existing files)

```
app/reports/passages.py        # GET /clients/{id}/passages/{chunk_id}  (FR-029)
app/reports/portal_routes.py   # portal report list/detail (FR-030) + report findings (FR-031)
app/reports/metrics_routes.py  # GET /clients/{id}/metrics ops dashboard (FR-021a; delivery fields null/"pending")
app/reports/schemas.py         # ADD: PassageResponse, PortalReportSummary, ReportFindingDetail, OpsDashboard
app/reports/routes.py          # EDIT: allow status=all in list_reports (FR-006a)
app/observability/__init__.py
app/observability/models.py    # LlmUsage  (table llm_usage)
app/observability/schemas.py   # UsageRecord, CostDashboard aggregate
app/observability/pricing.py   # tokens -> Decimal cost from Settings
app/observability/usage.py     # record_usage(...) best-effort writer
app/observability/tracing.py   # configure_tracing(settings) + traceable wrapper for triage
app/observability/routes.py    # GET /clients/{id}/usage  (FR-021/034)
app/agent/graph.py             # EDIT: capture input/output tokens -> record_usage (call_site="agent")
app/triage/llm.py              # EDIT: wrap _call_llm with tracing + record_usage (call_site="triage")
app/core/config.py             # EDIT: langsmith_api_key (optional secret) + pricing/tracing settings
app/db/migrations/versions/0009_llm_usage.py
app/main.py                    # EDIT: include_router for passages, portal, metrics, usage routers
```

Each new file: one-sentence module docstring, ≤ ~300 lines, fully `async`, Pydantic at the boundary
(never return ORM objects). Follow `app/reports/` for style.

## 4. Passage resolution (FR-029) — exact mechanism

- `Chunk` is `app/embedding/models.py:Chunk` — has `id, client_id, document_id, text, section,
  source_reliability, date`.
- Endpoint: `GET /clients/{client_id}/passages/{chunk_id}` → `PassageResponse{chunk_id, text,
  section?, source_reliability, date?, document_id, title?, external_id?}`.
- Query: `select(Chunk).where(Chunk.id == chunk_id, Chunk.client_id == client.id)`; join `documents`
  for `title`/`external_id` (confirm column names in `app/ingestion/models.py` before writing).
- 404 `{detail:"PASSAGE_UNAVAILABLE"}` when missing/not this client's — the UI shows citation
  metadata + "passage unavailable" (FR-010 edge case). Guard: `acting_client(allow_suspended=True)`.

## 5. Cost capture (FR-032/033) — exact token sources

- **Agent** (`app/agent/graph.py:agent_node`): already reads `response.usage_metadata`. That dict has
  `input_tokens`, `output_tokens`, `total_tokens`. Call `record_usage(call_site="agent", ...)` with
  client_id/finding_id from the closure (`client.id`, `finding.id`).
- **Triage** (`app/triage/llm.py:_call_llm`): the raw provider JSON carries usage — Anthropic:
  `resp.json()["usage"]["input_tokens"|"output_tokens"]`; OpenAI:
  `resp.json()["usage"]["prompt_tokens"|"completion_tokens"]`. `_call_llm` currently returns only the
  text — extend it (or the callers `resolve_yes_no`/`assess_valence`, which already have `client_id`,
  `document_id`, `settings`) to also record usage. Triage has no `finding_id` at call time → pass
  `finding_id=None`.
- `record_usage()` MUST wrap its DB write in try/except and log+swallow on failure (FR-033). It needs
  a session — both call sites already have one (`session`/`app_state`); pass it in. Do not open a new
  engine.

## 6. Tracing setup (FR-032) — degrade gracefully

- In startup (after Vault load), if `settings.langsmith_api_key` is non-empty, set env
  `LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_API_KEY=<key>`, `LANGCHAIN_PROJECT=settings.langsmith_project`.
  Empty key ⇒ **do nothing**, app boots normally (tracing disabled).
- Agent traces automatically (LangChain chat models). Triage: decorate with `langsmith.traceable`
  (import lazily so a missing/disabled langsmith never breaks the call path).
- Add `langsmith` to `[project].dependencies` in `pyproject.toml` (main group). Do **not** add the key
  to `_REQUIRED_SECRETS` (optional secret → no ci.yml inline-secret change needed).
- Tag traces with `client_id`/`finding_id`; never include prompt/response PII in tags (FR-035).

## 7. Config additions (FR-035) — `app/core/config.py`

```python
# secret (optional; empty disables tracing) — from Vault, NOT in _REQUIRED_SECRETS
langsmith_api_key: str = ""
# non-secret tracing/pricing config
langsmith_project: str = "pantera"
# per-1K-token prices in USD, keyed by pinned model id (state unit+currency here)
llm_price_per_1k_input_usd: dict[str, float] = {...}   # e.g. {anthropic_model: 0.003, openai_model: 0.0025}
llm_price_per_1k_output_usd: dict[str, float] = {...}
```
(Confirm `dict` default works under `extra="forbid"`; if a dict default is awkward, use two
flat fields per provider — e.g. `anthropic_price_in_usd_per_1k`. Keep unit + currency in the name.)

## 8. Router wiring — `app/main.py`

After the existing `app.include_router(reports_router)` (line ~41) add the new routers
(passages, portal, metrics, usage). Match the existing one-line-comment convention.

## 9. Frontend ground rules

- The SPA is a **pure API client**. Never trust UI role-gating as security — the API enforces the
  per-client wall. UI hiding is FR-004/027 defense-in-depth only.
- Queue ordering (expedited-first, SLA-asc, created_at tie-break) + SLA countdown are **client-side**
  (FR-007/R9) — the backend returns `created_at desc`.
- Citations: render **all N** (`corroboration_sources`), each openable → fetch passage on click.
- Acting-client switcher (staff) persists in `localStorage`; client-users have none.
- Token in `localStorage`; on any 401 → clear + route to sign-in.

## 10. Tests / gates

- Frontend: Vitest + RTL (+ MSW) for every primary surface; one Playwright e2e (reviewer
  approve/reject). Backend: pytest under existing gates (80% overall, **95% HITL** — the new
  reviewer-adjacent reads/usage capture count). Extend the fresh-clone smoke test to
  `npm ci && npm run build` + serve.
- Run both linters on any backend change: `uv run ruff check` **and** `uv run black --check app`.
