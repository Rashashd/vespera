# Contract — Frontend Architecture (Spec 010 SPA)

React 18 + Vite + TypeScript + Tailwind + shadcn/ui. React Router 6, TanStack Query 5, Zod, Vitest +
RTL (+ MSW), Playwright. The SPA is a **pure API client**; the backend is the security boundary.

> **Visual/look-and-feel = [../design-system.md](../design-system.md)** (color/type/spacing tokens,
> component specs, per-screen layouts). This file owns structure/routing/data; design-system owns design.

---

## App shell (FR-039) & visual system

- **Collapsible left sidebar** — role-appropriate primary nav (icons + labels). Collapsible to an
  icon-only rail (~56px); **auto-collapsed on the report-detail route** so layout C's findings rail has
  room (resolves the sidebar↔rail collision). Shows only destinations permitted to the signed-in role.
- **Top bar** — breadcrumbs (no dead ends; every subpage has a back path), the acting-client switcher
  (staff; FR-004a), the theme toggle (FR-038), and the user/logout menu.
- **Theme (FR-038)** — light/dark via Tailwind `darkMode: "class"` + shadcn CSS variables; persisted in
  `localStorage`, default light, applied app-wide through a `ThemeProvider`.
- **Visual direction** — clean, professional life-sciences tone; subtle blue/green/neutral accents;
  severity/SLA conveyed with restrained color (strong accent reserved for expedited/overdue). Guidance
  cues: confirmation **toasts fire on backend confirmation only** (never optimistic, FR-026), SLA
  banners, inline hints, tooltips. Desktop-first; mobile/full-WCAG out of scope (FR-028) but keyboard +
  visible focus + ARIA labels are honored.

---

## Routes & role gating

| Path | Surface | Allowed roles | Default landing for |
|---|---|---|---|
| `/login` | Sign-in | all (unauth) | — |
| `/queue` | Reviewer action queue (drafts-only) | reviewer | reviewer |
| `/queue/:reportId` | Report detail + actions | reviewer | — |
| `/reports` | All-reports read-only history (`status=all`) | reviewer | — |
| `/reports/:reportId` | Read-only report detail | reviewer | — |
| `/admin` | Admin console (clients/watchlists/keywords/trigger) | manager, admin | manager, admin |
| `/admin/dashboard` | Manager dashboard (pipeline/SLA/redraft/cost + stubbed delivery) | manager, admin | manager, admin |
| `/admin/audit` | Audit log export (button → forward-dep endpoint) | manager, admin | — |
| `/portal` | Client portal (watchlist index) | client-user | client-user |
| `/portal/watchlists/:watchlistId` | One watchlist's approved+sent reports | client-user | — |
| `/portal/reports/:reportId` | Read-only report detail | client-user | — |

A `<RequireRole roles=[…]>` route guard redirects unauthorized users to their own default surface (or
`/login` if unauth). Direct-URL navigation to a forbidden route is blocked (SC-004) — but this is
defense-in-depth; the API still enforces (a client-user hitting a reviewer route gets 403/404).

## Auth + acting-client (FR-001/003/004a)

- `AuthContext`: holds `{token, user{role, user_type, client_id}}`. On init, read token from
  `localStorage`; fetch the current user (`/auth/...me` or decode) to get role/scope. On 401, clear
  token + redirect to `/login`.
- `ActingClientContext` (staff only): selected `client_id` persisted in `localStorage`. Top-nav
  switcher lists the staff user's accessible clients. First sign-in with no selection → default to the
  first accessible client, or show a chooser if none selected. If the selected client becomes
  inaccessible/suspended (a scoped read 404/403s on it) → fall back to the chooser (FR-004a).
  Client-users have **no** switcher (fixed to `user.client_id`).
- Every client-scoped query key includes the acting/own `client_id` so switching refetches.

## Data layer (TanStack Query)

- One typed `apiClient` (fetch wrapper) attaches `Authorization: Bearer <token>`; on 401 triggers the
  auth-clear. All responses parsed with Zod schemas mirroring the backend (parse defensively —
  `corroboration_sources` via `.passthrough()`).
- Query hooks per resource: `useReportsQueue`, `useAllReports`, `useReport`, `useReportFindings`,
  `usePassage` (enabled on citation click), `usePortalReports`, `useUsageDashboard`,
  `useClients`/`useWatchlists` (admin).
- Mutations (`useApprove`, `useEditApprove`, `useReject`, `useDiscard`, `useDropFinding`,
  `useDiscardFinding`, `useTriggerIngest`) invalidate the relevant queries on success and surface a
  retryable error on failure — **no optimistic success** (FR-026). A 409/stale response shows the
  conflict message + refetches (FR-017/SC-005).

## Key UI behaviors (map to FRs)

- **Queue ordering (FR-007/R9):** sort expedited-first, then `sla_deadline` ascending (overdue first),
  then `created_at`. Render an SLA countdown badge per expedited report incl. an **overdue** state.
  Paginate via `limit`/`offset`.
- **Report detail (FR-008/009/010):** render the **claim list** (not a fixed field grid), visually
  distinguishing `provenance` (`drafted_grounded` vs `reviewer_attested` vs `aggregated`); render the
  `draft_body`; show `corroboration_count` and the **complete** `corroboration_sources` list. Each
  citation is clickable → `usePassage(chunk_id)` opens the exact text; on 404 show metadata +
  "passage unavailable".
- **Actions (FR-011–015):** Approve / Edit-then-Approve (edit claims+body) / Reject (required comment,
  show the 3-round cap + what the 4th does) / Discard. In batch reports, per-finding **drop**/**discard**
  (list findings via FR-031); emptying the batch reflects auto-discard.
- **All-reports (FR-006a/006b):** list every status with a status chip + a **delivery-status** label
  ("Approved (pending delivery)" now; Sent/Delivered/Delivery-failed + `delivered_at` once spec 13
  sets them). Read-only detail reuse.
- **Admin console (FR-018–021):** client CRUD, watchlist + custom-severity-keyword editing, per-
  watchlist **manual trigger** (`POST /clients/{id}/watchlists/{wid}/ingest` → 202 "queued"
  confirmation), and the cost dashboard (empty state when no usage).
- **Client portal (FR-023–025):** one page per watchlist listing that watchlist's **approved+sent**
  reports + finding statuses; read-only; no decision/config controls; never another client's data.
- **Cross-cutting (FR-026):** every surface has explicit empty / loading / error states.

## Report Detail layout — LOCKED: Option C (rail + center + passage drawer)

One `ReportDetail` component handles both report types and the read-only portal via three optional zones:

- **Left rail (findings list)** — renders ONLY for batch reports (multiple findings). Lists each
  finding with a status tick; selecting one loads it into the center. The per-finding **drop/discard**
  controls live here, acting on the currently selected finding (FR-015). For expedited reports (single
  finding) the rail is **collapsed/hidden** → the screen reduces to a two-pane read.
- **Center (always present)** — the selected finding's structured claims (with `ProvenanceBadge`),
  narrative `draft_body`, corroboration count, and the all-N citation list. The reviewer action bar
  (Discard / Reject / Edit / Approve) sits at the bottom of the center zone; for batch the top-level
  action is **Approve batch**. In the read-only client portal the action bar is hidden; the
  `DownloadReportButton` (T036a) remains.
- **Right passage drawer** — **closed by default**; slides in when a citation is clicked, showing the
  exact source passage (FR-029/010) with prev/next across the finding's sources and a close (✕).
  Falls back to "passage unavailable" + citation metadata when the chunk can't be resolved.

Header (all modes): back-to-queue, report id + type + severity, SLA countdown (expedited),
delivery-status chip, `[⭳ Download]`, and the primary action. This single component is reused by the
reviewer queue detail, the all-reports read-only view, and the client portal detail (actions hidden).

```
components/
  AppShell.tsx            # nav + acting-client switcher (staff)
  RequireRole.tsx         # route guard
  ReportList.tsx          # shared by queue / all-reports / portal (mode prop)
  ReportDetail.tsx        # claims + body + citations (read-only or actionable via prop)
  CitationPanel.tsx       # all-N sources; click → PassageDrawer
  PassageDrawer.tsx       # fetches + shows exact passage text / "unavailable"
  ProvenanceBadge.tsx     # grounded / attested / aggregated
  SlaCountdown.tsx        # expedited deadline incl. overdue
  DeliveryStatusChip.tsx  # pending-delivery / sent / delivered / failed
  ReviewerActions.tsx     # approve/edit/reject/discard
  FindingRow.tsx          # batch drop/discard
  admin/ClientForm, WatchlistEditor, KeywordEditor, TriggerButton, CostDashboard
pages/  SignIn, ReviewerQueue, AllReports, ReportDetailPage, AdminConsole, CostDashboardPage,
        ClientPortal, WatchlistPage
```

## Testing (SC-009/010)

- **Component/integration (Vitest + RTL + MSW):** sign-in (valid/invalid/rate-limited, no
  email-existence leak), role routing + forbidden-route blocking, queue ordering + SLA countdown,
  report detail with all-N citations + passage open + "unavailable" fallback, each reviewer action
  incl. stale-conflict, batch drop/discard + empty→auto-discard, admin CRUD + trigger + cost empty
  state, portal approved-only + per-watchlist + read-only + cross-client denial.
- **E2E (Playwright):** one happy path — sign in as reviewer, open a drafted report, approve; sign in
  again, reject another with a comment → returns to queue. Runs against the live stack.
- **Fresh-clone smoke (SC-009):** extend to `npm ci && npm run build` and serve the SPA; reaching the
  sign-in screen against the live backend with only documented commands.

## Build & deploy

- `frontend/Dockerfile`: multi-stage `npm ci && npm run build` → static assets served (nginx or
  `vite preview`). Added as its own `frontend` service in `docker-compose.yml` (constitution Principle
  VI: React SPA is a permitted separate container). `VITE_API_BASE_URL` configures the backend origin.
- Lockfile committed (`package-lock.json` or `pnpm-lock.yaml`) for reproducibility.
