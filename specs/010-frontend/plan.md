# Implementation Plan: Frontend SPA (Reviewer Queue · Admin Console · Client Portal)

**Branch**: `010-frontend` | **Date**: 2026-06-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/010-frontend/spec.md`

> **READ FIRST before `/speckit-implement`:** [contracts/implementation-notes.md](./contracts/implementation-notes.md)
> — verified, codebase-grounded API pins (live `ReportResponse` shape, `source_ref`=chunk_id,
> auth deps, migration number, router wiring). A cold/weaker implementer MUST read it to avoid
> hallucinating fields and routes that don't exist.

## Summary

Deliver the single-page web application that puts a human in front of Pantera's pipeline, plus the
thin backend it needs. Four surfaces behind one JWT sign-in, role-routed:

1. **Reviewer HITL queue (P1, the MVP)** — drafts-only action queue (expedited-first + SLA
   countdown), full report detail with **all N citations** openable to **exact passage text**, and
   the four reviewer actions (Approve / Edit-Approve / Reject-with-comment ×3 / Discard) plus
   per-finding drop/discard in batch reports. Plus a read-only **all-reports** view showing every
   status and a per-report **delivery status**.
2. **Admin console (P2)** — clients, watchlists, custom severity keywords, manual per-watchlist
   ingestion trigger, and a per-client **cost/usage dashboard**.
3. **Client portal (P3)** — read-only, own-client **approved + sent** reports, one page per watchlist.
4. **Auth + role routing (P1)** — login, session-across-reload, acting-client switcher for staff.

**Backend delivered in this spec (full-stack):**
- Three thin client-scoped read endpoints (FR-029 passage-text, FR-030 client-portal reports,
  FR-031 per-report findings) + a reviewer all-reports listing tweak (FR-006a).
- Observability + cost attribution: **LangSmith tracing** on both external LLM call sites (the
  LangGraph agent and the raw-httpx triage call) and a **local per-client LLM usage/cost store**
  (new migration `0009`) the dashboard reads (FR-032–FR-035).

**Technical approach:** React 18 + Vite + TypeScript + Tailwind + shadcn/ui SPA in a new
top-level `frontend/` workspace, served as its own container (constitution Principle VI explicitly
permits the React SPA as a separate runtime). The SPA is a pure API client — the backend remains the
authoritative per-client wall; UI role-gating is defense-in-depth. Backend additions are small,
async FastAPI routes following existing `app/<domain>/{routes,schemas,service,models}.py` patterns.

## Technical Context

**Language/Version**: TypeScript 5.x (frontend, Node 20 LTS toolchain) · Python 3.12+ (backend, `uv`)

**Primary Dependencies**:
- *Frontend*: React 18, Vite 5, React Router 6, TanStack Query 5 (server-state/caching/refetch),
  Tailwind CSS 3, shadcn/ui (Radix primitives), Zod (response parsing), Vitest +
  React Testing Library (component/integration), Playwright (one e2e). State: React Query for
  server state + a small auth/acting-client context (no Redux).
- *Backend (new)*: `langsmith` (tracing SDK) added to the main dependency group; everything else
  reuses installed deps (FastAPI, SQLAlchemy async, alembic, langchain-*).

**Storage**: PostgreSQL (existing) — one new table `llm_usage` via alembic migration `0009`. No
frontend persistent storage beyond browser `localStorage` for the JWT + acting-client selection.

**Testing**: *Frontend* — Vitest + RTL (component/integration against a mocked API, e.g. MSW),
Playwright (one e2e: reviewer approve/reject happy path against the running stack). *Backend* —
existing `pytest` (`uv run pytest`); the three new endpoints + usage capture fall under existing
coverage gates (80% overall, 95% HITL). Fresh-clone smoke test extended to build + serve the SPA.

**Target Platform**: Modern desktop web browser (Chromium/Firefox/Safari current). Mobile-optimized
layout out of scope (FR-028). Backend runs in the existing Docker compose stack.

**Project Type**: Web application (existing Python backend + new React frontend). Structure Option 2.

**Performance Goals**: Interactive-app responsiveness with explicit loading states (FR-026); no
per-endpoint latency SLO this version (Assumptions). Task-level target: sign-in→decision < 3 min
for a typical report (SC-001).

**Constraints**: Backend stays async throughout (constitution). LangSmith key is a Vault secret;
per-model pricing lives in `Settings` (`extra="forbid"`); traces/usage records carry no PII/secrets
(FR-035). Token/cost capture MUST NOT fail the underlying pipeline op (FR-033). React SPA is the
only new container; no torch, no MCP.

**Scale/Scope**: ~5 primary SPA surfaces; 4 user roles; single backend instance; tens–hundreds of
reports per client. Not a high-throughput concern.

## Constitution Check

*GATE: must pass before Phase 0 and be re-checked after Phase 1.*

| Principle | Relevance | Compliance in this plan |
|-----------|-----------|--------------------------|
| **I. Human-in-the-Loop (NON-NEGOTIABLE)** | The SPA *is* the HITL surface. | Reviewer is the only role offered approve/edit/reject/discard (FR-016); UI is defense-in-depth, API enforces (`require_reviewer`). No send path is added — drafting↔sending stay separate; delivery is spec 13. ✅ |
| **II. Grounding Is the Grade (NON-NEGOTIABLE)** | Reviewer must see all N citations + source text. | FR-009 renders the complete corroboration set; FR-029 passage endpoint lets the reviewer read the exact cited passage. No claim rendering hides sources. ✅ |
| **III. Triage Fails Safe** | Not touched. | No triage logic changes; tracing wraps the existing call without altering its fail-safe default. ✅ |
| **IV. Every Decision Backed by a Number** | New backend endpoints + cost capture. | Covered by existing eval/coverage gates; no new model/threshold introduced. Cost figures are derived (tokens × pinned pricing), not a quality metric. ✅ |
| **V. Multi-Tenant Isolation (NON-NEGOTIABLE)** | Client portal + acting-client + new reads. | All new reads client-scoped (`acting_client` / client-user own-client gating); client-users strictly limited to own approved+sent reports (FR-030, FR-025). Reviewer queue routes NOT widened to client-users. Usage records carry `client_id`. ✅ |
| **VI. Lean, Reproducible, Justified Architecture** | New SPA container + new dep. | React SPA is an explicitly-permitted separate container. One new backend dep (`langsmith`), justified by FR-032. No torch, no MCP. Frontend build reproducible via lockfile (`package-lock.json`/`pnpm-lock.yaml`). ✅ |
| **VII. Own Every Line (Spec-Driven)** | — | This plan + tasks precede code; Conventional Commits; PRs < 400 lines (frontend split into reviewable slices by surface). ✅ |
| **Security & Secrets** | JWT in browser; LangSmith key. | Token in `localStorage` justified (header bearer + reload persistence) and mitigated by CSP/security headers + ~8h TTL (Assumptions). LangSmith key → Vault `_REQUIRED_SECRETS` only if tracing is mandatory at boot; here tracing is best-effort, so the key is **optional** (empty disables tracing) and NOT added to `_REQUIRED_SECRETS` (no forced ci.yml secret). PII redaction continues (FR-035). |
| **Engineering Standards** | Async, config discipline, file hygiene. | New routes async; pricing in `Settings`; new files carry module docstrings and stay ≤ ~300 lines. ✅ |

**Initial gate: PASS.** No violations requiring Complexity Tracking. One deliberate choice recorded:
LangSmith key is an **optional** secret (tracing degrades gracefully), so it is not added to
`_REQUIRED_SECRETS` and requires no ci.yml inline-secret change (contrast spec 2's lesson — that
applies only to *required* secrets).

### Post-Design Re-check (after Phase 1)

Re-evaluated after data-model + contracts: still **PASS**. The `llm_usage` table carries `client_id`
(isolation), no PII columns (only token counts/model/cost/timestamps/optional finding_id). The
passage endpoint reuses `Chunk.client_id` scoping. No new constitutional tension introduced.

## Project Structure

### Documentation (this feature)

```text
specs/010-frontend/
├── plan.md              # This file
├── research.md          # Phase 0: decisions (frontend stack, tracing, token storage, attribution)
├── data-model.md        # Phase 1: llm_usage table + consumed read models
├── quickstart.md        # Phase 1: run/validate the SPA + new endpoints end-to-end
├── design-system.md     # Design tokens (color/type/spacing), components, per-screen layouts
├── contracts/
│   ├── implementation-notes.md   # READ-FIRST anti-hallucination pins (live API truth)
│   ├── backend-endpoints.md      # FR-029/030/031 + FR-006a request/response contracts
│   ├── cost-observability.md     # FR-032–035 tracing + usage-store contract
│   └── frontend-architecture.md  # routes, role-routing, data layer, component map, test plan
├── checklists/
│   ├── requirements.md           # (done) spec-quality gate
│   └── release-gate.md           # (done) 56-item release gate
└── tasks.md             # Phase 2 (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
# Existing backend (unchanged layout; additive only)
app/
├── reports/
│   ├── routes.py            # + reviewer all-reports listing tweak (FR-006a)
│   ├── portal_routes.py     # NEW — client-user read path (FR-030) + per-report findings (FR-031)
│   ├── passages.py          # NEW — passage-text resolve route + service (FR-029)
│   └── schemas.py           # + PortalReportSummary, ReportFindingDetail, PassageResponse
├── observability/           # NEW package
│   ├── __init__.py
│   ├── models.py            # LlmUsage ORM (table llm_usage)
│   ├── schemas.py           # usage record + cost-dashboard aggregate schemas
│   ├── pricing.py           # token→cost using Settings pricing table
│   ├── usage.py             # record_usage() write helper (best-effort, never raises upward)
│   ├── tracing.py           # LangSmith setup + @traceable wrapper for the triage call
│   └── routes.py            # GET /clients/{id}/usage cost-dashboard read (FR-021)
├── agent/graph.py           # + capture input/output tokens → record_usage (agent call site)
├── triage/llm.py            # + wrap _call_llm with tracing + record_usage (triage call site)
├── core/config.py           # + langsmith_api_key (optional secret), pricing + tracing Settings
├── db/migrations/versions/
│   └── 0009_llm_usage.py    # NEW migration
└── main.py                  # + include_router(portal/passage/usage routers)

# NEW frontend workspace (its own container)
frontend/
├── src/
│   ├── api/                 # typed fetch client, Zod schemas, React Query hooks
│   ├── auth/                # auth context, token store, role routing, acting-client context
│   ├── components/          # shadcn/ui-based shared components (citation panel, status chips…)
│   ├── pages/               # SignIn, ReviewerQueue, ReportDetail, AllReports, AdminConsole,
│   │                        #   CostDashboard, ClientPortal
│   ├── routes.tsx           # React Router config with role guards
│   └── main.tsx
├── tests/                   # Vitest + RTL component/integration (mocked API)
├── e2e/                     # Playwright: reviewer approve/reject happy path
├── index.html
├── package.json
├── vite.config.ts
├── Dockerfile               # build + serve (nginx or vite preview) — its own container
└── tailwind.config.ts

# Compose
docker-compose.yml           # + frontend service
```

**Structure Decision**: Web-application layout (Option 2). The backend keeps its existing
`app/<domain>/` modular-monolith structure (additive files only, each ≤ ~300 lines). The frontend is
a brand-new isolated `frontend/` workspace built and served as its own container, consistent with
constitution Principle VI's explicit allowance for the React SPA runtime. No existing backend file is
restructured; reviewer queue routes are extended, not rewritten.

## Complexity Tracking

> No constitution violations — table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
