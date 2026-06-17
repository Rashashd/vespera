# Implementation Plan: Report Delivery & Final Wiring Close-Out

**Branch**: `013-delivery` | **Date**: 2026-06-17 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/013-delivery/spec.md`

> **READ FIRST before `/speckit-implement`:** [implementation-notes.md](./implementation-notes.md) — verified file:line anchors, exact signatures, and "do-not-rebuild" inventory. A cold implementer MUST read it; the grounding below is summarized there.

## Summary

Close the loop: on reviewer **approval**, render the report and deliver it to the client via n8n (email and/or SFTP per client config), tracking a real delivery lifecycle (`sent` → `delivered` / `delivery_failed`) confirmed by an authenticated n8n callback, with a no-callback timeout sweep and a tiered reviewer-deadline SLA monitor. Then light up everything earlier specs stubbed for "the delivery layer": the per-report delivery-status display, the client portal's sent/delivered visibility, the manager dashboard delivery cards, report download + audit export, the budget-threshold notification, the dead-letter card, and the missing account-management screens — plus complete the worker-side LangSmith tracing wiring (off by default).

Technical approach: a new `app/delivery/` package (rendering + n8n client + delivery service + callback handling) driven by the existing in-process domain-event dispatcher (`ReportApproved` → durable ARQ job) and a new periodic sweep cron; one Alembic migration (`0012`) widening `reports.status`, adding delivery timestamps + SLA-escalation columns + a per-channel `delivery_attempt` table + per-client SFTP destination columns; thin role-refinement + export on the existing `GET /audit`; and frontend wiring of already-built components (`DeliveryStatusChip`, disabled export buttons, dashboard delivery section) plus two new admin screens (Staff/Team, per-client Users).

## Technical Context

**Language/Version**: Python 3.13 (uv); TypeScript/React 18 + Vite (frontend SPA)

**Primary Dependencies**: FastAPI, SQLAlchemy 2 (async), Alembic, ARQ + Redis (durable jobs/cron), httpx + tenacity (n8n calls), structlog, Presidio (redaction), LangSmith (optional tracing); Jinja2 *or* a plain HTML builder for report rendering (no new heavy dep; no PDF lib — deferred). Frontend: shadcn/ui, TanStack Query (hooks), the existing typed `apiClient`.

**Storage**: PostgreSQL + pgvector. New: `delivery_attempt` table; new columns on `reports` and `clients`. Migration head is **0011** → author **0012** (`down_revision="0011"`).

**Testing**: pytest (unit + integration; `PANTERA_INTEGRATION=1` for live DB/Redis). Frontend: component/integration (mocked API) + the existing e2e smoke. n8n is **mocked in CI** (the outbound httpx call is patched; the callback endpoint is tested directly).

**Target Platform**: Linux containers (api, worker, modelserver, guardrails, frontend) via docker compose; deploy Render/Fly/Railway + managed Postgres/Redis.

**Project Type**: Web service (modular monolith) + worker + React SPA.

**Performance Goals**: No hard latency SLO (spec decision). Dispatch occurs on the next worker cycle after approval; callbacks resolve delivery; the sweep cron runs periodically (default every 15 min).

**Constraints**: Tracing OFF by default; no torch in any serving container; files ≤ ~300 lines; async throughout; tenacity (3 attempts, no 4xx retry) on every external call; structlog JSON, PII-free (redaction); secrets only in Vault (n8n callback secret optional, langsmith key optional/not required-to-boot); per-client isolation absolute (+ RLS on new client-scoped table).

**Scale/Scope**: B2B; a handful of seeded clients; low delivery volume (reports per cycle). 8 user stories; ~1 migration; 1 new backend package; ~2 new frontend screens + several light-ups.

## Constitution Check

*GATE: must pass before Phase 0 and re-checked after Phase 1.*

| Principle | Assessment | Verdict |
|-----------|-----------|---------|
| I. HITL Authority (NON-NEGOTIABLE) | Delivery is triggered ONLY by the `ReportApproved` event (`app/reports/review.py:53`); drafting and sending stay separate; no report dispatched without logged reviewer approval (FR-001/006). | ✅ PASS |
| II. Grounding Is the Grade | Delivery does not draft; the rendered document carries the already-grounded claims + all corroboration sources verbatim (FR-002). No new ungrounded content. | ✅ PASS |
| III. Triage Fails Safe | Untouched. | ✅ N/A |
| IV. Every Decision Backed by a Number | No new ML decision; no new eval gate needed. Existing eval gates unaffected; coverage gates apply (80% overall, 95% DB-write/HITL-adjacent). | ✅ PASS |
| V. Multi-Tenant Isolation & Data Protection (NON-NEGOTIABLE) | Every delivery/notification/export names a server-validated client + is audited (FR-008/FR-026); new `delivery_attempt` table is client-scoped → gets an RLS policy in 0012; manager cross-client audit export is the **audited internal-operator exception** (FR-018); delivery/notification logs + traces redacted (FR-024/029); the report body to its own client is the intended deliverable. | ✅ PASS |
| VI. Lean, Reproducible, Justified Architecture | NO new serving container (n8n is the pre-existing, constitution-sanctioned notification/SFTP layer; delivery logic is a module `app/delivery/`, not a service). No torch. Rendering = HTML (PDF deferred). Reuse httpx+tenacity, ARQ, the dispatcher. uv lockfile. | ✅ PASS |
| VII. Own Every Line (Spec-Driven) | spec → clarify → checklist → plan → tasks → implement; Conventional Commits; PRs < 400 lines (this feature will be split across commits per user story). | ✅ PASS |
| Security & Secrets | n8n webhook URL + callback secret in Vault (callback secret optional, not required-to-boot); per-client SFTP credentials live in **n8n's credential store** (brief §9), not the app DB — the app stores only the SFTP destination metadata; tracing OFF by default; startup validation unchanged. | ✅ PASS |
| Engineering Standards | async; tenacity; structlog PII-free; domain-event decoupling (delivery + notifications are passive handlers/jobs); new files ≤300 lines; redaction gate + fresh-clone smoke stay green. | ✅ PASS |

**Result: PASS — no violations.** Complexity Tracking table below is empty (nothing to justify).

## Project Structure

### Documentation (this feature)

```text
specs/013-delivery/
├── plan.md                 # This file
├── research.md             # Phase 0 — design decisions
├── data-model.md           # Phase 1 — schema + migration 0012
├── quickstart.md           # Phase 1 — runnable validation scenarios
├── contracts/
│   └── delivery-api.md      # Phase 1 — new/changed endpoints + n8n contract
├── implementation-notes.md # READ-FIRST anti-hallucination guide (verified anchors)
├── checklists/
│   ├── requirements.md      # spec-quality (from /speckit-specify)
│   └── readiness.md         # requirements-readiness gate (all closed)
└── tasks.md                # /speckit-tasks output (NOT created here)
```

### Source Code (repository root)

```text
app/
├── delivery/                     # NEW package (US1)
│   ├── __init__.py
│   ├── models.py                 # DeliveryAttempt ORM (per (report, channel))
│   ├── rendering.py              # render_report_document(report) -> str (HTML; PDF deferred)
│   ├── n8n_client.py             # async httpx + tenacity POST to n8n webhook (mockable)
│   ├── service.py                # dispatch/confirm/fail/resend; status derivation from attempts
│   ├── handlers.py               # on_report_approved (enqueue task_deliver_report)
│   ├── notifications.py          # budget-threshold + SLA-escalation + delivery-failure alerts (US3/US6)
│   ├── sweep.py                  # no-callback timeout + SLA tiered escalation (cron body)
│   └── routes.py                 # POST delivery callback; POST re-send; GET report download
├── reports/
│   ├── enums.py                  # +SENT/DELIVERED/DELIVERY_FAILED on ReportStatus
│   ├── models.py                 # +sent_at/delivered_at/delivery_failed_at/delivery_error/sla_escalation_tier/sla_escalated_at; widen status CHECK
│   ├── portal_routes.py          # extend _delivery_status() for delivery_failed
│   ├── schemas.py                # add delivery_status to reviewer ReportSummary/ReportResponse
│   └── metrics_routes.py         # populate OpsDashboard.delivery (DeliveryMetrics)
├── audit/
│   └── routes.py                 # GET /audit role-refine (admin=client/watchlist only; reviewer 403) + GET /audit/export (csv|json)
├── clients/
│   └── models.py                 # +sftp_enabled/sftp_host/sftp_path/sftp_username (destination meta; creds in n8n)
├── observability/
│   └── schemas.py                # DeliveryMetrics submodel; OpsDashboard.delivery: DeliveryMetrics | None
├── core/
│   └── lifespan.py               # register delivery + notification handlers on the dispatcher
└── db/migrations/versions/
    └── 0012_delivery.py          # NEW migration (down_revision="0011")

worker/
└── worker.py                     # +configure_tracing(settings) after ctx["settings"]; +sweep cron in _cron_jobs

frontend/src/
├── pages/
│   ├── StaffPage.tsx             # NEW (US4) — staff/team admin (wire /staff)
│   └── ClientUsersPage.tsx       # NEW (US4) — per-client users (wire /clients/{id}/users)
├── components/
│   ├── DownloadReportButton.tsx  # enable (wire report download) (US5)
│   ├── admin/AuditExportButton.tsx  # enable (wire /audit/export) (US5)
│   └── admin/DeadLetterCard.tsx  # NEW (US7) — render failed-jobs/dead-letters
├── pages/DashboardPage.tsx       # populate Delivery section from metrics.delivery (US2)
├── pages/AllReports.tsx          # delivery_status now real (schema carries it) (US2)
└── api/schemas.ts + hooks.ts     # OpsDashboard.delivery shape; audit-export + download + staff/users hooks

docker-compose.yml                # api + worker: add TRACING_ENABLED/LANGSMITH_API_KEY/LANGSMITH_PROJECT passthrough

tests/
├── unit/                         # configure_tracing; delivery status derivation; rendering; sweep logic
└── integration/                  # approve→dispatch→callback→delivered; failure+resend; suspended hold; SLA tiers; audit export authz; account-mgmt
```

**Structure Decision**: Modular monolith (existing). Delivery is a **new cohesive package** `app/delivery/` (not a new container) — justified by the file-size discipline (Principle VI) and the distinct concern; it reuses the dispatcher, ARQ, httpx/tenacity, redaction, and the audit handler. n8n remains the only external notification/SFTP routing layer (already constitution-sanctioned). Frontend changes are component/page wiring within the existing SPA.

## Complexity Tracking

> No Constitution violations — table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
