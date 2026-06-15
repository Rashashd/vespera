---
description: "Task list for Spec 010 — Frontend SPA (Reviewer Queue · Admin Console · Client Portal)"
---

# Tasks: Frontend SPA (Reviewer Queue · Admin Console · Client Portal)

**Input**: Design documents from `specs/010-frontend/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

> **⚠️ READ FIRST:** [contracts/implementation-notes.md](./contracts/implementation-notes.md) — verified,
> codebase-grounded API pins. A cold/weaker implementer MUST read it before any task. Do not invent
> fields/routes; `grep` to confirm. Run **both** `uv run ruff check app` AND `uv run black --check app`
> on every backend change.

**Tests**: INCLUDED — SC-010 / clarify Q4 explicitly require component/integration tests across all
SPA surfaces + one e2e, and the new backend endpoints fall under existing pytest gates (95% HITL).

**Organization**: By user story. Spec stories: **US1** reviewer queue (P1, MVP), **US2** batch
findings (P1), **US3** auth & role routing (P1, precondition), **US4** admin console (P2), **US5**
client portal (P3). Phase order respects the real dependency: auth (US3) before the reviewer surfaces.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable (different files, no incomplete-task dependency)
- **[Story]**: US1–US5 (setup/foundational/polish carry no story label)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Initialize the `frontend/` workspace + the one backend dependency.

- [X] T001 Scaffold `frontend/` Vite + React 18 + TypeScript project (`frontend/package.json`, `vite.config.ts`, `tsconfig.json`, `index.html`, `src/main.tsx`)
- [X] T002 [P] Configure Tailwind CSS + shadcn/ui in `frontend/` (`tailwind.config.ts`, `src/globals.css`, `components.json`), including light/dark theme CSS variables (`darkMode: "class"`) for FR-038
- [X] T003 [P] Add React Router 6, TanStack Query 5, Zod to `frontend/package.json` and commit the lockfile
- [X] T004 [P] Configure Vitest + React Testing Library + MSW (`frontend/vitest.config.ts`, `frontend/tests/setup.ts`, `frontend/tests/msw/handlers.ts`)
- [X] T005 [P] Configure Playwright (`frontend/playwright.config.ts`, `frontend/e2e/`)
- [X] T006 [P] Add `frontend/Dockerfile` (multi-stage `npm ci && npm run build` → static serve) and a `frontend` service in `docker-compose.yml` with `VITE_API_BASE_URL`
- [X] T007 [P] Add `langsmith` to `pyproject.toml` `[project].dependencies` and refresh `uv.lock`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Backend cost/observability scaffolding (cross-cutting) + the SPA core (api client, auth,
query, routing shell) that every story builds on.

**⚠️ CRITICAL**: No user-story work begins until this phase is complete.

### Backend cross-cutting

- [X] T008 Create migration `app/db/migrations/versions/0009_llm_usage.py` — `llm_usage` table (columns + CHECK on `call_site`, indexes `ix_llm_usage_client_id`, `ix_llm_usage_client_created`) per data-model.md
- [X] T009 [P] Create `app/observability/__init__.py` + `LlmUsage` ORM in `app/observability/models.py` (mirror migration 0009)
- [X] T010 [P] Add config to `app/core/config.py`: `langsmith_api_key: str = ""` (optional secret — **NOT** in `_REQUIRED_SECRETS`), `langsmith_project: str = "pantera"`, and per-1K-token input/output USD pricing keyed by pinned model id (unit+currency in comments)
- [X] T011 [P] Implement `app/observability/pricing.py` `compute_cost(model, in_tok, out_tok, settings) -> Decimal` (unknown model → 0 + warning)
- [X] T012 Implement `app/observability/usage.py` `record_usage(...)` best-effort writer (reuses caller session; try/except → log+swallow, never re-raises) — depends on T009, T011
- [X] T013 [P] Implement `app/observability/tracing.py` `configure_tracing(settings)` (no-op when key empty) + lazy `traceable` fallback; call it at startup in `app/main.py`/lifespan after Vault load

### Frontend core

- [X] T014 [P] Typed `apiClient` fetch wrapper in `frontend/src/api/client.ts` (attach `Authorization: Bearer`, on 401 trigger auth-clear)
- [X] T015 [P] Base Zod schemas mirroring the live API (`ReportSummary`, `ReportResponse`+`Claim`, `CorroborationSource` via `.passthrough()`, `PassageResponse`, `ReportFindingDetail`) in `frontend/src/api/schemas.ts`
- [X] T016 React Query provider + client in `frontend/src/api/queryClient.tsx`, wired into `frontend/src/main.tsx`
- [X] T017 Token store (`localStorage`) + `AuthContext` (holds `{token, user{role, user_type, client_id}}`; init from storage; clear on 401) in `frontend/src/auth/AuthContext.tsx`
- [X] T018 Route shell + `RequireRole` guard skeleton in `frontend/src/routes.tsx` + `frontend/src/components/RequireRole.tsx`
- [X] T019 [P] `AppShell` in `frontend/src/components/AppShell.tsx`: **collapsible left sidebar** (role-appropriate icons+labels; collapsible to an icon rail; auto-collapsed on the report-detail route) + **top bar** (breadcrumbs slot, acting-client switcher slot, theme toggle slot, user/logout menu). No dead ends; back paths via breadcrumbs (FR-039)
- [X] T019a [P] `ThemeProvider` + theme toggle (light/dark, `class` strategy, persisted in `localStorage`, default light, applied app-wide) in `frontend/src/components/ThemeToggle.tsx` + `frontend/src/theme/ThemeProvider.tsx` (FR-038)

**Checkpoint**: Backend cost store + SPA shell exist; stories can begin.

---

## Phase 3: User Story 3 — Any user signs in and is routed by role (Priority: P1) 🎯 precondition

**Goal**: Email/password sign-in, session-across-reload, role routing, acting-client switcher.

**Independent Test**: Sign in as each user type → correct landing + visible nav; reload keeps session;
expired/invalid → `/login` with a non-enumerating error; forbidden routes blocked.

### Tests for User Story 3

- [X] T020 [P] [US3] Component tests for sign-in (valid / invalid creds — no email-existence leak / rate-limited) in `frontend/tests/signin.test.tsx`
- [X] T021 [P] [US3] Integration tests for role routing + forbidden-route blocking + reload persistence + expiry→login in `frontend/tests/routing.test.tsx`

### Implementation for User Story 3

- [X] T022 [US3] SignIn page + login mutation (`POST /auth/jwt/login`) in `frontend/src/pages/SignIn.tsx` + `frontend/src/auth/useLogin.ts`
- [X] T023 [US3] Role-based default landing + redirect of unauthorized/unauth users in `frontend/src/routes.tsx` / `RequireRole.tsx`
- [X] T024 [US3] Session persistence across reload + 401/expiry → `/login` with clear message (wire `apiClient` ↔ `AuthContext`)
- [X] T025 [US3] `ActingClientContext` + top-nav acting-client switcher (staff only; `localStorage` per-device; first-login default/chooser; lost-access → chooser fallback) in `frontend/src/auth/ActingClientContext.tsx` + `frontend/src/components/ActingClientSwitcher.tsx`
- [X] T026 [US3] Invalid-credential + rate-limit error states (non-enumerating) in `SignIn`

**Checkpoint**: Auth + routing work; other stories can render.

---

## Phase 4: User Story 1 — Reviewer works the approval queue (Priority: P1) 🎯 MVP

**Goal**: Drafts queue (expedited-first + SLA), full detail with all-N citations openable to exact
passage, the four reviewer actions, and the read-only all-reports view.

**Independent Test**: Seed a drafted expedited + a drafted batch report; as reviewer verify ordering +
countdown, detail renders all structured claims + every citation with openable passage text, and each
action produces the right outcome with the report leaving the queue.

### Backend (supporting endpoints) + tests

- [X] T027 [P] [US1] Add `status=all` to `list_reports` in `app/reports/routes.py` (default unchanged; FR-006a)
- [X] T028 [P] [US1] Passage endpoint `GET /clients/{client_id}/passages/{chunk_id}` in `app/reports/passages.py` + `PassageResponse` in `app/reports/schemas.py`; register router in `app/main.py` (FR-029)
- [X] T029 [P] [US1] Per-report findings endpoint `GET /clients/{client_id}/reports/{report_id}/findings` in `app/reports/portal_routes.py` (co-located with the FR-030 portal routes) + `ReportFindingDetail` schema in `app/reports/schemas.py`; register the router in `app/main.py` (FR-031, reused by US2/US5)
- [X] T030 [P] [US1] pytest: passage endpoint 200 + 404 `PASSAGE_UNAVAILABLE` + cross-client isolation in `tests/integration/test_passages.py`
- [X] T031 [P] [US1] pytest: report-findings endpoint + `status=all` listing in `tests/integration/test_report_findings.py`

### Frontend

- [X] T032 [US1] Reviewer queue page (drafts-only; expedited-first → SLA-asc → created_at sort; pagination via limit/offset) in `frontend/src/pages/ReviewerQueue.tsx` + `frontend/src/components/SlaCountdown.tsx` (incl. overdue state). Each row carries a **severity-colored left bar**; a persistent **overdue banner** counts overdue expedited reports (design-system §12.5)
- [X] T033 [US1] Report detail: claim list with **clinical-field hierarchy** (emphasize Drug/Reaction/Severity/Causality) + `ProvenanceBadge` rendering **three visibly distinct trust classes** (grounded = link+`#chunk`; reviewer-added/attested = dashed + pencil + "reviewer-added"; aggregated = Σ) + `draft_body` + corroboration_count + a visible **revision/comment history** panel ("round k of 3", prior rejection comments + who/when, FR-008) in `frontend/src/components/ReportDetail.tsx` + `frontend/src/components/ProvenanceBadge.tsx` + `frontend/src/components/RevisionHistory.tsx`; when a report is mid-redraft, render an explicit in-progress state instead of stale actionable content (Edge Cases). See design-system §12.3/12.4/12.6
- [X] T034 [US1] `CitationPanel` (all N corroboration sources) + `PassageDrawer` (fetch passage on click via `usePassage`; "passage unavailable" fallback) in `frontend/src/components/CitationPanel.tsx` + `frontend/src/components/PassageDrawer.tsx`
- [X] T035 [US1] `ReviewerActions`: approve / edit-then-approve / reject (required comment + 3-round cap messaging) / discard — no optimistic success; stale-conflict (409) → message + refetch in `frontend/src/components/ReviewerActions.tsx`
- [X] T036 [US1] All-reports view (`status=all`) + `DeliveryStatusChip` ("Approved (pending delivery)" now; Sent/Delivered/Delivery-failed + `delivered_at` later) + read-only detail reuse in `frontend/src/pages/AllReports.tsx` + `frontend/src/components/DeliveryStatusChip.tsx`
- [X] T036a [P] [US1] `DownloadReportButton` in `frontend/src/components/DownloadReportButton.tsx`, placed in `ReportDetail` (reviewer + portal reuse). Calls a not-yet-built client-scoped export endpoint; until it exists, render a disabled state with a **tooltip explaining why** ("Available once the delivery layer ships") (FR-036, FR-026, design-system §12.7) — no error, no UI restructuring when the endpoint lands. Honors per-client auth (client-users only own approved/sent reports).
- [X] T036b [US1] Citation-review tracking + soft approve gate in `ReportDetail`: per-citation "reviewed" toggle, "n of N sources reviewed" progress, and a **soft confirm** dialog on Approve when not all reviewed (never a hard block; reviewer decision final). Per-session client-side state (FR-040, design-system §12.2)
- [X] T036c [US1] Single primary action bar (sticky; one Approve — not duplicated in header); Reject/Discard via `alert-dialog` confirm (design-system §12.1); batch reports show an `N findings · included/dropped/needs-attention` summary header (§12.8)

### Frontend tests + e2e

- [X] T037 [P] [US1] Component/integration tests: queue ordering + SLA + **severity left-bar/overdue banner**, detail all-N citations + passage open + unavailable fallback, **citation-review progress + soft approve-gate confirm (FR-040)**, **provenance renders three distinct classes**, **revision history visible**, each action + stale-conflict, **keyboard operability + visible focus (FR-028)**, and **mid-redraft renders an in-progress state not a stale actionable draft** in `frontend/tests/reviewer.test.tsx`
- [X] T038 [US1] Playwright e2e: reviewer approve happy path + reject-with-comment returns to queue in `frontend/e2e/reviewer.spec.ts`

**Checkpoint**: MVP — a reviewer can authorize a send entirely in the UI.

---

## Phase 5: User Story 2 — Reviewer manages findings inside a batch report (Priority: P1)

**Goal**: Per-finding drop/discard inside a batch report; emptying the batch reflects auto-discard.

**Independent Test**: Seed a batch report with several findings; drop one (re-eligible next cycle),
discard another (permanent), confirm the rest proceed and emptying the batch auto-discards the report.

### Implementation for User Story 2 (reuses FR-031 from T029)

- [X] T039 [P] [US2] `FindingRow` + drop/discard mutations (`POST .../findings/{fid}/drop` 204, `.../discard` 204) in `frontend/src/components/FindingRow.tsx`
- [X] T040 [US2] Batch-mode finding list in `ReportDetail` + reflect empty→auto-discard outcome (refetch report state)
- [X] T041 [P] [US2] Component tests: drop→pending re-eligible, discard→permanent, empty→auto-discard in `frontend/tests/batch.test.tsx`

**Checkpoint**: Both P1 reviewer stories work independently.

---

## Phase 6: User Story 4 — Admin/Manager console + cost dashboard (Priority: P2)

**Goal**: Client/watchlist/keyword config, manual per-watchlist trigger, and a per-client cost
dashboard backed by traced LLM usage.

**Independent Test**: As manager, create a client, add a watchlist + custom severity keyword, trigger a
manual cycle, and view the cost dashboard (populated + empty states); all persist on reload.

### Backend (cost capture + dashboard) + tests

- [X] T042 [US4] Instrument the agent call site: capture `usage_metadata` input/output tokens → `record_usage(call_site="agent", client_id, finding_id)` in `app/agent/graph.py`
- [X] T043 [US4] Instrument the triage call site: wrap with `traceable` + `record_usage(call_site="triage", finding_id=None)` reading provider `usage` tokens in `app/triage/llm.py`
- [X] T044 [P] [US4] Cost dashboard endpoint `GET /clients/{id}/usage` in `app/observability/routes.py` + `CostDashboard` schema in `app/observability/schemas.py` (`require_admin`); register in `app/main.py` (FR-021/034)
- [X] T044a [P] [US4] Operations-metrics endpoint `GET /clients/{id}/metrics` in `app/reports/metrics_routes.py` (`require_admin`) aggregating from `reports`/`findings`: counts by status, pending-queue (expedited vs batch), expedited SLA health (overdue/due-soon/met), redraft health (avg revisions, #at-cap) + `OpsDashboard` schema; **delivery counts (sent/delivered/failed) returned as null/"pending"** until spec 13 adds the states; register in `app/main.py` (FR-021a)
- [X] T044b [P] [US4] pytest: ops-metrics endpoint status/SLA/redraft aggregation + delivery-metrics returned as pending + empty state in `tests/integration/test_ops_metrics.py`
- [X] T045 [P] [US4] pytest: usage round-trip (triage+agent rows, finding_id on agent), dashboard total reconciles with summed rows (SC-011), empty state, and `record_usage` DB-failure is swallowed in `tests/integration/test_usage.py`

### Frontend

- [X] T046 [P] [US4] Admin client CRUD (cadence + severity thresholds) in `frontend/src/pages/AdminConsole.tsx` + `frontend/src/components/admin/ClientForm.tsx`
- [X] T047 [P] [US4] Watchlist + custom severity keyword editor in `frontend/src/components/admin/WatchlistEditor.tsx` + `frontend/src/components/admin/KeywordEditor.tsx`
- [X] T048 [P] [US4] Manual per-watchlist ingest trigger (`POST /clients/{id}/watchlists/{wid}/ingest` → 202 "queued" confirmation) in `frontend/src/components/admin/TriggerButton.tsx`
- [X] T048a [P] [US4] `AuditExportButton` (CSV/JSON, staff-only, with compliance explainer) in `frontend/src/components/admin/AuditExportButton.tsx`; calls a not-yet-built audit-export endpoint → disabled "export not yet available" until it exists; lights up with no restructuring (FR-037, forward dependency)
- [X] T049 [US4] Manager dashboard page `frontend/src/pages/DashboardPage.tsx` with cards: pipeline-by-status, queue load, SLA health, redraft health (from `GET /clients/{id}/metrics`), the cost card (from `GET /clients/{id}/usage`), and **delivery cards stubbed "pending delivery layer"** (FR-021a); components in `frontend/src/components/admin/` (`PipelineCard`, `SlaHealthCard`, `RedraftCard`, `CostCard`, `DeliveryCard`); each with an explicit empty state
- [X] T050 [P] [US4] Component tests: admin CRUD persistence, trigger confirmation, dashboard cards (pipeline/SLA/redraft/cost populated + empty; delivery card shows "pending delivery layer"), audit-export button disabled state, console hidden from reviewer/client in `frontend/tests/admin.test.tsx`

**Checkpoint**: Console + cost observability operable.

---

## Phase 7: User Story 5 — Client-user views own approved & sent reports (Priority: P3)

**Goal**: Read-only, own-client approved+sent reports, one page per watchlist.

**Independent Test**: As a client-user, see only own-client approved+sent reports grouped by watchlist,
read-only, no decision/config controls, and no access to another client or any in-workflow report.

### Backend + tests

- [X] T051 [US5] Portal routes `GET /clients/{id}/portal/reports?watchlist_id=` + `/portal/reports/{rid}` (status ∈ {approved,sent,delivered}; expedited attribution via `document_watchlists`) + `PortalReportSummary`/`PortalReportDetail` schemas in `app/reports/portal_routes.py`; register in `app/main.py` (FR-030)
- [X] T052 [P] [US5] pytest: approved-only filter, own-client isolation (404 on other client), watchlist grouping/attribution in `tests/integration/test_portal.py`

### Frontend

- [X] T053 [US5] Client portal watchlist index + per-watchlist report list (read-only) in `frontend/src/pages/ClientPortal.tsx` + `frontend/src/pages/WatchlistPage.tsx`
- [X] T054 [US5] Read-only report detail reuse (no decision/config controls; `DownloadReportButton` from T036a IS present) + portal finding statuses (reuse `ReportDetail` read-only mode + FR-031 findings)
- [X] T055 [P] [US5] Component tests: approved-only visibility, per-watchlist grouping, read-only (no controls), cross-client denial in `frontend/tests/portal.test.tsx`

**Checkpoint**: All five stories independently functional.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T056 [P] Audit every surface for explicit empty / loading / error states (FR-026) across `frontend/src/pages/`
- [X] T056a [P] Command palette (⌘K) in `frontend/src/components/CommandPalette.tsx` (shadcn `command`): jump to report by id, switch acting client (staff), navigate primary surfaces; accelerator only, never the sole path (FR-041, design-system §12.10). Include a component test (opens on ⌘K, navigates) in `frontend/tests/command-palette.test.tsx`
- [X] T057 Extend the fresh-clone smoke test to `npm ci && npm run build` + serve the SPA (CI workflow / `scripts/`) — SC-009
- [X] T058 [P] Update `docs/RUNBOOK.md` + `frontend/README.md` with run/build/test commands
- [X] T059 Run `uv run ruff check app` + `uv run black --check app` on all backend changes; confirm coverage gates (80% overall, 95% HITL) pass
- [X] T060 Run `quickstart.md` end-to-end validation against the live stack

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)**: no dependencies.
- **Foundational (P2)**: depends on Setup; **blocks all stories**.
- **US3 (Phase 3)**: depends on Foundational; **precondition for US1/US2/US4/US5** (auth + routing).
- **US1 (Phase 4)**: depends on US3. The MVP slice.
- **US2 (Phase 5)**: depends on US3 + T029 (FR-031 findings) + T033/T040 (ReportDetail).
- **US4 (Phase 6)**: depends on US3 + Foundational backend (T008–T013). Independent of US1/US2/US5.
- **US5 (Phase 7)**: depends on US3 + T029 (FR-031) + T033 (read-only detail reuse).
- **Polish (Phase 8)**: depends on the stories you intend to ship.

> **Shared-file note (T029 ↔ T051):** both write `app/reports/portal_routes.py`. T029 (Phase 4)
> **creates** the file/router (FR-031 findings route) and registers it in `app/main.py`; T051
> (Phase 7) **extends** the same file with the FR-030 portal report routes (reusing the already-
> registered router). Build T029 so the module + `APIRouter` are in place for T051 to append to —
> do not create a second router for the same file.

### Within each story

- Tests authored alongside; backend endpoint before its consuming UI; models/schemas before services
  before routes; shared components before pages that compose them.

### Parallel opportunities

- Setup: T002–T007 in parallel after T001.
- Foundational: backend T009/T010/T011/T013 in parallel; frontend T014/T015/T019 in parallel
  (T012 after T009+T011; T016/T017/T018 after T014/T015).
- After Foundational + US3: US1, US4 can proceed in parallel (different files); US2 and US5 follow
  their US1 dependencies.
- All `[P]` backend pytest tasks (T030, T031, T045, T052) run in parallel.

---

## Parallel Example: User Story 1

```bash
# Backend supporting endpoints (different files) in parallel:
Task: "T027 status=all in app/reports/routes.py"
Task: "T028 passage endpoint in app/reports/passages.py"
Task: "T029 report-findings endpoint + schema"

# Then their tests in parallel:
Task: "T030 tests/integration/test_passages.py"
Task: "T031 tests/integration/test_report_findings.py"
```

---

## Implementation Strategy

### MVP first

1. Phase 1 Setup → 2 Foundational → 3 US3 (auth) → 4 US1 (reviewer queue).
2. **STOP & VALIDATE**: a reviewer can sign in and authorize a send entirely in the UI (SC-001/003).
   This is the demonstrable MVP.

### Incremental delivery

US1 (MVP) → US2 (batch finding control) → US4 (console + cost) → US5 (client portal). Each adds value
without breaking prior stories.

---

## Notes

- `[P]` = different files, no incomplete-task dependency.
- The three new backend reads + cost capture are **full-stack scope of this spec** (clarify Q1/Q5).
- Delivery states (`sent`/`delivery_failed` + `delivered_at`) are a **spec-13 forward dependency** — the
  UI renders them but spec 10 does not add the enum values (FR-006b). Recorded in the forward-dependency
  ledger.
- The **report export endpoint** (download as PDF/document, FR-036 / T036a) is a **forward dependency** —
  spec 10 ships the disabled "export not yet available" control; a later spec adds the client-scoped
  export route and the control lights up. Recorded in the forward-dependency ledger.
- The **audit-export endpoint** (CSV/JSON, FR-037 / T048a) is a **forward dependency** — same pattern:
  disabled control now, staff-only export route added later. Recorded in the ledger.
- The **delivery metrics** on the manager dashboard (sent/delivered/failed, FR-021a / T044a / T049) are a
  **spec-13 forward dependency** — the backend returns them as "pending" and the UI stubs the delivery
  cards until spec 13 adds the delivery states. Same dependency as FR-006b.
- Commit per task or logical group (Conventional Commits, **no** Co-Authored-By trailer); keep PRs < 400
  lines — split the frontend by surface.
