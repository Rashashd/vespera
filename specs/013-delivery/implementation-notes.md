# Implementation Notes — Spec 013 Delivery (READ FIRST)

> A weaker model implements this spec cold in a fresh session and WILL hallucinate APIs/fields that don't
> exist. Every anchor below was verified against the live codebase on 2026-06-17. **Grep before you assume.**
> Read this → then `plan.md` → `data-model.md` → `contracts/delivery-api.md`. Line numbers drift — confirm
> the symbol, not the exact line.

## 0. Golden rules (project standing)

- `uv run` everything. BOTH `ruff check` AND `black --check app worker tests` must pass.
- Conventional Commits, **NO `Co-Authored-By`** trailer. PRs < 400 lines (split per user story).
- async everywhere; `httpx.AsyncClient`; `tenacity` (3 attempts, **never retry 4xx**) on every external call; never `requests`/`time.sleep`.
- `structlog` JSON, **PII-free** — scrub `error`/`reason` via `app/redaction` before logging. No `print`.
- No `os.getenv` outside `app/core/config.py`. New config → `Settings` (`extra="forbid"`).
- New files ≤ ~300 lines (split `app/delivery/` per the module list in plan.md). One-sentence module docstring.
- Domain-event decoupling: delivery/notifications are **passive handlers / durable jobs**, never direct cross-module calls.
- Coverage gate: ≥80% overall, **≥95%** on delivery DB-writes + the callback/HITL-adjacent paths.

## 1. DO NOT REBUILD — these already exist (verified)

| Thing | Location | Note |
|-------|----------|------|
| Approval dispatches `ReportApproved` | `app/reports/review.py:33-63` (event at :53-62); route `app/reports/routes.py:94-111` | Your delivery trigger. No consumer today beyond audit. |
| In-process dispatcher | `app/core/dispatcher.py:13-26`; register at `app/core/lifespan.py:71-72`; example handler `app/audit/handler.py:31-49` | `Handler = (event, AsyncSession) -> Awaitable[None]`, runs in caller's txn. |
| `ReportApproved` event | `app/domain/events.py:27-32` | fields: actor_id, actor_type, client_id, report_id, report_type. |
| Portal delivery wiring | `app/reports/portal_routes.py` — `_PORTAL_STATUSES={"approved","sent","delivered"}` (:30), `_delivery_status()` (:56-62); `delivery_status` field `app/reports/schemas.py:154` | Built to light up; extend `_delivery_status` for `delivery_failed`. |
| Metrics endpoint | `app/reports/metrics_routes.py:32-104` (`delivery=None` at :101); `OpsDashboard` `app/observability/schemas.py:51-62` | Add `DeliveryMetrics`; populate `delivery`. |
| Client suspend/reactivate | `app/clients/accounts.py` set_client_status:61-66, suspend_client:69-71, reactivate_client:74-76 | **status-only flip** — do NOT add watchlist mutation (D5). |
| Cadence loop already gates on client status | `app/scheduling/service.py` `query_due_watchlists` :157-251, filters `Client.status=="active"` (:181) AND `Watchlist.is_active` (:182); scheduler `app/jobs/scheduler.py:21` | Suspension already stops cycles → no `is_active` flip / no tracking. |
| Staff CRUD endpoints | `app/auth/routes_staff.py` POST:19-66 (`require_manager`:23, `password_helper.hash`:44), GET:69-86, PATCH:89-146 (last-manager guard :108/:128) | US4 is FRONTEND wiring; backend exists. |
| Client-user CRUD endpoints | `app/clients/routes_client_users.py` POST:23-87 (`require_admin`:32, hash:61), GET:90-99, PATCH:102-170 | schemas `ClientUserCreate/Update` (scope, min_severity, watchlist_ids). |
| Budget event | `WatchlistBudgetThresholdReached` `app/domain/events.py:292-298`, raised `app/scheduling/budget_policy.py:45-54` (`state` = warning/soft_capped) | US6 = passive handler; event already fires on crossing (dedup inherent). |
| Dead-letter | model `app/scheduling/models.py:77-106`; `GET /admin/dead-letters` + resolve `app/scheduling/routes.py:120-156`; `failed_jobs` on metrics | US7 card = frontend only. |
| Audit view | model `app/audit/models.py:15-43` (RLS-EXEMPT, append-only); handler `app/audit/handler.py:31-49`; `GET /audit` `app/audit/routes.py:26-54` (staff-only, categories reports\|findings\|clients\|jobs, excludes auth) | US5 = refine authz + ADD export; the VIEW exists. |
| Redaction | `app/redaction/redactor.py` `redact`:66-83 / `redact_async`:86-96; `scrub_text` `app/redaction/recognizers.py:84-90` | Use `scrub_text` (regex, loop-safe) for log/error values. |
| Tracing helper + decorator | `app/observability/tracing.py` `configure_tracing`:31-49 (sets `LANGCHAIN_TRACING_V2`/`_API_KEY`/`_PROJECT`), `traced_llm_call`:52-73, `_SAFE_INPUT_KEYS=("client_id","max_tokens")`:28 | API calls it at `app/core/lifespan.py:61-64`; triage decorated `app/triage/llm.py:44`. |
| Durable enqueue | `app/jobs/enqueue.py:21-94` — `enqueue(name, *, job_id, app_state=None, _ctx=None, **kwargs)`; usage `app/jobs/tasks.py:441-449`; inline mode `jobs_inline` | Deterministic `job_id` = idempotent. |
| Worker cron registration | `worker/worker.py` startup:18-39 (`ctx["settings"]=settings`:23, `install_system_rls`:26), `_cron_jobs`/`cron_jobs`:71-94, `_arq_cron(fn, hour=, minute=)`; `scheduler_tick` `app/jobs/scheduler.py:14-51` | Add the sweep cron here. |
| RLS plumbing | `app/db/rls.py` set_rls_context:19-31, set_system_context, install_system_rls:34-47; API per-principal `app/auth/dependencies.py:44-48`; test harness `tests/integration/conftest.py:18,28` | New client-scoped table needs a policy (see §3). |
| Frontend `DeliveryStatusChip` (all 4 states) | `frontend/src/components/DeliveryStatusChip.tsx:1-37`; used `pages/AllReports.tsx:55`, `components/ReportDetail.tsx:87`, `pages/WatchlistPage.tsx:57-60` | Lights up when reviewer schemas carry `delivery_status`. |
| Frontend budget-policy control | `frontend/src/components/admin/WatchlistEditor.tsx:170-184` | **FR-020 ALREADY DONE — verify only.** |
| Frontend Clients CRUD | `frontend/src/pages/Clients.tsx` (list/create/suspend/reactivate) | reuse for the Users sub-screen entry point. |

## 2. DOES NOT EXIST YET — you must build these (grep-confirmed absent)

- **No `delivered_at`/`sent_at`/delivery columns** on `reports` (`app/reports/models.py:22-71` has only `sla_deadline`:44).
- **No `delivery_attempt` table**; **no `app/delivery/` package**.
- **No SFTP config** on `Client` (`app/clients/models.py` — only `report_email_regular`:33 / `report_email_urgent`:34; comment "sending deferred later":32).
- **No n8n / webhook / send code anywhere** — `grep -ri 'n8n\|webhook' app/` = 0 hits. You build the httpx client.
- **No `DeliveryMetrics`** submodel; `OpsDashboard.delivery` is `None` (`app/observability/schemas.py`); frontend `OpsDashboardSchema.delivery = z.null()` (`frontend/src/api/schemas.ts:233-242`).
- **No `/audit/export`** endpoint; **no report `/download`** endpoint; **no delivery-callback** / **resend** routes.
- **No `configure_tracing` call in the worker** (`worker/worker.py` startup never calls it — the real US8 gap).
- **No `TRACING_ENABLED`/`LANGSMITH_*` in `docker-compose.yml`** (api+worker pass only `VAULT_ADDR`/`VAULT_TOKEN`).
- **No `DeadLetterCard`** component; **no Staff/Team or per-client Users** frontend screens (`Clients.tsx` exists, but nothing for staff or client-users).
- **Reviewer `ReportSummary`/`ReportResponse` lack `delivery_status`** — only `PortalReportSummary` (`schemas.py:154`) has it. Add it so the chip lights up for reviewers.
- **Manual consolidate trigger** (`frontend/src/components/admin/TriggerButton.tsx`) handles ingest with a simple toast and does NOT handle a 202 — confirm the consolidate path + adjust (FR-022).

## 3. Migration 0012 recipe

- File `app/db/migrations/versions/0012_delivery.py`, `revision="0012"`, **`down_revision="0011"`** (head = `0011_rls_policies`, down_revision `0010`). The `pantera_app` role must exist before `alembic upgrade` (spec 12).
- Patterns to copy: `op.create_table` / `op.add_column` / `op.create_check_constraint` from `0010_scheduling.py`; **widen a CHECK = drop + recreate** (`op.drop_constraint("ck_reports_status",...)` then `op.create_check_constraint(...)` with the 9-value set). RLS DDL from `0011_rls_policies.py:58-99` (`ENABLE`/`FORCE ROW LEVEL SECURITY` + `CREATE POLICY tenant_isolation ... USING(...) WITH CHECK(...)`).
- New client-scoped table `delivery_attempt` **must** get a tenant-isolation policy in 0012 (add to the policied set). `asyncpg` prepared-statement caching is already disabled (`statement_cache_size=0`, spec 12) — don't re-add.
- Columns to add: see [data-model.md](./data-model.md) §2 (`reports`), §3 (`delivery_attempt`), §4 (`clients` SFTP).

## 4. Config & secrets

- `app/core/config.py`: `tracing_enabled: bool=False` (:101), `langsmith_api_key: str=""` (:97), `langsmith_project="pantera"` (:98) — already present; read via `Settings` only.
- `_REQUIRED_SECRETS` = `app/core/startup.py:14-20` (database_url, redis_url, auth_jwt_secret, app_database_url, guardrails_token). **Do NOT add** `langsmith_api_key` (optional/observability). **Do** add an OPTIONAL `n8n_webhook_url` + `delivery_callback_token` to Settings/Vault — NOT to `_REQUIRED_SECRETS` (delivery degrades/holds when unset; app must still boot). If you DO make either required, also add it to the inline secret writer in `.github/workflows/ci.yml` (this bit spec 2).
- SFTP credentials: live in **n8n's credential store**, NOT the app DB (D7). App stores only `sftp_host/path/username/enabled`.
- `docker-compose.yml` (verify repo root) — add to BOTH `api` and `worker` `environment:`: `TRACING_ENABLED: ${TRACING_ENABLED:-false}` (must default to `false`, NOT empty — pydantic can't parse `""`→bool), `LANGSMITH_API_KEY: ${LANGSMITH_API_KEY:-}`, `LANGSMITH_PROJECT: ${LANGSMITH_PROJECT:-pantera}`. `docker-compose.override.yml` is ports-only (modelserver 8003 / guardrails 8002 locally).

## 5. Gotchas / lessons

- **Worker tracing insertion point**: `worker/worker.py` startup, immediately after `ctx["settings"] = settings` (:23), call `from app.observability.tracing import configure_tracing; configure_tracing(settings)` — mirrors `lifespan.py:64`. Do not duplicate the helper.
- **`configure_tracing` unit test**: use `monkeypatch` so env auto-restores (module/session fixtures that unconditionally pop env vars corrupt other tests — the spec-7 fixture lesson). Assert the three `LANGCHAIN_*` set when enabled+key; no-op when disabled OR key empty.
- **Callback idempotency**: unique `(report_id, channel)` on `delivery_attempt`; a callback for an already-final attempt is a 200 no-op; unknown dispatch → 404. Derive report status from attempts (delivered = all delivered; failed = any failed).
- **HITL gate**: delivery is enqueued ONLY from the `ReportApproved` handler. Never send from the approve route inline; never from any non-approved status.
- **Suspension hold**: the delivery job checks `client.status` at send time (fresh authorization, recompute from stored state — `app/auth/dependencies.py` pattern); if suspended → hold (stay approved-pending-delivery) + `ReportDeliveryHeld` event; reactivation handler re-enqueues held reports.
- **Tests**: `GUARDRAILS_ENABLED=false` in `tests/conftest.py` (unchanged); integration needs `PANTERA_INTEGRATION=1` + the host Vault repoint ([[host-integration-test-vault-repoint]]); use the `make_client()`/`make_staff_user` fixtures + `priv_factory` for RLS-safe seeding ([[test-isolation-pattern]]). n8n httpx call is **mocked**; test the callback endpoint directly.
- **Redaction stays green**: any `error`/`reason`/log line on the delivery path must pass through `scrub_text` — the redaction gate asserts no fake PII/secret leaks.

## 6. Per-user-story wiring map

- **US1 (P1) delivery core** → `app/delivery/` (models/rendering/n8n_client/service/handlers/routes) + register `on_report_approved` in `app/core/lifespan.py` + migration 0012 + `ReportStatus` extension + portal `_delivery_status` extension. Callback + resend routes (contracts §1/§2).
- **US2 visibility** → add `delivery_status` to reviewer `ReportSummary`/`ReportResponse` (`app/reports/schemas.py`) + `DeliveryMetrics` + `metrics_routes` populate + frontend `DashboardPage.tsx:44-49` delivery section + `schemas.ts`/`hooks.ts`. Chip + portal already wired.
- **US3 SLA + sweep** → `reports.sla_escalation_tier`/`sla_escalated_at` + `task_delivery_sla_sweep` cron in `worker/worker.py` + `app/delivery/sweep.py` (tiers → client's reviewers, then manager/admin; no-callback flip). Escalation via n8n notification.
- **US4 accounts** → frontend `StaffPage.tsx` (wire `/staff`) + `ClientUsersPage.tsx` (wire `/clients/{id}/users`) + nav in `AppShell.tsx:31-80` + routes in `routes.tsx`. Backend exists; creator sets initial password (FR-016a).
- **US5 export** → `GET /audit/export` + `GET /clients/{id}/reports/{rid}/download` + role-refine `GET /audit` + enable `DownloadReportButton.tsx` / `admin/AuditExportButton.tsx`.
- **US6 budget notify** → passive handler on `WatchlistBudgetThresholdReached` → n8n notification to manager+admin (`app/delivery/notifications.py`), register in `lifespan.py`.
- **US7 residual** → `DeadLetterCard.tsx` (from `GET /admin/dead-letters`/`failed_jobs`) + verify `WatchlistEditor` budget control persists (done) + adjust manual-consolidate trigger for 202.
- **US8 tracing** → worker `configure_tracing` + compose passthrough + `tests/unit/test_tracing_config.py`.

## 7. Spec/plan drift fixed during planning (record)

- **FR-007b simplified**: suspension does NOT flip `watchlist.is_active` or track paused lists — the cadence loop already gates on `Client.status=="active"`. Spec + data-model updated; only delivery-hold/release is new.
- **FR-020 already implemented** (`WatchlistEditor.tsx:170-184`) — tasks should mark verify-only.
- **`GET /audit` already exists** — US5 audit work = role-refinement + export, not a new view.
- Confirm `docker-compose.yml` location (repo root expected) before editing the env blocks.
