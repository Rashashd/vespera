# Feature Specification: Frontend SPA (Reviewer Queue · Admin Console · Client Portal)

**Feature Branch**: `010-frontend`

**Created**: 2026-06-13

**Status**: Draft

**Input**: User description: "React SPA: reviewer HITL approval queue, admin console, and read-only client portal — serves all user types (manager, admin, reviewer, client-user) over JWT auth."

## Overview

Pantera's backend exposes the full pharmacovigilance pipeline (ingestion → triage → grounded report drafting → human-in-the-loop approval), but every interaction today is API-only. This feature delivers the single-page web application that puts a human in front of that pipeline: a **Safety Reviewer** works the approval queue and authorizes every send; a **Platform Admin/Manager** configures clients, watchlists, and severity rules and watches cost; and a **Client-user** signs in to a read-only, per-watchlist view of their own client's approved and sent reports. The application is the human-in-the-loop control surface the product's safety and regulatory posture depends on — no report leaves the system without a reviewer acting in this UI.

The application is role-aware: one sign-in experience routes each user type to the surfaces they are permitted to use, and never exposes data outside a user's authorization scope (client-users see only their own client; the per-client wall is honored in the UI exactly as the API enforces it).

## Clarifications

### Session 2026-06-14

- Q: Do the three spec-9 backend gaps (passage-text endpoint, client-user report read, per-report finding list) get implemented in this spec or treated as external prerequisites? → A: Full-stack — spec 10 implements the three thin client-scoped backend read endpoints alongside the SPA.
- Q: How does a staff user (reviewer/manager/admin) choose which client they are acting on, given the per-client API? → A: A persistent acting-client switcher in the top nav (defaults to last used); every queue/console view is scoped to the selected client (no cross-client unified queue in v1).
- Q: Which reports are visible in the client portal, and how is the portal organized? → A: Client-users see ONLY reports that have been reviewer-approved AND sent/delivered (never merely approved or any in-workflow state). The portal is organized as one page per watchlist — each watchlist lists its own reports (both expedited and batch). Reaching "sent" depends on delivery (spec 13); until then the portal correctly shows nothing as sent. Expedited reports lacking a direct `watchlist_id` are attributed to a watchlist via the `document_watchlists` junction (same mechanism spec 9 uses for batch attribution).
- Q: What is the SPA testing strategy given the constitution's coverage/HITL gates? → A: Component/integration tests (mocked API) across all primary SPA flows for breadth, PLUS one end-to-end browser test of the reviewer approve/reject happy path against the running stack; the three new backend endpoints fall under the existing pytest coverage gates (incl. 95% on HITL backend code); the fresh-clone smoke test is extended to build and serve the SPA.
- Q: The cost/usage dashboard has no backend (no LLM-cost attribution exists). Drop it, placeholder it, or build it? → A: Build it via tracing. Add LangSmith tracing to BOTH external LLM call sites — the LangGraph agent (spec 9) AND the raw-httpx triage valence call (spec 8, which bypasses LangChain) — each trace tagged with `client_id`/`finding_id`; AND persist a per-client token/cost record locally (tokens × pinned model pricing). The admin cost dashboard reads the local store (not the LangSmith API at view-time). Embeddings/classifier are local ONNX (zero external cost) and are excluded. This is now in-scope, full-stack work for this spec.
- Q: (refinement, codebase-grounded) The manual "cycle" trigger — what does it map to? → A: The existing `POST /clients/{id}/watchlists/{watchlist_id}/ingest` (202) — manual trigger is per-watchlist ingestion, not a single per-client call; the console triggers it per watchlist.
- Q: (revision) Exactly which reports does each role see, and how is delivery status surfaced? → A: **Client-user sees approved AND sent reports** (status ∈ {approved, sent, delivered}; not sent-only — so the portal is populated in v1 by approved reports, FR-023/030). **Reviewer sees ALL reports** for the acting client across every status as a read-only history distinct from the drafts action queue (FR-006a). **Each report shows a delivery status** — "Approved (pending delivery)" now, and Sent / Delivered / Delivery-failed + `delivered_at` once the delivery layer (spec 13) sets them (FR-006b). This supersedes the earlier "client sees sent/delivered only / portal empty in v1" decision.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Reviewer works the approval queue and authorizes a send (Priority: P1)

A Safety Reviewer signs in and lands on the approval queue showing all drafted reports awaiting a decision, with expedited (urgent/emergency) reports surfaced ahead of batch reports and a visible deadline countdown on each expedited item. The reviewer opens a report, reads the structured fields (Drug, Reaction, Population, Dose, Study type, Source reliability, Corroboration count, Causality, Recommendation) and the drafted narrative, and — critically — sees the **complete** set of corroborating citations for each finding (all N sources, not just the top hit). For any citation the reviewer can open the exact source passage text to confirm the report describes it correctly. The reviewer then takes exactly one action: **Approve**, **Edit then Approve**, **Reject with a comment** (which sends it back for an automated redraft, capped at 3 rounds), or **Discard**. Once acted upon, the report leaves the queue.

**Why this priority**: This is the product's core safety control and the entire reason the frontend exists — the only path by which any report is authorized to be sent. Without it there is no human-in-the-loop gate and nothing can be delivered. It is independently demonstrable as the MVP.

**Independent Test**: Seed a drafted expedited report and a drafted batch report for a client, sign in as a reviewer, and verify the queue lists both (expedited first, with a countdown), the detail view renders all structured fields and every corroborating citation with openable passage text, and each of the four actions produces the correct outcome (approved/edited-approved/redraft-on-reject/discarded) with the report removed from the active queue.

**Acceptance Scenarios**:

1. **Given** a reviewer is signed in and drafted reports exist for the acting client, **When** they open the queue, **Then** they see drafts-only items (no operator alerts, no journal follow-ups), with expedited reports ordered ahead of batch reports and each expedited item showing a deadline countdown.
2. **Given** a reviewer opens a report, **When** the detail view loads, **Then** all structured fields, the drafted body, the corroboration count, and the full list of all N corroborating sources are displayed for each finding.
3. **Given** a reviewer is viewing a finding's citations, **When** they select a citation, **Then** the exact source passage text is shown so they can verify the drafted claim against the source.
4. **Given** a reviewer is viewing a drafted report, **When** they choose Approve, **Then** the report becomes ready-to-send and is removed from the active queue, and the action is recorded for audit.
5. **Given** a reviewer chooses Edit then Approve, **When** they modify structured fields and/or the body and confirm, **Then** the edited content is persisted as the approved report and the edit does not require grounding to pass.
6. **Given** a reviewer rejects a report with a comment and fewer than 3 prior revisions, **When** they submit, **Then** the report returns to a drafting state for an automated redraft addressing the comment and the revision count increases.
7. **Given** a reviewer rejects a report for the 4th time, **When** they submit, **Then** the report is flagged for manual revision, stays visible in the queue, and is no longer auto-redrafted.
8. **Given** a reviewer chooses Discard, **When** they confirm, **Then** the report becomes terminal, cannot be sent, and leaves the queue.
9. **Given** a non-reviewer (manager/admin/client-user) is signed in, **When** they attempt a reviewer action, **Then** the action is refused and the UI does not present approve/reject controls to them.
10. **Given** a reviewer is signed in, **When** they open the all-reports view (distinct from the action queue), **Then** they see every report for the acting client across all statuses, each showing its status and a delivery status ("Approved (pending delivery)" in this version), filterable by status and openable read-only.

---

### User Story 2 - Reviewer manages findings inside a batch report (Priority: P1)

A reviewer opens a batch report (one consolidated document covering many minor/positive findings for a client cycle) and reviews each finding section. They can remove a single finding from the report without rejecting the whole document: **drop** a finding (it returns to the pending batch and is eligible again next cycle) or **discard** a finding permanently (it never resurfaces). The rest of the batch proceeds. If removing findings empties the batch entirely, the report is automatically discarded.

**Why this priority**: Batch reports are one of the two report types the product ships, and per-finding control is an explicit brief requirement ("for batch reports, individual findings can be discarded while the rest proceeds"). It shares the queue/detail surface with Story 1 and is part of the same MVP slice.

**Independent Test**: Seed a batch report with multiple findings, sign in as a reviewer, drop one finding and discard another, and verify the dropped finding is re-eligible next cycle while the discarded finding is terminal, the remaining findings stay in the report, and emptying the batch auto-discards the report.

**Acceptance Scenarios**:

1. **Given** a batch report with several findings is open, **When** the reviewer drops a finding, **Then** that finding is removed from the report and returned to pending-batch status while the remaining findings stay included.
2. **Given** a batch report with several findings is open, **When** the reviewer discards a finding, **Then** that finding is permanently removed and will not appear in any future report.
3. **Given** all findings in a batch report have been dropped or discarded, **When** the last one is removed, **Then** the report is automatically discarded.

---

### User Story 3 - Any user signs in and is routed by role (Priority: P1)

A user (manager, admin, reviewer, or client-user) opens the application, signs in with email and password, and is routed to the surfaces their role permits: reviewers to the approval queue, managers/admins to the admin console, and client-users to their own read-only portal. The session persists across page reloads until it expires, after which the user is returned to sign-in. Invalid credentials and rate-limited login attempts produce clear feedback. No user is shown navigation to surfaces they are not authorized to use.

**Why this priority**: Authentication and role-based routing are the precondition for every other story — nothing in the application is reachable without it. It is the thin foundational slice that makes Stories 1, 2, 4, and 5 demonstrable.

**Independent Test**: With seeded users of each type, sign in as each and verify the landing surface and visible navigation match the role, a reload keeps the session, an expired/invalid session returns to sign-in, and wrong credentials show an error without leaking whether the account exists.

**Acceptance Scenarios**:

1. **Given** a registered user, **When** they sign in with valid credentials, **Then** they are authenticated and routed to their role's default surface.
2. **Given** a signed-in user reloads the page, **When** the application re-initializes, **Then** the session is restored without requiring re-login (until expiry).
3. **Given** a user's session has expired, **When** they make any authenticated request, **Then** they are returned to the sign-in screen with a clear message.
4. **Given** a user enters invalid credentials, **When** they submit, **Then** they see an error that does not disclose whether the email is registered.
5. **Given** a user of a given role is signed in, **When** the navigation renders, **Then** only surfaces permitted to that role are shown and direct navigation to a forbidden surface is blocked.

---

### User Story 4 - Admin/Manager configures clients, watchlists, and severity rules (Priority: P2)

A manager or admin signs in to the admin console and manages the operational configuration that drives the pipeline: create and configure clients (cycle cadence, severity thresholds), manage each client's watchlists (drug names, keywords) and per-client custom severity keywords, and trigger a manual monitoring cycle for any client. They can view a per-client cost and usage dashboard.

**Why this priority**: The console is required by the brief and is what makes the system operable without raw API calls, but the approval queue (P1) can be demonstrated against seeded configuration, so the console is the second slice. The cost dashboard adds in-scope observability work (LangSmith tracing + a local per-client usage/cost store, FR-032–FR-035); manual trigger reuses the existing per-watchlist ingestion endpoint.

**Independent Test**: Sign in as a manager, create a client with a cadence and thresholds, add a watchlist with drugs/keywords and a custom severity keyword, trigger a manual cycle, and view the cost/usage dashboard; verify each change is persisted and reflected on reload.

**Acceptance Scenarios**:

1. **Given** a manager/admin is signed in, **When** they create a client with cadence and severity thresholds, **Then** the client is persisted and appears in the client list.
2. **Given** a client exists, **When** the admin adds or edits a watchlist (drug names, keywords) and custom severity keywords, **Then** the configuration is persisted and shown on reload.
3. **Given** a client with a watchlist exists, **When** the admin triggers a manual cycle for that watchlist, **Then** the per-watchlist ingestion run is accepted and the admin sees confirmation that it was queued.
4. **Given** external LLM calls (triage and/or agent drafting) have run for a client, **When** the admin opens the cost dashboard, **Then** per-client external-LLM cost and token usage are displayed from the local usage store; a client with no recorded usage shows an explicit empty state rather than an error.
5. **Given** a reviewer or client-user is signed in, **When** they attempt to reach the admin console, **Then** access is denied and the console is not shown in their navigation.

---

### User Story 5 - Client-user views their own approved & sent reports (Priority: P3)

A client-user signs in and sees a read-only view of their own client's **approved and sent** reports — reports the reviewer has authorized (approved) and any that have subsequently been sent/delivered — organized into **one page per watchlist**, each watchlist listing its own reports (expedited and batch), with the status of their findings. They can open a report to read it but cannot approve, edit, reject, discard, or change any configuration; they never see in-workflow (drafted/under-review/rejected/discarded) reports and never see another client's data.

**Why this priority**: Client login is beyond the brief's core build (clients are recipients there; a client portal is a listed future improvement), so it is the lowest priority slice — valuable but additive. It reuses the report read/detail surfaces from Story 1 in a read-only mode.

**Independent Test**: Sign in as a client-user, verify they see only their own client's approved and sent reports grouped by watchlist (one page per watchlist) in read-only form, that no decision or configuration controls are present, and that they cannot access another client's reports or any in-workflow report by any means.

**Acceptance Scenarios**:

1. **Given** a client-user is signed in, **When** they open their portal, **Then** they see one page per watchlist, each listing only that watchlist's approved and sent reports and finding statuses, with no in-workflow (drafted/under-review/rejected/discarded) or other-client data.
2. **Given** a client-user opens a report, **When** the detail view loads, **Then** it is read-only with no approve/edit/reject/discard or configuration controls.
3. **Given** a client-user attempts to access another client's report or any admin/reviewer surface, **When** they navigate there, **Then** access is denied.
4. **Given** a report for the client is still in workflow (drafted/under-review/rejected/discarded), **When** the client-user opens their portal, **Then** that report does not appear; once it is approved it appears.

---

### Edge Cases

- **Concurrent decisions**: two reviewers open the same drafted report and both act — only the first decision takes effect; the second sees a clear "already actioned / out of date" message and the queue refreshes rather than silently overwriting.
- **Expired SLA**: an expedited report's deadline passes while in the queue — the countdown shows an overdue state; the report remains actionable (the UI does not block the action on an expired deadline).
- **Report being redrafted**: a report a reviewer just rejected is mid-redraft when reopened — the UI reflects its in-progress drafting state rather than presenting stale draft content as actionable.
- **Citation without resolvable passage**: a citation's passage cannot be resolved (missing/older data) — the UI shows the citation metadata (title, identifier, date) and a clear "passage unavailable" state rather than failing the whole report view.
- **Empty queue**: a reviewer with no drafted reports sees an explicit empty state, not an error or blank screen.
- **Session expiry mid-action**: a session expires while a reviewer is composing an edit or reject comment — the user is returned to sign-in and, on the next attempt, is not shown a misleading success.
- **Backend capability absent**: a console feature whose backend is not yet available (e.g., cost dashboard, manual trigger) renders a clear unavailable/empty state instead of a crash.
- **Large citation sets**: a finding corroborated across many sources renders all of them without truncating the count the reviewer relies on, and remains navigable.
- **Network/API error on an action**: an action fails in transit — the report is not optimistically shown as decided; the user sees a retryable error and the true server state.

## Requirements *(mandatory)*

### Functional Requirements

#### Authentication & Authorization

- **FR-001**: The application MUST authenticate users with email and password against the existing backend auth, obtaining and using a session token (JWT) for all subsequent authorized requests.
- **FR-002**: The application MUST support all four user types — manager, admin, reviewer, and client-user — and route each to the surfaces their role is permitted to use.
- **FR-003**: The application MUST persist an authenticated session across page reloads until token expiry, and MUST return the user to sign-in on expiry or on any unauthorized response.
- **FR-004**: The application MUST NOT display navigation or controls for surfaces and actions the signed-in user is not authorized to perform, and MUST block direct navigation to forbidden surfaces (defense-in-depth alongside, never instead of, the API's enforcement).
- **FR-004a**: For staff users (reviewer/manager/admin), the application MUST provide a persistent acting-client selector in the top navigation; every client-scoped view (queue, report detail, console) MUST be scoped to the currently selected client. The selection MUST persist across navigation and reload, scoped per browser/device. On first sign-in with no prior selection, the application MUST default to a deterministic choice (the staff user's first accessible client) or present a client chooser when none is selected. If a previously-selected client becomes inaccessible or suspended, the application MUST detect this and fall back to the chooser rather than showing a broken/empty scoped view. Client-users have no selector — they are fixed to their own client. A cross-client unified queue is out of scope for this version.
- **FR-005**: The application MUST present a clear error on invalid credentials that does not reveal whether an email is registered, and MUST surface a distinct message when login is rate-limited.

#### Reviewer Approval Queue (HITL)

- **FR-006**: Reviewers MUST see a drafts-only approval **action queue** for the acting client containing reports in non-terminal review states, excluding operator alerts and journal follow-ups.
- **FR-006a**: Reviewers MUST ALSO be able to view **all reports** for the acting client across every status (drafted, under-review, needs-manual-revision, approved, rejected, discarded, and — once the delivery layer exists — sent/delivered/delivery-failed), as a read-only history distinct from the action queue. This is filterable by status and reuses the read-only report detail view. (The existing reviewer reports endpoint already accepts a status filter; this requires allowing reviewers to list all statuses, not only the review states.)
- **FR-006b**: Every report in the reviewer's all-reports view and detail MUST show its **delivery status**: in this version a report's terminal authorized state is "Approved (pending delivery)"; once the delivery layer (spec 13) introduces and sets them, the UI MUST display **Sent / Delivered / Delivery-failed** and the delivery timestamp (`delivered_at`) per report. The UI MUST be built to render these delivery states and degrade to "pending delivery" while they do not yet exist.
- **FR-007**: The queue MUST surface expedited (urgent/emergency) reports ahead of batch reports and MUST show a deadline countdown for each expedited report, including an overdue state when the deadline has passed. Among multiple expedited reports, the order MUST be by SLA deadline ascending (soonest/overdue first); among batch reports (and as the final tie-break), by creation time. The queue MUST be paginated, with a defined page size and a way to load older entries beyond the first page.
- **FR-008**: The report detail view MUST render the report's structured claims (each with its provenance and, where grounded, its source reference), the drafted narrative body, the corroboration count, and the reviewer-comment/rejection history. Together the claims and body convey the pharmacovigilance fields (Drug, Reaction, Population, Dose, Study type, Source reliability, Causality, Recommendation); the UI does not assume a fixed field-keyed grid.
- **FR-009**: For each finding, the detail view MUST display the **complete** set of corroborating citations (all N sources — title, identifier, date), not only the top retrieval hit.
- **FR-010**: For any citation, the reviewer MUST be able to open the exact source passage text it refers to, so they can verify the drafted claim against the source; if a passage cannot be resolved, the UI MUST show the citation metadata with an explicit "passage unavailable" state.
- **FR-011**: Reviewers MUST be able to **Approve** a drafted report, marking it ready-to-send and removing it from the active queue, with no further drafting triggered.
- **FR-012**: Reviewers MUST be able to **Edit then Approve**, persisting edited structured fields and/or body as the approved report; the edit path MUST NOT be blocked by the grounding gate.
- **FR-013**: Reviewers MUST be able to **Reject with a required comment**; while under the redraft cap (3) this returns the report for an automated redraft addressing the comment and increments the revision count, and on exceeding the cap the report is flagged for manual revision and stays in the queue without further auto-redraft.
- **FR-014**: Reviewers MUST be able to **Discard** a report, making it terminal and non-sendable.
- **FR-015**: Within a batch report, reviewers MUST be able to **drop** an individual finding (returns it to pending-batch, eligible next cycle) or **discard** an individual finding (permanent), while the remaining findings proceed; emptying the batch MUST result in the report being auto-discarded.
- **FR-016**: Reviewer actions MUST be restricted to the reviewer role in the UI; manager, admin, and client-user MUST NOT be offered approve/edit/reject/discard controls.
- **FR-017**: When a report has already been actioned by someone else (stale view), the UI MUST surface a clear conflict message and refresh state rather than silently overwriting a prior decision.

#### Admin Console

- **FR-018**: Managers/admins MUST be able to create and configure clients, including cycle cadence and severity thresholds.
- **FR-019**: Managers/admins MUST be able to create and edit a client's watchlists (drug names, keywords) and per-client custom severity keywords.
- **FR-020**: Managers/admins MUST be able to trigger a manual monitoring cycle and receive confirmation that it was queued. The trigger maps to the existing per-watchlist ingestion run (`POST /clients/{id}/watchlists/{watchlist_id}/ingest`); the console invokes it per watchlist.
- **FR-021**: Managers/admins MUST be able to view a per-client cost and usage dashboard sourced from the locally-persisted LLM usage records (see FR-033/FR-034), showing per-client external-LLM cost and token usage; it MUST show an explicit empty state when a client has no recorded usage yet.
- **FR-021a**: Managers/admins MUST be able to view a per-client **operations dashboard** that aggregates the pipeline's current health from existing report/finding data, including at minimum: report counts by status (drafted, under-review, approved, rejected, discarded, needs-manual-revision), pending-queue load (expedited vs batch), SLA health for expedited reports (overdue / due-soon / met), and redraft health (average revision count and the number of reports that reached the redraft cap). The cost view (FR-021) is presented as part of this dashboard. **Delivery metrics** (counts of sent / delivered / delivery-failed reports, delivery success rate and latency) are a **forward dependency on the delivery layer (spec 13)**: until those states exist the dashboard MUST show them as a "pending delivery layer" placeholder rather than fabricating numbers, and MUST light them up once spec 13 sets the delivery states. Every metric MUST render an explicit empty state when there is no data yet.
- **FR-022**: The admin console MUST be inaccessible to reviewers and client-users. Manager and admin roles have equivalent admin-console rights in this version (no manager-vs-admin capability split); reviewer and client-user have none.

#### Client Portal (read-only)

- **FR-023**: Client-users MUST see, read-only, only their own client's **approved and sent** reports (status ∈ {approved, sent, delivered} — never in-workflow drafted/under-review/rejected/discarded), organized as **one page per watchlist** with each watchlist listing its own reports (expedited and batch) and the status of their findings, and MUST be able to open a report to read it. Expedited reports without a direct watchlist association MUST be attributed to a single owning watchlist via the document/watchlist linkage so they appear under exactly one watchlist page; when a source document maps to multiple of the client's watchlists, the owning watchlist is resolved deterministically (the first/claiming watchlist, consistent with spec 9's report-once-per-client attribution).
- **FR-024**: The client portal MUST present no decision controls (approve/edit/reject/discard) and no configuration controls.
- **FR-025**: Client-users MUST NOT be able to access any other client's data or any reviewer/admin surface by any navigation path.

#### Cross-cutting UX

- **FR-026**: Every surface MUST present explicit empty, loading, and error states (no blank screens or unhandled failures), and MUST NOT optimistically present an action as succeeded before the backend confirms it.
- **FR-027**: All data shown MUST be scoped to the user's authorization (acting client for staff; own client for client-users), honoring the per-client wall in the UI exactly as the API enforces it.
- **FR-028**: The application MUST be usable on a standard desktop browser at common reviewer screen sizes; mobile-optimized layout is out of scope for this version. Basic keyboard operability and visible focus for the primary reviewer actions MUST be supported; full WCAG/accessibility conformance and localization are out of scope for this version (declared, not omitted).

#### Supporting Backend Endpoints (delivered with this feature)

- **FR-029**: The system MUST provide a client-scoped read endpoint that resolves a report claim's source reference (and a corroboration source) to the exact underlying source passage text, so the reviewer can read the cited evidence. It MUST honor the same per-client authorization as the report it belongs to and return a clear "passage unavailable" result when a reference cannot be resolved.
- **FR-030**: The system MUST provide a client-user-authorized read path to a client's own **approved and sent** reports (status ∈ {approved, sent, delivered}; never drafted/under-review/rejected/discarded) and their finding statuses, filterable/groupable **by watchlist** (the existing reviewer queue/detail routes are reviewer-only and MUST NOT be widened); this path MUST enforce that a client-user sees only their own client's data and only approved-or-later reports, and MUST resolve each report's owning watchlist (including watchlist attribution for expedited reports that lack a direct watchlist link).
- **FR-031**: The system MUST provide a read endpoint returning a report's constituent findings (drug, reaction, bucket, and per-report state) so the batch per-finding drop/discard UI can list them; it MUST be client-scoped and authorized like the parent report.

#### Observability & Cost Attribution (delivered with this feature)

- **FR-032**: The system MUST trace every external LLM call through LangSmith, covering BOTH external call sites — the LangGraph drafting agent and the triage valence call (the latter currently bypasses LangChain and MUST be instrumented to be captured). Each trace MUST be tagged with `client_id` and, where applicable, `finding_id`. Locally-run models (ONNX classifier, ONNX embedder via the modelserver) incur no external cost and are out of scope for cost attribution.
- **FR-033**: For every external LLM call, the system MUST persist a usage record attributed to the client: at minimum the `client_id`, the model used, input/output token counts, the computed cost (tokens × the pinned per-model pricing held in configuration; pricing MUST state its unit — e.g., per-1K-tokens — and currency in config), the call site (triage vs agent), and a timestamp. Token/cost capture MUST NOT block or fail the underlying pipeline operation if tracing/recording fails. (Persisting these records introduces a new store and likely a new database migration.)
- **FR-034**: The cost dashboard MUST read exclusively from the locally-persisted usage records (FR-033), never from an external tracing service at view-time, so the dashboard remains available regardless of LangSmith availability.
- **FR-035**: Tracing credentials and per-model pricing MUST follow existing configuration discipline — the LangSmith API key is a Vault-managed secret, and pricing lives in non-secret `Settings`; neither is hardcoded. Traces and usage records MUST NOT contain patient PII or secrets (redaction rules continue to apply).

#### Report Download (UI built here; export endpoint is a forward dependency)

- **FR-036**: The report detail surface (reviewer detail/all-reports and the read-only client portal detail) MUST present a **Download report** control that initiates download of the report as a self-contained document (e.g., PDF) via a dedicated backend export endpoint. That export endpoint does **not** exist yet and is intentionally a **forward dependency on a later spec**; until it exists, the control MUST render a clear disabled / "export not yet available" state (consistent with FR-026 and the "backend capability absent" edge case) rather than erroring. The control MUST honor the same per-client authorization as the report it belongs to (a client-user may only download their own client's approved/sent reports). When the export endpoint is added, the control MUST light up with no UI restructuring.

#### Audit Export & Theme

- **FR-037**: The admin console MUST present an **Audit log export** control (CSV/JSON) for the acting client, with brief explanatory text about its compliance purpose. The backend audit-export endpoint does **not** exist yet and is intentionally a **forward dependency on a later spec**; until it exists, the control MUST render a clear disabled / "export not yet available" state rather than erroring, MUST honor staff-only authorization, and MUST light up with no UI restructuring once the endpoint is added.
- **FR-038**: The application MUST support a **light/dark theme toggle**, persisted per browser/device, applied consistently across all surfaces, and meeting reasonable contrast in both modes. The default theme is light.

### Shell & Navigation

- **FR-039**: The application MUST present a consistent shell on every authenticated surface: a **collapsible left sidebar** for role-appropriate primary navigation (icons + labels; collapsible to an icon-only rail, and auto-collapsed on the report-detail surface so the findings rail has room) and a **top bar** carrying breadcrumbs, the acting-client switcher (staff; FR-004a), the theme toggle (FR-038), and the user/logout menu. Navigation MUST avoid dead ends: every subpage is reachable and has a clear path back (breadcrumbs and/or a back control). The sidebar MUST show only the destinations permitted to the signed-in role (FR-004).

### Safety-First Reviewer Aids

- **FR-040**: The report detail surface MUST let the reviewer track, per citation, whether they have opened/reviewed its source passage, and MUST display review progress (e.g., "n of N sources reviewed"). When a reviewer approves a report without having reviewed every citation, the UI MUST surface a **soft confirmation** ("not all sources reviewed — approve anyway?") rather than hard-blocking the action — the reviewer's decision remains final and authoritative (Constitution Principle I). This review-progress state is per-reviewer, per-session, client-side (no backend persistence in v1); durable/audited verification state is a noted future improvement. The intent is to make grounding verification (Principle II) an explicit step without removing reviewer authority.
- **FR-041**: The application MUST provide a keyboard-invokable **command palette** (e.g., Ctrl/Cmd-K) to jump to a report by id, switch the acting client (staff), and navigate to primary surfaces, so the tool scales for high-volume reviewers without forcing mouse navigation. This is an accelerator layered over normal navigation, never the only path to any destination.

### Key Entities *(include if feature involves data)*

These are consumed from the existing backend; this feature introduces no new persistent domain data of its own (session/UI state is client-side only).

- **User / Session**: the signed-in identity, its role (manager | admin | reviewer | client-user) and, for client-users, the single client they are scoped to; drives routing and visible controls.
- **Report**: a safety report of type expedited or batch, with structured fields, drafted body, workflow status (drafted | under_review | approved | rejected | discarded | needs_manual_revision), revision count, optional SLA deadline (expedited) or cycle period (batch), and its constituent findings. **Delivery status** (Sent / Delivered / Delivery-failed + `delivered_at`) is a forthcoming attribute set by the delivery layer (spec 13); until then an approved report displays as "pending delivery".
- **Finding (within a report)**: a drug/reaction observation with a bucket (emergency/urgent/minor/positive) and a per-report state (included/dropped/discarded) for batch handling.
- **Citation / Corroboration source**: one of the N sources supporting a finding — title, identifier, date, and a reference resolvable to an exact source passage the reviewer can read.
- **Claim provenance**: each structured claim carries one of three provenance values — `drafted_grounded` (AI-written from a retrieved passage; MUST carry a resolvable source reference), `reviewer_attested` (added/edited by the reviewer; not grounding-gated), or `aggregated` (a batch summary line aggregating already-grounded findings; not tied to a single passage). The UI MUST visually distinguish these so the reviewer can tell grounded from attested content.
- **Client**: a monitored pharma client with cadence, severity thresholds, and custom severity keywords (admin-managed).
- **Watchlist**: a client's monitored drug names and keywords (admin-managed); also the organizing unit of the client portal (one page per watchlist, listing that watchlist's approved and sent reports).
- **LLM usage record**: one row per external LLM call — `client_id`, optional `finding_id`, model, input/output token counts, computed cost (tokens × pinned per-model pricing), call site (triage | agent), timestamp. Aggregated per client to drive the admin cost dashboard; written from the traced agent and triage call sites.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A reviewer can go from sign-in to an authorized decision (approve, edit-approve, reject, or discard) on a drafted report entirely within the application, without any direct API call, in under 3 minutes for a typical report (a typical report = a single-finding expedited report, or a batch report of roughly ten or fewer findings).
- **SC-002**: For every finding in a report, 100% of its corroborating sources are visible to the reviewer (the displayed source count equals the report's corroboration count), and each source's exact passage text is openable from the UI.
- **SC-003**: No report can be approved, edited-and-approved, rejected, or discarded by any user other than a reviewer through the application, and no send is possible without a reviewer decision recorded.
- **SC-004**: Each user type, on sign-in, reaches only the surfaces permitted to their role; 0 forbidden surfaces are reachable via navigation or direct URL in testing.
- **SC-005**: When two reviewers act on the same report, exactly one decision takes effect and the other receives a conflict message — no decision is silently overwritten.
- **SC-006**: Every primary surface (queue, report detail, admin console, client portal, sign-in) renders a defined empty/loading/error state under the corresponding condition, with no blank screens or unhandled crashes observed in testing.
- **SC-007**: A manager/admin can create a client, configure a watchlist with custom severity keywords, and have that configuration drive a subsequent monitoring cycle, all from the console.
- **SC-008**: A client-user sees only their own client's approved and sent reports, grouped by watchlist, and can never reach another client's data, an in-workflow (drafted/under-review/rejected/discarded) report, or any decision/configuration control.
- **SC-009**: The application runs from the project's fresh-clone startup path and reaches the sign-in screen against the live backend with no manual build steps beyond the documented commands; the fresh-clone smoke test builds and serves the SPA.
- **SC-010**: All primary SPA surfaces (sign-in, reviewer queue, report detail, admin console, client portal) are covered by component/integration tests against a mocked API, and the reviewer approve/reject happy path is additionally verified by an automated end-to-end browser test against the running stack; the three supporting backend endpoints meet the existing pytest coverage gates (including 95% on HITL backend code).
- **SC-011**: Every external LLM call (triage valence and agent drafting) produces a client-attributed usage record, and the admin cost dashboard's per-client total reconciles with the sum of those records for the client; the dashboard renders with no dependency on an external tracing service being reachable.
- **SC-012**: A reviewer can mark each citation reviewed and see accurate "n of N reviewed" progress; approving a report with any unreviewed citation always surfaces a soft confirmation and, on confirm, still completes — i.e., the aid never blocks a reviewer's final decision (Principle I).

## Assumptions

- **Spec 9 is IMPLEMENTED and merged** (PR #11; `app/reports/` + `app/agent/` live on `master`, from which `010-frontend` is branched). Reviewer surfaces consume the live API, not a paper contract: queue `GET /clients/{id}/reports` and detail `GET /clients/{id}/reports/{rid}` (returning `ReportResponse`), and the actions `approve` / `edit-approve` / `reject` / `discard` (each returning a `ReportSummary`) plus per-finding `drop` (204) and `discard` (204). The actual `ReportResponse` carries: `structured_fields` as a list of **claims** (`text`, `provenance`, optional `source_ref`) — not field-keyed objects; `corroboration_count`; `corroboration_sources` as a loosely-typed list; `reviewer_comments` (rejection history); `revision_count`; optional `sla_deadline`; optional `watchlist_id` / `cycle_period_*`. The named pharmacovigilance fields (Drug/Reaction/Population/…) are conveyed within the claim list and `draft_body`, not as separate typed keys — the UI renders the claims and body, not a fixed field grid.
- **Three backend gaps exist against the live spec-9 code and are implemented IN THIS SPEC** as thin, client-scoped, read-only backend endpoints alongside the SPA (full-stack scope, confirmed 2026-06-14):
  - **Passage text endpoint is ABSENT.** No route resolves a claim's `source_ref` / a corroboration source to the underlying chunk's exact passage text. "Clickable to exact passage" requires a new thin, client-scoped read endpoint; both citation metadata display and full-text view are required (product owner: the reviewer must read the source text to verify the report).
  - **No client-user read path to reports.** The queue and detail routes are guarded by `require_reviewer`; there is no client-user dependency or client-scoped read endpoint. The read-only client portal therefore depends on new client-facing read endpoint(s) for a client's own approved/delivered reports + finding statuses.
  - **No per-report finding list endpoint.** `ReportResponse` does not include the report's findings, and no route returns a report's findings with drug/reaction/bucket/state. The batch per-finding drop/discard UI depends on a new read of a report's constituent findings (a `ReportFindingResponse`-shaped list already exists as a schema but is not exposed by any route).
- **Queue ordering (expedited-first) is a UI concern.** The live `GET /reports` returns reports ordered by `created_at` desc; `report_type` and `sla_deadline` are present on `ReportSummary`, so the frontend sorts expedited ahead of batch and renders the SLA countdown client-side.
- **Client portal is the v1 read-only scope.** Client-users get read-only access to their own client's **sent/delivered** reports (organized one page per watchlist) and finding statuses only — never in-workflow or approved-but-unsent reports. Read-only visibility into their watchlists/drugs and cycle status beyond grouping reports is explicitly a **future improvement**, not in this version. This intentionally goes beyond the brief, which treats clients as report recipients (a client portal is a listed future improvement); the product owner has pulled the read-only portal into scope.
- **Client portal is populated in v1 by `approved` reports; delivery states are a spec-13 forward dependency.** The live `ReportStatus` enum (spec 9) is `drafted | under_review | approved | rejected | discarded | needs_manual_revision`; there is **no `sent`/`delivered`/`delivery_failed` value** — `approved` is the terminal state today. Because client visibility includes **approved** (not sent-only), the portal IS populated in this version as soon as the reviewer approves a report. Spec 13 (delivery, n8n) is responsible for introducing the `sent`/`delivery_failed` statuses (and `delivered_at`) and actually sending. The reviewer's all-reports view and the report detail show a **delivery status** that reads "Approved (pending delivery)" until those states exist, then "Sent / Delivered / Delivery-failed" once spec 13 sets them (FR-006b). **Forward dependency recorded for spec 13 planning:** spec 13 MUST (a) add the `sent`/`delivery_failed` statuses + `delivered_at` and the actual delivery action, and (b) ensure the spec-10 reviewer delivery-status display and the client portal's sent/delivered visibility light up (the UI is built to render them now). Until then, the client sees approved reports and the reviewer sees them as pending delivery.
- **Report export endpoint is a forward dependency (not built here).** FR-036 adds a "Download report" control in the UI now, but no backend route produces a downloadable report document today. The export endpoint (format — e.g., PDF — and which spec owns it decided when built; a natural home is the delivery track, spec 13) is a **recorded forward dependency**: spec 10 ships the disabled/"export not yet available" control, and the later spec MUST add the client-scoped export endpoint and ensure this control lights up with no UI restructuring. Recorded in the forward-dependency ledger.
- **Audit-export endpoint is a forward dependency (not built here).** FR-037 adds an "Audit log export" control now; no backend audit-export route exists today. The endpoint (CSV/JSON over the existing append-only audit log) is a **recorded forward dependency**: spec 10 ships the disabled control, a later spec adds the staff-only export route, and the control lights up. Recorded in the forward-dependency ledger.
- **Operations-dashboard delivery metrics are a spec-13 forward dependency.** FR-021a's pipeline/SLA/redraft/cost cards are buildable now from `reports`/`findings`/`llm_usage`; the sent/delivered/delivery-failed cards depend on the delivery states spec 13 introduces and are stubbed ("pending delivery layer") until then — the same forward dependency as FR-006b.
- **Admin console depends on existing client/watchlist APIs (specs 3 / 4b).** Client creation, watchlist management, and custom severity keywords use the existing client-scoped backend routes.
- **Manual trigger has a backend; cost attribution is built in this spec.** Manual cycle trigger maps to the existing per-watchlist ingestion endpoint. Cost/usage has no prior backend, so this spec adds it: LangSmith tracing on both external LLM call sites + a locally-persisted per-client usage/cost store the dashboard reads (FR-032–FR-035). This pulls observability (LangSmith) and per-client cost attribution into this spec as in-scope, full-stack work; durable/scheduled triggering remains a later spec (11).
- **Authentication reuses the existing fastapi-users JWT backend** (specs 2 / 4b) — email/password login, bearer token, and the existing role model (staff manager/admin/reviewer; client-user scoped to one client). No new auth mechanism is introduced.
- **Token storage (plan-level default).** The backend issues a single ~8h bearer access token (no refresh token in v1 — that's a documented future improvement). Because the API is header-based bearer auth and FR-003 requires the session to survive reload, the SPA persists the token client-side (browser storage) rather than in memory only; the XSS exposure of that choice is mitigated by the constitution-mandated CSP/security headers and the short token lifetime. A cookie-based scheme would require backend changes and is out of scope. `/speckit-plan` confirms the exact mechanism.
- **Tenant scoping is enforced by the API; the UI mirrors it.** The frontend filters by the acting client (staff) or own client (client-user) for usability, but relies on the backend as the authoritative per-client wall — the UI is defense-in-depth, not the security boundary.
- **Target platform is a modern desktop web browser.** Mobile-optimized layouts are out of scope for this version.
- **No explicit read-latency targets beyond the task-level SC-001.** Queue and report-detail reads follow standard interactive-app expectations (perceptibly responsive, with loading states per FR-026); no per-endpoint latency SLO is set in this version.
- **Live public deployment of the SPA is handled by the project's overall deployment track**, not redefined here; this feature must build and run from the documented fresh-clone path and operate against the live backend.
- **No streaming/real-time push is assumed.** Queue freshness is achieved by reloading/refetching (including after a conflict); live websockets/SSE are not required for this version.
