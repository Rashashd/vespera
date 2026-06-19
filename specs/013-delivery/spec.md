# Feature Specification: Report Delivery & Final Wiring Close-Out

**Feature Branch**: `013-delivery`

**Created**: 2026-06-17

**Status**: Draft

**Input**: User description: "n8n notification routing (email + SFTP per client config); `delivered_at` callback; `delivery_failed` status + n8n alert; reviewer-deadline SLA monitoring — and, because this is the final spec, light up the widest set of stubbed UI surfaces left by earlier specs."

## Context & Why This Spec

Pantera drafts grounded safety reports and a qualified reviewer approves them — but today **approval is the end of the line**. The report status set stops at `approved`, nothing is ever sent to the client, no delivery is confirmed, and a missed reviewer deadline goes unescalated. The whole point of the platform — *the approved report reaching the pharma client* — is unbuilt.

This is also the **last spec**, so it deliberately closes out the largest backlog of stubbed UI any spec inherits. Earlier specs built UI and backend that intentionally render "pending" or sit disabled, waiting for delivery to exist: the per-report delivery-status display, the client portal's sent/delivered visibility, the manager dashboard's delivery cards, the report-download and audit-export buttons, the budget-threshold notification, the half-wired LLM tracing, and several smaller controls whose backends already shipped. This spec lights all of them up.

The platform's two safety invariants are non-negotiable here: **no report is sent without logged reviewer approval** (drafting and sending stay separate), and **client-to-client isolation is absolute** — every delivery, notification, and export names and is scoped to a server-validated client.

## Clarifications

### Session 2026-06-17

- Q: When the routing layer never confirms a dispatch, how is a report left in `sent` resolved? → A: A timeout sweep flips a report still `sent` after a configured no-callback window to `delivery_failed` and alerts staff (no send sits unconfirmed indefinitely; `delivered` remains callback-confirmed).
- Q: When a client has both email and SFTP configured, what defines `delivered`? → A: Dispatch to every configured channel and track each independently; `delivered` only when ALL configured channels confirm; if any channel fails, `delivery_failed` (recording which), and re-send targets only the failed channel(s).
- Q: Who can view/export the audit log, and over what scope? → A: Role-based event-category visibility across all clients (staff are not single-client): manager (superuser) sees/exports ALL events; admin sees/exports ONLY client/watchlist-management events; reviewer has NO audit-log access; client-users never. Export supports optional client/time filters and emits CSV + JSON.
- Q: How does a missed reviewer-deadline escalate if the report stays unreviewed? → A: Tiered escalation — Tier 1 notifies the client's reviewers on miss; Tier 2 escalates to manager/admin if still unactioned after a further configured interval. Each tier fires once (not every tick); escalation stops when the report is approved/discarded.
- Q: What does client suspension do to delivery and watchlists? → A: Suspension is a comprehensive pause — approved reports are held (delivered on reactivation or explicit staff re-send) and no new cycles run. Verified at plan time: the cadence loop already excludes non-active clients (`query_due_watchlists` filters `Client.status=='active'`), so cycles stop on suspension with no watchlist state change; spec 13 adds only the delivery-hold + release-on-reactivation, and cycles resume automatically when active again.

### Session 2026-06-17 — readiness-gate closures

Decisions taken to close the `readiness.md` requirements-quality checklist before planning:

- Delivery channels are exactly **email + SFTP**; "configured" = required settings present (email address / SFTP host+path+credentials); deliver to every configured channel (FR-003).
- Channel-failure threshold = the platform's standard resilient-call retry (3 attempts, exponential backoff, no 4xx retry) (FR-004a); callback idempotency keyed on **(report, channel)** (FR-005).
- **No-callback timeout default = 6h**; **SLA Tier-2 default = 2h** after Tier-1 (FR-006a / FR-012).
- SLA **Tier-1 targets the client's reviewers** (shared queue — no single "assigned reviewer"); Tier-2 the client's manager/admin (FR-012).
- **Re-send / held-release** authorization and **delivery-failure + budget notifications** → admin/manager, not reviewers (FR-006 / FR-007 / FR-019).
- "Client/watchlist-management events" (admin audit scope) **enumerated**; manager cross-client export is the audited internal-operator exception (FR-018).
- New accounts get an **admin-set initial credential out-of-band**; self-service reset is future (FR-016a).
- **Delivery success rate = delivered ÷ dispatched** (FR-011); **render failure holds the report** + alert (FR-002); **"fresh authorization check" = recomputed from current stored state** (FR-026).
- Delivery/alert/escalation **timing is intentionally non-SLO** (qualitative "shortly"/"promptly" accepted).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Approved report is delivered to the client (Priority: P1)

A reviewer approves a drafted safety report. The system renders the report into a self-contained document and routes it to the client through the channel(s) that client has configured (email and/or SFTP), choosing the regular or urgent recipient based on the report's urgency. The report moves from `approved` → `sent`, and on a delivery-confirmation callback → `delivered` (recording when), or → `delivery_failed` on error. A failed delivery raises an alert to internal staff and can be re-sent without losing data.

**Why this priority**: This is the reason the platform exists. Without it, every prior spec produces drafts that never reach the customer. It is the minimum viable slice — a single approved report that actually arrives at the client closes the end-to-end loop.

**Independent Test**: Configure a client with a delivery channel, approve a report, and assert: (a) the report is dispatched to that channel, (b) status transitions approved→sent, (c) a delivered callback sets `delivered` + a delivery timestamp, (d) a failure path sets `delivery_failed` and emits an alert, (e) nothing is dispatched for a report that was never approved.

**Acceptance Scenarios**:

1. **Given** an `approved` report for a client with a configured regular email recipient, **When** delivery runs, **Then** the report document is dispatched to that recipient and the report status becomes `sent`.
2. **Given** a `sent` report, **When** the routing layer posts a successful delivery callback, **Then** the status becomes `delivered` and the delivery timestamp is recorded.
3. **Given** a `sent` report, **When** the routing layer posts a failure callback (or dispatch errors), **Then** the status becomes `delivery_failed` and an alert is raised to internal staff.
4. **Given** a report that is `drafted`, `under_review`, `rejected`, or `discarded`, **When** any delivery path is invoked, **Then** the report is NOT sent (only reviewer-approved reports are deliverable).
5. **Given** an urgent/emergency (expedited) report and a client with a distinct urgent recipient, **When** delivery runs, **Then** the urgent recipient is used.
6. **Given** a `delivery_failed` report, **When** a staff member re-triggers delivery, **Then** a fresh dispatch occurs and the status returns to `sent` (no duplicate to an already-delivered recipient).

---

### User Story 2 - Delivery status is visible across reviewer, portal, and dashboard (Priority: P2)

Now that reports carry real delivery states, the surfaces earlier specs built to render them stop showing "pending" and reflect the truth. The reviewer's all-reports view and report detail show Sent / Delivered (with the delivery time) / Delivery-failed. The client portal lists the client's sent and delivered reports with their delivery status. The manager dashboard's delivery cards (sent / delivered / failed counts and delivery success rate) populate instead of returning null.

**Why this priority**: The states are useless if no one can see them. The agency needs delivery confirmation visibility, and the client needs to see what was sent. The UI is already built to render these — this story is the verification that it lights up end-to-end.

**Independent Test**: With reports seeded across each delivery state, load the reviewer report views, the client portal, and the manager dashboard, and assert each shows the correct delivery label/count for each report — and that "Approved (pending delivery)" appears only for genuinely undelivered approved reports.

**Acceptance Scenarios**:

1. **Given** reports in `approved`, `sent`, `delivered`, and `delivery_failed`, **When** a reviewer opens the all-reports view, **Then** each report shows its correct delivery status (and `delivered` shows the delivery time).
2. **Given** a client with `sent`/`delivered` reports, **When** a client-user opens their portal, **Then** those reports appear with their delivery status, and in-workflow reports do not.
3. **Given** a client with a mix of delivery outcomes, **When** a manager opens the dashboard, **Then** the delivery cards show non-null sent/delivered/failed counts for the acting client.

---

### User Story 3 - Reviewer-deadline SLA monitoring and escalation (Priority: P2)

Expedited (urgent/emergency) reports carry a reviewer deadline. A monitor watches open expedited reports and, when a deadline is missed, escalates in tiers so the report does not sit unreviewed: first the client's reviewers are notified, and if the report is still unactioned after a further interval it escalates to the client's manager/admin. Escalation stops once the report is actioned; reports already actioned (approved/discarded/etc.) and non-expedited reports never escalate.

**Why this priority**: Patient-safety-relevant expedited findings have a time bound; an unreviewed expedited report is exactly the failure the platform exists to prevent. Independent of delivery mechanics, so it can ship and be tested on its own.

**Independent Test**: Create an expedited report with a past deadline still in an open state and assert an escalation notification fires once; create one with a future deadline and assert no escalation; create an already-approved overdue report and a non-expedited overdue report and assert neither escalates.

**Acceptance Scenarios**:

1. **Given** an open expedited report whose reviewer deadline has just passed, **When** the monitor runs, **Then** a Tier-1 escalation notifies the client's reviewers and the escalation is audited.
2. **Given** an expedited report whose deadline has NOT passed, **When** the monitor runs, **Then** no escalation occurs.
3. **Given** an expedited report that was already approved or discarded after its deadline, **When** the monitor runs, **Then** no escalation occurs.
4. **Given** a report already Tier-1 escalated and still unactioned after the configured interval, **When** the monitor runs, **Then** a Tier-2 escalation notifies manager/admin (once).
5. **Given** the monitor runs repeatedly, **When** a report has already been escalated at its current tier, **Then** it is not escalated again on every tick (no alert storm).

---

### User Story 4 - Account-management screens for staff and client-users (Priority: P2)

A manager can create, view, and deactivate staff accounts (reviewer/admin/manager) and per-client users (with their visibility scope, minimum severity, and watchlist scoping) directly from the UI. Today a manager can create a *client* but cannot add the reviewer who works it nor the client-users who log into the portal, so those flows can only be exercised with seeded/scripted accounts.

**Why this priority**: It unblocks operating the platform without scripts — onboarding a reviewer and a client's portal users is a basic agency workflow. The backend account endpoints already exist, so this is primarily UI wiring, but it is essential to a usable product.

**Independent Test**: As a manager, create a reviewer and a client-user through the UI; assert each is persisted, appears in the relevant list, can sign in, and lands in the correct role-scoped experience; assert a non-manager cannot reach the staff-creation screen.

**Acceptance Scenarios**:

1. **Given** a manager on the staff/team admin screen, **When** they create a reviewer, **Then** the reviewer account is created and can sign in to the reviewer queue.
2. **Given** a manager/admin on a client's users panel, **When** they create a client-user with a watchlist/severity scope, **Then** that user can sign in to the portal and sees only data within their scope.
3. **Given** a non-manager staff member, **When** they attempt to reach the staff-creation screen, **Then** access is denied (UI gating backed by the same server-side authorization).
4. **Given** an existing account, **When** a manager deactivates it, **Then** that account can no longer sign in.

---

### User Story 5 - Report download and audit-log export (Priority: P3)

The disabled "Download report" button (reviewer detail and portal) and the disabled "Audit log export" button (admin console) light up. A user can download the rendered report document for any report they are entitled to (client-users only their own approved/sent/delivered reports; staff for the client in their current acting context). Managers and admins can view and export the append-only audit log with role-based visibility — managers (superuser) see all events; admins see only client/watchlist-management events; reviewers and client-users have no audit-log access.

**Why this priority**: Convenience and compliance value (a downloadable report artifact and an exportable audit trail), but not on the critical delivery path — the report still reaches clients via US1 regardless.

**Independent Test**: Download a report you are entitled to and confirm the document matches what was delivered; attempt to download another client's report and confirm refusal; as staff, export the audit log and confirm the export is itself audited.

**Acceptance Scenarios**:

1. **Given** an entitled user, **When** they download a report, **Then** they receive the rendered report document.
2. **Given** a client-user, **When** they request a report not belonging to their client or not yet approved/sent, **Then** the request is refused.
3. **Given** a manager, **When** they export the audit log over a window, **Then** they receive an export of all event types across all clients, and the export action is recorded in the audit log.
4. **Given** an admin, **When** they view or export the audit log, **Then** they see only client/watchlist-management events (not auth, triage, report, or delivery events).
5. **Given** a reviewer, **When** they attempt to reach the audit log or its export, **Then** access is denied.

---

### User Story 6 - Budget-threshold notification to the agency (Priority: P3)

When a watchlist crosses its budget warning or exceeded threshold, the agency receives an actual outbound notification (the active send that spec 11 deliberately deferred), so staff can raise the budget or change the budget-exceeded policy.

**Why this priority**: The thresholds are already recorded and shown on the cost dashboard; the missing piece is the proactive nudge. Useful but secondary to delivering reports.

**Independent Test**: Drive a watchlist past its warning and exceeded thresholds and assert an agency notification is dispatched for each crossing, audited, and not re-sent on every subsequent cycle within the same state.

**Acceptance Scenarios**:

1. **Given** a watchlist that crosses its budget warning threshold, **When** the crossing is detected, **Then** an agency notification is dispatched and audited.
2. **Given** a watchlist that crosses its exceeded threshold, **When** the crossing is detected, **Then** an agency notification is dispatched.
3. **Given** a watchlist already in the warning state, **When** subsequent activity stays within the same state, **Then** a duplicate notification is not sent.

---

### User Story 7 - Close out residual stubbed frontend controls (Priority: P3)

The remaining backend-shipped-but-UI-pending controls from earlier specs are wired: the admin watchlist editor exposes a control to set the per-watchlist budget-exceeded policy (continue / critical_only / pause); the admin dashboard renders the dead-letter / failed-jobs card from existing data; and the manual consolidate-batch control handles the asynchronous 202-enqueue response (confirm + refresh/poll) instead of expecting an inline report.

**Why this priority**: Pure finish-the-wiring items whose backends already exist; each is small and independent, lowest risk, but together they retire the stubbed-UI backlog so nothing is left dangling at project end.

**Independent Test**: Set a watchlist's budget-exceeded policy from the UI and confirm it persists; trigger a dead-lettered job and confirm the card shows the count; trigger a manual consolidate and confirm the UI handles the 202 (shows enqueued + refreshes) rather than waiting for an inline report.

**Acceptance Scenarios**:

1. **Given** the admin watchlist editor, **When** a manager sets the budget-exceeded policy, **Then** the new policy persists and governs subsequent over-budget cycles.
2. **Given** unresolved dead-lettered jobs for a client, **When** a manager opens the dashboard, **Then** the failed-jobs card shows the count.
3. **Given** the admin console, **When** a manager triggers a manual consolidate, **Then** the UI acknowledges the enqueue (202) and refreshes to show progress rather than blocking on an inline report.

---

### User Story 8 - Complete LangSmith LLM tracing wiring (Priority: P3)

LLM tracing was scaffolded earlier (spec 10) and confirmed safe to enable once egress redaction was in place (spec 12 — "redaction is the control"), but it is only **half-wired**: the API process configures tracing at startup, while the triage and drafting-agent LLM calls actually execute in the background **worker**, which never configures it. So turning the tracing switch on today yields **no traces for the real pipeline**. This story completes the wiring — the worker configures tracing the same way the API does, and the deployment passes the tracing settings through to both processes — so that, *when* tracing is switched on, worker-executed LLM calls emit PII-free traces. **Tracing stays OFF by default; this is wiring, not enabling.**

**Why this priority**: Observability completeness with low risk — it changes nothing while the default-off switch stays off, and the redaction control that makes traces safe already ships. Valuable for debugging and cost attribution, but not on the delivery critical path.

**Independent Test**: With tracing enabled and a key present, run a worker triage job and a drafting-agent job and confirm matching runs appear in the configured tracing project; with tracing disabled (default) or no key, confirm zero traces and that the worker boots and runs normally; and a fast unit test confirms the tracing-config helper sets the expected environment when on and is a no-op when off.

**Acceptance Scenarios**:

1. **Given** tracing enabled with a key, **When** the worker executes a triage or drafting-agent LLM call, **Then** a corresponding run appears in the configured tracing project.
2. **Given** tracing disabled (the default) or no key, **When** the worker starts and runs jobs, **Then** no traces are emitted and the worker boots and operates normally.
3. **Given** a captured trace, **When** it is inspected, **Then** it contains only redacted content (triage runs show only a minimal `{client_id, max_tokens}` input and a redacted output; agent runs show only Presidio-redacted messages) — no patient identifiers or secrets.
4. **Given** the containerized API and worker, **When** the tracing settings are provided to the deployment, **Then** both processes receive them and the enable flag defaults to off.

---

### Edge Cases

- **No delivery channel configured** for a client whose report is approved → the report is NOT silently dropped; it is held as approved-pending-delivery and a "no delivery channel configured" alert is surfaced to staff.
- **Duplicate, out-of-order, or unknown-report callbacks** from the routing layer → callback handling is idempotent; a delivered report is not flipped back by a late/duplicate callback; a callback for an unknown report is rejected.
- **Failure then later success** → a report that failed and is re-sent reaches `delivered` cleanly without producing two delivered records.
- **Mixed multi-channel outcome** → if one configured channel confirms and another fails, the report is `delivery_failed` naming the failed channel; a re-send targets only the failed channel and the already-confirmed channel is not re-sent.
- **Client suspended** → delivery to a suspended client is **held** (not sent); the report waits and is delivered on reactivation or an explicit staff re-send.
- **Suspend/reactivate cascade** → a suspended client runs no cycles (the cadence loop gates on client status) and delivery is held; reactivating resumes cycles and releases held reports. Watchlists a staff member manually deactivated stay off (suspension makes no `is_active` change).
- **Batch report with dropped/discarded findings** → only the included findings appear in the delivered document.
- **SLA clock boundaries** → a report approved seconds before its deadline does not escalate; clock-skew and repeated monitor ticks do not double-escalate.
- **Audit export over a very large window** → the export is bounded/paginated rather than unbounded.
- **Account management** → duplicate email, creating a client-user for a suspended client, and deactivating the last manager are handled with clear errors rather than corrupting access.
- **Report-download race** → downloading a report mid-delivery returns the current rendered document (or a clear "not yet available") rather than erroring.
- **Render failure** → if the delivered document cannot be produced, the report is not dispatched; it is held with a staff alert and re-rendered on re-send.

## Requirements *(mandatory)*

### Functional Requirements

**Delivery — sending the approved report (US1)**

- **FR-001**: On a logged reviewer **approval** of a report, the system MUST dispatch that report to the client through the channel(s) configured for that client (email and/or SFTP). Drafting and sending remain separate operations; no report is dispatched without reviewer approval.
- **FR-002**: The system MUST render each approved report into a self-contained, human-readable document (the delivered artifact, used for email body/attachment, SFTP file, and report download). The document MUST carry the report's grounded content as shown on screen — structured claims with provenance, the corroboration count and all listed sources, and the narrative body (a batch report includes only its included findings). If rendering fails, the report MUST NOT be dispatched; it is held (approved-pending-delivery) with a staff alert and re-attempted on re-send. PDF generation is out of scope (future improvement); the renderer MUST be structured so a later HTML→PDF step is a drop-in addition.
- **FR-003**: The system MUST support per-client delivery configuration covering email recipients (a regular and an urgent recipient) and an SFTP destination, and MUST select the urgent recipient for expedited (urgent/emergency) reports and the regular recipient otherwise. The supported channels are exactly **email** and **SFTP**; a channel counts as *configured* only when its required settings are present (email: a recipient address; SFTP: destination host/path plus credentials). The report is delivered to every configured channel.
- **FR-004**: The report lifecycle MUST extend beyond `approved` with delivery states **`sent`** (dispatched to the routing layer), **`delivered`** (confirmed), and **`delivery_failed`** (dispatch or delivery error), and MUST record a **delivery timestamp** (`delivered_at`) on confirmed delivery. For a client with multiple channels, `delivered` follows the all-channels-confirm rule (FR-004a).
- **FR-004a**: When a client has more than one delivery channel configured, the system MUST dispatch the report to **every** configured channel and track each channel's outcome independently. A report becomes `delivered` only when **all** configured channels are confirmed; if any channel fails (after the platform's standard resilient-call retry — exponential backoff, up to 3 attempts, never retrying 4xx), the report becomes `delivery_failed`, recording which channel(s) failed. A staff re-send MUST target only the unconfirmed/failed channel(s) and MUST NOT re-send to a channel already confirmed.
- **FR-005**: The system MUST accept a **delivery-confirmation callback** from the routing layer reporting the outcome of a dispatched channel (success with delivery time, or failure). The callback MUST be authenticated so that only the routing layer can call it, MUST be **idempotent** (safe under retries, duplicates, and out-of-order delivery), and the report's overall status (`delivered`/`delivery_failed`) MUST be derived from its per-channel outcomes per FR-004a. Idempotency is keyed on the (report, channel) dispatch identity, so a duplicate, late, or out-of-order callback never changes an already-final per-channel outcome; a callback for an unknown dispatch is rejected.
- **FR-006**: On delivery failure, the system MUST set `delivery_failed` and raise an **alert** (notification) to internal staff, and MUST allow a **re-send** — authorized for admin/manager (delivery-ops) roles, not reviewers — that does not duplicate a delivery already confirmed.
- **FR-006a**: A report still in `sent` after a configured **no-callback window** (default 6 hours) MUST be automatically transitioned to `delivery_failed` and raise a staff alert, so no dispatched report sits unconfirmed indefinitely. `delivered` remains reserved for a confirmed routing-layer callback.
- **FR-007**: If a client has **no configured delivery channel**, the system MUST NOT silently drop the approved report; it MUST hold the report as approved-pending-delivery and surface a clear actionable alert to staff. The held report is released for delivery once a channel is configured and an admin/manager re-send is triggered.
- **FR-007a**: The system MUST NOT deliver to a client whose status is **suspended**; an approved report for a suspended client is held (surfaced to staff) and is delivered on the client's reactivation or an explicit staff re-send, subject to a fresh authorization check.
- **FR-007b**: Suspending a client MUST be a **comprehensive pause**: it holds delivery (FR-007a) and stops all new ingestion/triage/drafting cycles for that client. (Verified at plan time: the cadence loop already runs only for active clients — it selects watchlists whose client is `active` — so suspension stops cycles without any per-watchlist state change.) Reactivating the client MUST resume its cycles and release its held reports for delivery, subject to a fresh authorization check. The suspend/reactivate cascade MUST be audited.
- **FR-008**: Every delivery action (dispatch, delivered, failed, re-send, and "no channel" hold) MUST be recorded as an **audited domain event** naming the server-validated target client.

**Delivery visibility — lighting up the stubbed surfaces (US2)**

- **FR-009**: Reviewer report views (all-reports list and report detail) MUST display the per-report delivery status: Approved-pending-delivery / Sent / Delivered (with the delivery time) / Delivery-failed.
- **FR-010**: The client portal MUST display the client's `sent` and `delivered` reports with their delivery status, and MUST continue to exclude in-workflow reports (drafted/under_review/rejected/discarded).
- **FR-011**: The manager dashboard MUST populate the previously-null **delivery metrics** for the acting client (counts of sent / delivered / failed and a delivery success rate, defined as delivered ÷ *dispatched*, where **dispatched** = reports that have left `approved` — i.e. in `sent`, `delivered`, or `delivery_failed` — in the window).

**Reviewer-deadline SLA monitoring (US3)**

- **FR-012**: The system MUST monitor open expedited (urgent/emergency) reports against their reviewer deadline and escalate in **tiers** when missed: **Tier 1** notifies the client's reviewers (a report sits in the shared per-client reviewer queue, not assigned to one person) when the deadline is first passed; **Tier 2** escalates to the client's manager/admin if the report is still unactioned after a further interval (default 2 hours, configurable). Escalation MUST stop as soon as the report is actioned (approved/discarded).
- **FR-013**: SLA escalation MUST be audited, MUST NOT fire for reports already in a terminal/actioned state, MUST NOT fire for non-expedited reports, and MUST fire each tier **at most once** per report (never on every monitor tick — no alert storm); the current escalation tier and last-escalated time are tracked per report.

**Account management (US4)**

- **FR-014**: A manager MUST be able to create, view, and deactivate **staff** accounts (reviewer/admin/manager) from the UI.
- **FR-015**: A manager/admin MUST be able to create, view, and deactivate **per-client users** — including their visibility scope, minimum severity, and watchlist scoping — from the UI.
- **FR-016**: Account-management screens MUST enforce the same authorization as the underlying server endpoints (manager-owned staff management; per-client user management); UI role-gating is defense-in-depth only, never the security boundary.
- **FR-016a**: Creating an account (staff or client-user) MUST set an **initial credential** chosen by the creating manager/admin and communicated to the user out-of-band; self-service password-reset and invite-email flows are out of scope (future improvement).

**Report and audit export (US5)**

- **FR-017**: The system MUST provide a **report-download** capability that returns the rendered report document, scoped so client-users receive only their own approved/sent/delivered reports and staff are scoped to the client in their current acting context; this lights up the existing (disabled) "Download report" button.
- **FR-018**: The audit-log view and its export MUST enforce **role-based event-category visibility**: a **manager** (superuser) sees and exports **all** audit events; an **admin** sees and exports **only client/watchlist-management events**; a **reviewer** has **no** audit-log access; client-users never. *Client/watchlist-management events* means client lifecycle (create / suspend / reactivate / config) and watchlist lifecycle (create / activate / deactivate, item, severity-keyword, and budget-policy changes) — not auth, ingestion, triage, report, delivery, or cost events. Both the view and the export span all clients (staff are not single-client); a manager's cross-client export is the deliberate, audited internal-operator exception to client isolation (Constitution V), not tenant-to-tenant leakage. The export MUST support optional client and time-window filters (bounded/paginated), emit CSV and JSON, and the export action MUST itself be audited; this lights up the existing (disabled) "Audit log export" button.

**Budget-threshold notification (US6)**

- **FR-019**: When a watchlist crosses its budget **warning** or **exceeded** threshold (state transitions already recorded), the system MUST dispatch an outbound **notification to the agency** (the client's manager and admin), audited, and MUST NOT re-notify while the watchlist remains in the same budget state.

**Residual stubbed controls (US7)**

- **FR-020**: The admin watchlist editor MUST expose a control to set the per-watchlist **budget-exceeded policy** (continue / critical_only / pause), persisted via the existing endpoint.
- **FR-021**: The admin dashboard MUST render the **dead-letter / failed-jobs** card from the existing failed-jobs data for the acting client.
- **FR-022**: The manual **consolidate-batch** control MUST handle the asynchronous 202-enqueue response (acknowledge + refresh/poll) rather than expecting a synchronous inline report.

**Cross-cutting constraints**

- **FR-023**: All notification and delivery routing (report delivery, delivery-failure alert, SLA escalation, budget notification) MUST go through the platform's notification/delivery routing layer via durable enqueue + webhook, with no additional message broker introduced.
- **FR-024**: No PII or secret may appear in any delivery or notification **log, trace, or stored summary**; existing redaction MUST be applied to these paths. (The report content delivered to its own client is the intended deliverable and is not redacted.)
- **FR-025**: Credentials and endpoints for the routing layer and per-client SFTP MUST be handled as secrets (held in the secret store), never committed to code or stored in plaintext.
- **FR-026**: Every new client-scoped row, delivery action, notification, and export MUST remain within the per-client isolation boundary (client-to-client isolation absolute; staff actions name a server-validated target client; client-users strictly own-client). Any **fresh authorization check** (before a held or re-sent delivery, and on reactivation release) MUST be recomputed from current stored state — client status, configured recipients, report status, and actor role — never from cached or token claims.

**LangSmith tracing wiring (US8)**

- **FR-027**: The background **worker** MUST configure LLM tracing at startup the same way the API process does, so that worker-executed triage and drafting-agent LLM calls emit traces when tracing is enabled. Tracing MUST remain **OFF by default** — this requirement is wiring, not enabling.
- **FR-028**: The deployment MUST pass the tracing configuration (enable flag, API key, project name) through to **both** the API and worker processes, defaulting to OFF; the enable flag MUST default to a valid `false`, never an empty value.
- **FR-029**: Worker-emitted traces MUST be **PII-free** under the existing redaction controls — triage call inputs reduced to `{client_id, max_tokens}` and output redacted, drafting-agent messages Presidio-redacted at egress — so no patient identifier or secret appears in any trace.
- **FR-030**: A fast, non-integration automated test MUST cover the tracing-configuration helper: enabled + key sets the tracing environment; disabled or empty key is a no-op; the test MUST restore environment state afterward.

### Key Entities *(include if feature involves data)*

- **Report (extended)**: gains delivery lifecycle states (`sent`/`delivered`/`delivery_failed`) and a confirmed-delivery timestamp, in addition to its existing reviewer-deadline field.
- **Client delivery configuration**: per-client channels — regular and urgent email recipients (existing) plus an SFTP destination — and which channel(s) are enabled.
- **Delivery record / event**: one audited record per (report, channel) dispatch attempt and its outcome (channel, target client, status, error, timestamps), enabling per-channel re-send and the dashboard delivery counts. The report's overall delivery status is derived from its channel records (`delivered` only when all confirm).
- **Outbound notification**: a message routed via the notification layer — report delivery, delivery-failure alert, SLA escalation, or budget-threshold alert — addressed to a client recipient or to internal staff.
- **Staff user / Client user (existing)**: surfaced and managed by the account-management screens.
- **Audit log (existing, append-only)**: the source of the audit export and the sink for every delivery/notification/export event.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of reviewer-approved reports are dispatched to the client's configured channel shortly after approval, and 0% of reports are dispatched without a logged reviewer approval.
- **SC-002**: Every dispatched report reaches a terminal delivery outcome (`delivered` or `delivery_failed`) with a recorded delivery time on success; no report remains stuck in `sent` indefinitely.
- **SC-003**: Every delivery failure produces a staff alert promptly and is recoverable by re-send with no data loss and no duplicate delivery to an already-delivered recipient.
- **SC-004**: The reviewer views, client portal, and manager dashboard reflect the true delivery state for 100% of reports — "Approved (pending delivery)" is shown only for genuinely undelivered approved reports, and the dashboard delivery counts reconcile with the underlying delivery records.
- **SC-005**: Every missed reviewer SLA deadline on an open expedited report produces a prompt Tier-1 escalation, with at most one escalation per tier (no alert storm) and Tier-2 only after continued inaction; met deadlines and non-expedited reports never escalate.
- **SC-006**: A manager can create a working reviewer account and a working client-user account end-to-end from the UI — each can sign in and lands in the correct scoped experience — with no scripted/seeded setup.
- **SC-007**: An entitled user can download a report document and an unentitled user cannot (own-client enforced), and audit-log access matches role exactly — managers export all events, admins see/export only client/watchlist-management events, reviewers and client-users are denied; the audit export is itself audited.
- **SC-008**: 100% of watchlist budget warning/exceeded crossings produce an agency notification, with no duplicate notification while the watchlist stays in the same budget state.
- **SC-009**: No PII or secret appears in any delivery or notification log/trace (verified by the redaction gate).
- **SC-010**: The fresh-clone smoke test and all existing eval/coverage gates stay green; delivery, callback, and SLA-monitoring paths are covered to the project's bars (≥80% overall; 95% on database-write and HITL-adjacent paths).
- **SC-011**: When tracing is enabled, worker-executed triage and drafting-agent LLM calls produce runs in the configured tracing project; when it is disabled (the default), zero traces are produced and the worker boots normally; and no captured trace contains PII or secrets.

## Assumptions

- The **notification/delivery routing layer is n8n** (per the brief and Constitution VI), invoked through durable enqueue + webhook. The backend owns the enqueue, the authenticated delivery-confirmation callback endpoint, and all state; in CI/tests the routing layer is mocked/stubbed (no live n8n in CI).
- The **delivered artifact is a rendered HTML/structured-text document**. PDF generation and object-store (MinIO/S3) report storage are explicit future improvements (brief §9); the renderer is designed so HTML→PDF is a later drop-in.
- **"Delivered" is asserted by the routing-layer callback.** A report still `sent` after a configured no-callback window (default 6h) is swept to `delivery_failed` with a staff alert (FR-006a), so no send sits unconfirmed indefinitely; the window length is a tunable setting.
- **Backend endpoints already exist** for staff account CRUD and per-client user CRUD (spec 4b / agency console), so US4 is primarily frontend wiring with no backend restructuring.
- **Staff are not single-client.** Manager/admin/reviewer operate across all clients; the acting-client switcher selects the current working context, not an authority limit. For the **audit log specifically**, visibility is role-based by event category — manager is a superuser (all events), admin sees only client/watchlist-management events, reviewer has no audit-log access — which refines spec-10's generic "manager == admin console rights" for this surface (so the existing agency-console audit-log view may need its role scoping adjusted to match).
- **Budget warning/exceeded domain events already exist** (spec 11); US6 wires the deferred outbound send onto them.
- **Per-client recipients** are single addresses (regular + urgent) per the current model; multiple recipients per client and verified-domain allow-listing remain future improvements (brief §9). The SFTP destination is single per client.
- **SLA escalation recipients are internal staff**, never the client: Tier 1 → the client's reviewers (shared per-client queue, no single assignee); Tier 2 → the client's manager/admin. Escalation fires on a missed deadline (tiered, each tier once; Tier-2 default 2h after Tier-1); a pre-deadline warning is optional/future (the dashboard already surfaces "due soon"). The tier intervals are tunable settings.
- **The report delivered to its own client is the intended product** and is not redacted; redaction applies only to logs, traces, and stored summaries.
- A **schema change is required** to extend report delivery states, record delivery timestamps + per-channel delivery attempts, hold per-client SFTP destination, and track SLA escalation tier/time per report. (No watchlist state change is needed for suspension — the cadence loop already gates on client status.)
- **Suspension as a comprehensive pause.** Today `suspend_client` flips `client.status`, and the cadence loop already excludes non-active clients (so cycles already stop on suspension). This spec adds the missing piece — **holding delivery** while suspended and **releasing held reports** on reactivation; cycles resume automatically once active again. Suspension makes no watchlist `is_active` change.
- **LLM-tracing scaffolding already exists** (the tracing-config helper, the redacting trace decorator, the default-off Settings fields, the API-process startup wiring, the triage call-site decoration, and the tracing dependency); the gap this spec closes is **worker configuration + deployment passthrough + a unit test**, not rebuilding any of it.
- **The tracing API key stays env-driven** (read via Settings — the allowed config path — and never required to boot): a deliberate exception to "secrets only in Vault" for an optional, observability-only key. It is NOT added to the required-secrets set, so no CI secret-writer change is needed.
- **Delivery, alert, and escalation timing is not a hard SLO.** Dispatch occurs on the next worker cycle after approval; the qualitative "shortly"/"promptly" wording in the success criteria is a deliberate decision, not an unspecified target.
- This is the **final spec**; its intent is to deliver reports end-to-end *and* retire the known stubbed-UI / forward-dependency backlog from specs 10–11 (plus the tracing wiring above).

## Out of Scope

- **PDF report generation and blob/object-store storage** (MinIO/S3, signed URLs, per-client folder trees) — future improvement; v1 delivers a rendered document.
- **Multiple report recipients per client** and **verified-domain allow-listing** of recipient addresses — future improvements (brief §9).
- **Journal/author follow-up form delivery** (sending the empty follow-up template and ingesting the filled return) — future improvement; the follow-up artifact remains generated-not-sent.
- **E2B(R3) regulatory export format** — future improvement.
- **A full operator job-management console** (replay/re-trigger dead-lettered jobs, pause/resume queues, per-watchlist cycle history) beyond the read-only dead-letter card — deferred.
- **SSO/OIDC federation and MFA**, and **refresh-token rotation** — future auth direction, not this spec.
- **Trace sampling / cost controls and trace-based alerting** — deferred unless explicitly wanted.
- **Enabling tracing by default or in production** — out of scope; this spec only completes the wiring, and tracing ships OFF.

## Dependencies

- **Spec 9 (report drafting + HITL)** — the reviewer-approval event is the delivery trigger.
- **Spec 10 (frontend + metrics)** — the delivery-status display, portal sent/delivered visibility, dashboard delivery cards, and the disabled download/audit-export buttons are built and waiting to light up; the metrics endpoint's delivery block is currently null; the LLM-tracing scaffold (Settings fields + redacting decorator + API-process wiring) also originates here.
- **Spec 11 (ARQ + scheduling)** — durable enqueue for the send job and the SLA-monitor cron; the budget warning/exceeded events; the dead-letter data for the failed-jobs card; and the manual-consolidate 202 behavior.
- **Spec 12 (security hardening)** — redaction for delivery/notification logs and traces; Row-Level Security scoping for every new client-scoped row; redaction is also the control that makes LLM tracing safe to switch on.
- **Spec 3 / 4b (client + watchlist lifecycle)** — the suspend/reactivate comprehensive-pause cascade extends the client-status and watchlist-active behavior these specs established.
