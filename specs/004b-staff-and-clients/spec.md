# Feature Specification: Staff & Client Account Model (Agency Foundation Revision)

**Feature Branch**: `004b-staff-and-clients`

**Created**: 2026-06-09

**Status**: Draft

**Input**: User description: "Convert Pantera from a per-client multi-tenant SaaS into an internal agency/CRO model. Pantera is a research company doing pharmacovigilance literature work FOR pharma clients. Internal staff (manager/admin/reviewer) work ACROSS all clients; each client may also have its own client-side users (added later) scoped by severity and watchlist. A manager creates and soft-deletes clients. Admins set per-client report recipient emails. Backend/API only."

## Why This Spec Exists (Context)

Specs 1–4 modeled Pantera as a classic multi-tenant SaaS: every user belongs to exactly one
client (`users.client_id` is required), there are two roles (`admin`, `reviewer`), and every
authorization check is `resource.client_id == user.client_id` — a hard wall that makes a user of
one client unable to see any other client. That correctly describes a product where each customer
company logs in to its own account.

But Pantera's real shape is an **agency / CRO**: a research company performs pharmacovigilance
literature monitoring *on behalf of* many pharma clients. Pantera's **own internal staff** must
work **across all clients**, while each client's **own people** (added later) see only their
client's work — and only the slice of it they are entitled to. This spec revises the user and
authorization foundation to match that reality **before** later specs (report drafting, reviewer
approval, notifications) build on top of it. The per-`client_id` *data* columns on
documents/watchlists/runs are correct and unchanged; only the **user + authorization layer** changes.

This is a **backend/API-only** spec. No frontend, no report drafting, no notification sending.

## Clarifications

### Session 2026-06-09

- Q: How should the migration reconcile wiping users with the foreign-key references to them (`ingestion_runs.triggered_by_user_id`, the audit human-actor) and audit immutability (FR-020)? → A: **Full dev reset** — the migration clears `users` **and** the dependent seed rows that reference them (ingestion runs + run-sources, and the audit rows authored by those users); documents/watchlists (which carry no user FK) are preserved. FR-020's append-only guarantee governs **runtime**, not this one-time foundation migration.
- Q: Where does the seeded bootstrap manager's credential come from? → A: From **Vault** at seed time (email + initial password read into memory, never written to disk or into the migration file). The manager row is created **once** via a guarded/idempotent seed (Alembic applies the data step once; if implemented as a startup seed it runs only when no active manager exists). The password is **changeable after first login** (force-change-on-first-login is the intended hardening).
- Q: Is a user's login email unique globally or per-client? → A: **Globally unique** across all users (staff and client-users alike); one email = one account, matching the email-as-login auth model.
- Q: What committed maximum access-token lifetime does "short" mean, and what happens at expiry? → A: **~8-hour single-token session** (one workday), no refresh token; at expiry the session ends and the user re-logs in. Immediate revocation of a demoted/deactivated/soft-deleted user is handled by the **per-request DB re-check**, not by the token lifetime. Refresh tokens (short access + long-lived refresh) are a documented **future improvement**.
- Q: What does an empty client-user scope (no severity floor, no watchlists) mean? → A: **Least-privilege / explicit scope.** A client-user's scope MUST be **explicitly chosen at creation** — either "full visibility of this client's reports" or a specific severity floor and/or watchlist set; no silent default is allowed (creation is refused without a choice). As a **fail-safe**, any absent/empty scope is interpreted as **no visibility** (default-deny), never as "see everything." "Full visibility" is always a deliberate, audited selection.
- Q: May a manager demote or deactivate themselves? → A: **Yes, but only while another active manager remains** — the last-active-manager guard (FR-005) applies equally to self-actions; a manager can never remove the final active manager, themselves included.
- Q: Who may view the client roster versus change it? → A: **All staff** (manager/admin/reviewer) may list/read the client roster (needed to choose a target client); **only a manager** may create/soft-delete/reactivate clients.
- Q: What happens to a client-user's watchlist scope when a scoped watchlist is deactivated? → A: **Scope links persist** through a watchlist soft-deactivation (data is preserved, mirroring client soft-delete); only a true hard-delete of a watchlist cascades its scope links away. An inactive watchlist simply yields no new reports.
- Q: What happens to an in-flight ingestion run when its client is soft-deleted mid-run? → A: **The in-flight run finishes and records its result**; no new run is accepted afterward (consistent with spec-4 FR-024). Already-ingested data is preserved.
- Q: Do the per-client recipient emails hold one address or several? → A: **A single address each** — one regular recipient and one urgent recipient per client; multiple recipients per category is a documented future improvement.
- Q: Can staff admins deactivate individual watchlists separately from suspending a client? → A: **Yes** — a staff admin (or manager) may activate/deactivate any client's individual watchlist (the spec-3 `watchlists.is_active` flag) via the acting-client model, **independently of client status**. A deactivated watchlist blocks new ingestion for that watchlist **only**; a suspended client blocks **all** its watchlists. The two controls are orthogonal; both are audited (FR-027).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Internal staff operate across all clients (Priority: P1)

Pantera's internal staff sign in once and operate across **every** client. There are three staff
roles: **manager** (the superuser who owns the client roster and all staff accounts), **admin**
(operates client workspaces, manages client-side users, configures report delivery), and
**reviewer** (will approve/reject/edit agent-written reports — the permission is granted here even
though reports arrive in a later spec). A staff user has **no home client**; instead, every action
a staff user takes must **name the client it operates on**, and that action is recorded against
that target client. This is the irreducible foundation: without a cross-client staff identity and a
safe way to scope each staff action to one named client, none of the agency workflows can exist.

**Why this priority**: This is the new identity-and-access spine that replaces the per-client wall
removed by this revision. Every later capability (client lifecycle, client-users, report delivery)
depends on staff being able to authenticate and act, scoped and audited, across clients. It is the
minimum viable, independently demonstrable slice.

**Independent Test**: Seed the bootstrap manager; have the manager create a staff admin and a staff
reviewer; sign in as each; confirm a staff user has no client of their own yet can act on an
existing client when (and only when) they name a valid client; confirm an action names its target
client in the audit log; confirm a staff user who names no client, or names a non-existent client,
is refused.

**Acceptance Scenarios**:

1. **Given** the bootstrap manager exists, **When** the manager creates a staff admin and a staff
   reviewer, **Then** each is created with `user_type = staff`, no `client_id`, and the requested
   staff role, and the creation is audited.
2. **Given** a signed-in staff admin, **When** they perform a client-scoped action (e.g., trigger
   an ingestion run) naming a valid, active client, **Then** the action is permitted and audited
   against that **target client**, regardless of the admin having no home client.
3. **Given** a signed-in staff user, **When** they attempt a client-scoped action without naming a
   client, or naming a non-existent client, **Then** the action is refused with a clear message and
   no side effects.
4. **Given** a staff reviewer, **When** they attempt a manager-only or admin-only action (e.g.,
   create a client, or create a staff account), **Then** the action is refused as forbidden.
5. **Given** any staff user, **When** the request body attempts to set `user_type` or `client_id`
   on a created/edited user, **Then** those fields are ignored/refused — they are never accepted
   from the request body.

---

### User Story 2 - A manager manages the client roster (Priority: P1)

A **manager** creates new clients (replacing the hand-run operator seed script), and can
**soft-delete** a client to retire it and **reactivate** it later. Soft-deleting a client freezes
it — no new ingestion runs are accepted and its client-side users can no longer sign in — while
**preserving all of its data** (documents, watchlists, runs, watermarks, audit). A client is never
hard-deleted. This gives Pantera a first-class, audited client lifecycle owned by a single
accountable role.

**Why this priority**: Clients are the unit of work the whole platform organizes around. A logged-in
manager creating and retiring clients is core agency operation and the natural companion to US1;
together they form the operable MVP. It depends on US1 (the manager role must exist).

**Independent Test**: As a manager, create a client and confirm it is active and audited; soft-delete
it and confirm new ingestion runs for it are refused while its existing documents/watchlists/runs
remain readable by staff; reactivate it and confirm new runs are accepted again; confirm a
non-manager cannot create, soft-delete, or reactivate a client.

**Acceptance Scenarios**:

1. **Given** a signed-in manager, **When** they create a client, **Then** the client is persisted
   active, and the creation is audited and attributed to that manager.
2. **Given** an active client, **When** a manager soft-deletes it, **Then** the client's status is set
   to **suspended**, no new ingestion run is accepted for it, its client-side users can no longer sign
   in, and **all** of its existing data is preserved (nothing deleted).
3. **Given** a soft-deleted client, **When** a manager reactivates it, **Then** it becomes active
   again, new ingestion runs are accepted, and its client-side users may sign in again.
4. **Given** a non-manager staff user (admin or reviewer), **When** they attempt to create,
   soft-delete, or reactivate a client, **Then** the action is refused as forbidden.
5. **Given** any client, **When** any actor attempts a hard delete, **Then** there is no code path
   that hard-deletes a client (data and audit trail are always retained in this spec).

---

### User Story 3 - Client-side users scoped by severity and watchlist (Priority: P2)

A client may have **several of its own users** (the pharma company's people). A staff admin creates
these client-side users and assigns each a **visibility scope**: a **minimum severity** (reusing the
existing `non-serious < serious < life-threatening` levels) and/or a **set of that client's
watchlists**. A client-side user can never widen their own scope. In this spec the **account, role,
and scope are stored and managed**, but client-side **login and report-visibility enforcement are
deferred** to the report spec — the schema exists now so nothing has to be re-migrated when reports
arrive.

**Why this priority**: The agency serves clients who need their own narrowed views, so the data model
must capture client-users and their scope now to avoid a second foundation change later. It is P2
because no report-viewing exists yet to enforce against — the value is realized when reports land —
so storing the model is sufficient for this spec. It depends on US1/US2 (staff and clients must
exist to own and scope client-users).

**Independent Test**: As a staff admin, create a client-side user for a client with a severity floor
of `serious` and a subset of that client's watchlists; confirm the user is `user_type = client`,
bound to exactly that client, with the recorded scope; confirm a watchlist from a *different* client
cannot be added to the scope; confirm the client-user cannot modify their own scope; confirm the
creation and any later scope change are audited.

**Acceptance Scenarios**:

1. **Given** an active client, **When** a staff admin creates a client-side user with a severity
   floor and/or a set of that client's watchlists, **Then** the user is persisted with
   `user_type = client`, that single `client_id`, and the recorded scope, and the creation is
   audited against the target client.
2. **Given** a client-side user, **When** an admin assigns a watchlist that belongs to a *different*
   client to that user's scope, **Then** the assignment is refused with a clear validation message.
3. **Given** a client-side user, **When** that user (once login exists) attempts to broaden their own
   severity floor or add watchlists to their own scope, **Then** the change is refused — only staff
   may set a client-user's scope.
4. **Given** a client-side user with a recorded scope, **When** an admin changes that scope, **Then**
   the change is persisted and audited; the report-visibility *enforcement* of that scope is the
   later report spec's responsibility, not this spec's.

---

### User Story 4 - Per-client report delivery addresses (Priority: P2)

For each client, a staff admin records **where that client's reports are sent**: a **regular**
recipient email and a separate **urgent** recipient email, plus the **severity threshold** at which a
report counts as urgent (default: life-threatening). This spec only **stores and audits** these
addresses and the threshold; the actual sending belongs to the later notification spec. A recorded
requirement for that spec: urgent/emergency reports are delivered **immediately when written**, not
batched on the normal cadence.

**Why this priority**: Routing reports to the right people is essential agency configuration, and it
naturally belongs to the per-client model established here, but it produces no externally-visible
behavior until the notification spec exists — so storing it (P2) is the right scope now. It depends
on US2 (the client must exist to carry the addresses).

**Independent Test**: As a staff admin, set a client's regular and urgent recipient emails and the
urgent threshold; confirm they are persisted on the client and the change is audited; confirm an
invalid email format is refused; confirm a reviewer cannot change them.

**Acceptance Scenarios**:

1. **Given** an active client, **When** a staff admin sets the regular email, the urgent email, and
   the urgent severity threshold, **Then** all three are persisted on the client and the change is
   audited against that client.
2. **Given** a recipient email field, **When** an admin submits a malformed email address, **Then**
   the request is refused with a clear validation message and the stored values are unchanged.
3. **Given** the urgent threshold is unset, **When** a client is created, **Then** the threshold
   defaults to the highest severity (life-threatening) and the regular/urgent emails are empty until
   an admin sets them.
4. **Given** report recipient emails configured, **When** a non-admin (reviewer or client-user)
   attempts to change them, **Then** the action is refused as forbidden.

---

### User Story 5 - Session freshness and tamper-evident audit (Priority: P3)

Because staff now reach across all clients, the controls that replace the old isolation wall must be
trustworthy. A user's **current** role, type, and account/client status govern every request — never
stale claims carried in a previously issued session token: a demoted, deactivated, or soft-deleted
user loses access on their **next** request, not whenever a token happens to expire. The **audit log
is append-only** and cannot be altered or deleted by anyone, including a manager superuser. Every
sensitive change is attributed to its acting staff user and its **target client**.

**Why this priority**: This hardening makes the cross-client model safe to operate and to grant the
manager superuser; the core agency capability is demonstrable before it, so it is P3 — layered on
once staff, clients, client-users, and delivery config work. It depends on all prior stories
(it hardens their access paths).

**Independent Test**: Sign in as an admin; have a manager demote that admin; confirm the admin's
next request is refused with the new, lower privileges without re-login. Soft-delete a client; confirm
its client-side user's next request is refused. Attempt, as a manager, to modify or delete an existing
audit entry; confirm it is impossible. Confirm each sensitive action recorded names the acting user
and the target client.

**Acceptance Scenarios**:

1. **Given** a signed-in staff user, **When** a manager changes that user's role or deactivates them,
   **Then** the user's very next request reflects the change (re-evaluated from current stored state),
   without waiting for token expiry.
2. **Given** a client-side user with a live session, **When** their client is soft-deleted, **Then**
   their next request is refused.
3. **Given** any actor including a manager, **When** they attempt to update or delete an audit-log
   entry, **Then** the operation is impossible — the audit log is append-only.
4. **Given** any sensitive write in this spec, **When** it succeeds, **Then** the audit entry names
   the acting staff user and the target client it acted upon.

---

### Edge Cases

- **No manager exists (bootstrap)**: The system must guarantee at least one manager exists so the
  client/staff roster can be administered; the initial manager is provisioned by the migration, not
  by a logged-in user (resolving the create-staff chicken-and-egg).
- **Last-manager protection**: Demoting, deactivating, or otherwise removing the **final active
  manager** is refused, so the platform can never be left with no one able to administer clients/staff.
- **Privilege escalation via manager minting**: Only a manager may create a manager or promote any
  user to manager; an admin attempting either is refused (no self-escalation to superuser).
- **Immutable identity fields**: Changing a user's `user_type` or `client_id` after creation is
  refused for everyone except a manager performing an explicit, audited correction; these fields are
  never read from a normal request body.
- **Staff action with no named client**: A client-scoped staff action that does not name a target
  client (or names a non-existent one) is refused; "act on all clients implicitly" is never allowed.
- **Acting on a soft-deleted client**: Triggering a new ingestion run (or other new work) for a
  soft-deleted client is refused; existing data remains readable by staff; reactivation restores
  new-work acceptance.
- **Client soft-deleted mid-run**: If a client is soft-deleted while one of its ingestion runs is
  already executing, the in-flight run finishes and records its result; no new run is accepted
  afterward, and already-ingested data is preserved (consistent with spec-4 FR-024).
- **Scoped watchlist deactivated/deleted**: A client-user's scope links persist through a watchlist
  **soft-deactivation** (data preserved); a deactivated watchlist simply yields no new reports. Only a
  true **hard-delete** of a watchlist cascades its scope links away.
- **Cross-client watchlist scope**: Assigning a watchlist from client B to a client-A user's scope is
  refused; a client-user's scope may only reference its own client's watchlists.
- **Client-user self-widening**: A client-side user may not broaden their own severity floor or add
  watchlists to their own scope; only staff may change a client-user's scope.
- **Empty client-user scope**: Creating a client-user without an explicit scope choice (neither "full
  client visibility" nor a narrowing severity/watchlist scope) is refused; and any scope that ends up
  absent/empty is treated as **no visibility** (default-deny), never as full visibility.
- **Stale session after change**: A token issued before a demotion/deactivation/soft-delete confers no
  extra access — authorization is recomputed from current stored state on each request, bounded
  further by a short token lifetime.
- **Malformed recipient email**: An invalid regular/urgent email address is refused with a clear
  message; previously stored values are unchanged.
- **Reviewer write attempts**: A reviewer attempting any create/update/soft-delete (clients, staff,
  client-users, report emails) is refused; their write surface is limited to the report
  approve/reject/edit permission granted (for use by the later report spec).
- **Existing data on migration**: Because existing accounts were all per-client admins/reviewers under
  the old model, the migration clears the user table — plus the dev rows that reference users by
  foreign key (ingestion runs/run-sources and user-authored audit rows) so nothing dangles — and seeds
  a single bootstrap manager, rather than silently converting anyone into a cross-client staff user.
  Re-running the migration or restarting the app never creates a duplicate manager (idempotent seed).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST classify every user by a **`user_type`** of exactly `staff` or `client`,
  stored independently of the user's **role**, and MUST enforce that a `staff` user has **no** owning
  client while a `client` user is bound to **exactly one** client.
- **FR-002**: System MUST support three **staff roles** — `manager`, `admin`, `reviewer` — for
  `user_type = staff` users, each acting **across all clients** (no per-staff home client).
- **FR-003**: System MUST grant a **manager** full authority: everything an admin or reviewer may do,
  **plus** creating/soft-deleting/reactivating clients and creating/managing all staff accounts
  (including other managers).
- **FR-004**: System MUST allow only a **manager** to create a user with the manager role or to
  promote any user to manager; no other role may create or promote to manager (no self-escalation).
- **FR-005**: System MUST prevent removal of the **last active manager**: demoting, deactivating, or
  otherwise removing the final active manager MUST be refused with a clear message. This guard applies
  to **self-actions** too — a manager MAY demote or deactivate themselves only while another active
  manager remains.
- **FR-006**: System MUST allow a **staff admin** to operate any client's workspace (including
  triggering ingestion for any client, revising the spec-4 own-client restriction), to create and
  manage that client's **client-side users** and their scope, and to set that client's **report
  recipient emails**.
- **FR-007**: System MUST grant a **staff reviewer** cross-client visibility and a report
  **approve/reject/edit permission** (consumed by the later report spec); a reviewer MUST NOT perform
  any administrative write (clients, staff, client-users, report emails).
- **FR-008**: System MUST require every **client-scoped staff action** to explicitly **name the target
  client**, validate it (exists and, for new work, is active), and MUST refuse an action that names no
  client or a non-existent client; “operate on all clients implicitly” MUST never be permitted. All
  staff roles (manager/admin/reviewer) MAY list/read the client roster in order to select a target
  client; **mutating** the roster (create/soft-delete/reactivate) remains manager-only (FR-010/FR-011).
- **FR-009**: System MUST treat `user_type` and `client_id` as **immutable after creation** except by
  a manager performing an explicit, audited correction, and MUST NEVER accept `user_type` or
  `client_id` from a normal request body (they are derived/validated server-side).
- **FR-010**: System MUST allow a **manager** to **create a client**, persisting it active, replacing
  the hand-run operator seed script as the supported creation path.
- **FR-011**: System MUST allow a **manager** to **soft-delete** a client by setting its **status to
  `suspended`** (the existing `clients.status` field), which MUST stop acceptance of new ingestion runs
  for it and block its client-side users from signing in, while **preserving all** of the client's
  documents, watchlists, runs, watermarks, and audit (no destructive delete); and MUST allow a manager
  to **reactivate** a suspended client (status → `active`).
- **FR-012**: System MUST NOT provide any path that **hard-deletes** a client (or cascades a client
  deletion into its watchlists/users/documents) in this spec; retention of data and audit is
  guaranteed.
- **FR-013**: System MUST allow a **staff admin** to create **client-side users** (`user_type =
  client`) bound to exactly one client, and MUST allow a client to have **several** such users.
- **FR-014**: System MUST allow a client-side user's **visibility scope** to be recorded as a
  **minimum severity** (from the existing `non-serious < serious < life-threatening` ordering) and/or
  a **set of that client's watchlists**, and MUST refuse adding a watchlist that belongs to a
  **different** client to that scope. The scope MUST be **explicitly chosen at creation** — either an
  explicit "full visibility of this client's reports" selection or a narrowing severity/watchlist
  scope; creation without an explicit choice MUST be refused. As a fail-safe, an **absent/empty scope
  MUST be interpreted as no visibility** (default-deny), never as full visibility — a client-user
  sees only what was deliberately granted (least-privilege).
- **FR-015**: System MUST ensure a client-side user can **never widen their own scope**; only a staff
  admin (or manager) may set or change a client-user's scope.
- **FR-016**: System MUST **store and manage** client-side user accounts, roles, and scope in this
  spec, while **deferring** client-side login and report-visibility **enforcement** to the later report
  spec; the stored schema MUST be sufficient that no later re-migration of these fields is required.
- **FR-017**: System MUST allow a **staff admin** to record, per client, a **regular** recipient email,
  a separate **urgent** recipient email (a **single address each**), and an **urgent severity
  threshold** (defaulting to the highest severity, life-threatening); the system MUST validate email
  format and refuse malformed addresses without changing stored values. (Multiple recipients per
  category is a documented future improvement.)
- **FR-018**: System MUST treat the per-client recipient emails and threshold as **storage only** in
  this spec (no sending), and MUST record for the later notification spec that **urgent/emergency
  reports are delivered immediately when written, not batched** on the normal cadence.
- **FR-019**: System MUST authorize **every request** from the user's **current stored state** (role,
  type, account active status, and, for client-users, their client's active status) rather than from
  claims embedded in a previously issued session token, so a demotion, deactivation, or client
  soft-delete takes effect on the user's **next** request. The access-token lifetime MUST be a single
  **~8-hour** session (no refresh token in this spec); at expiry the session ends and the user
  re-authenticates. Immediate revocation is provided by the per-request re-check above, not by the
  token lifetime, so the lifetime is defense-in-depth only.
- **FR-020**: System MUST keep the **audit log append-only**: no actor, including a manager superuser,
  may update or delete an existing audit entry.
- **FR-021**: System MUST **audit every sensitive write** via the existing domain-event/audit
  mechanism — client create/soft-delete/reactivate, staff create/role-change/deactivate, manager
  creation, client-user create/scope-change, and recipient-email change — attributing each to the
  acting staff user and recording the **target client** it acted upon. (Read/access auditing of
  cross-client views is deferred to the later report spec.)
- **FR-022**: System MUST refuse all **cross-client access by client-side users**: a client-user MUST
  only ever reach their own client's data, scoped further by their recorded severity/watchlist scope;
  the cross-client reach is exclusive to **staff** and is the deliberate, audited exception to the
  per-client wall.
- **FR-023**: System MUST deliver these changes as a new versioned **database migration** that does not
  break the spec-1/2/3/4 schema. Because this dev system has no production user data to preserve, the
  migration's data step performs a **full dev reset**: it clears `users` **and** the dependent seed
  rows that reference users by foreign key (ingestion runs and run-sources, and the audit rows authored
  by those users), so no foreign key is left dangling and no existing account silently gains
  cross-client staff access. Rows that carry **no** user foreign key (documents, watchlists,
  watermarks) MUST be preserved. The append-only audit guarantee (FR-020) governs runtime behavior and
  does NOT constrain this one-time foundation migration.
- **FR-024**: System MUST seed **exactly one bootstrap manager** as part of the reset, reading its email
  and initial password from **Vault** (into memory only — never written to disk or embedded in the
  migration). The seed MUST be **idempotent**: it creates the bootstrap manager only once (the Alembic
  data step applies once; any startup-seed implementation MUST create it only when no active manager
  exists), so re-running migrations, re-seeding Vault, or restarting the app never creates a duplicate
  manager. The bootstrap manager MUST be able to **change their password after first login** (a
  force-change-on-first-login is the intended hardening).
- **FR-025**: System MUST enforce that a user's login **email is globally unique** across all users
  (both staff and client-users); one email maps to exactly one account.
- **FR-026**: System MUST validate all inputs at the API boundary and reject malformed input with
  clear, non-leaking messages, leaving persisted state unchanged on rejection; unauthenticated callers
  MUST be refused before any role or tenant check.
- **FR-027**: System MUST allow a **staff admin** (or manager) to **activate or deactivate an individual
  watchlist** (the existing spec-3 `watchlists.is_active` flag) for **any** client via the acting-client
  model, **independently of the client's status**. A **deactivated watchlist** accepts no new ingestion
  runs but affects **only that watchlist**; a **suspended client** blocks new ingestion for **all** of
  its watchlists regardless of each watchlist's own flag (the two controls are orthogonal). Watchlist
  (de)activation is audited and obeys the same cross-client staff authorization as every other
  client-scoped action (FR-008). Reviewers and client-users MUST NOT (de)activate watchlists.

### Key Entities *(include if data involved)*

- **User (revised)**: An authenticatable person. Now carries a **`user_type`** (`staff` | `client`)
  distinct from **`role`**. A `staff` user has no owning client and a staff role
  (`manager`/`admin`/`reviewer`); a `client` user is bound to exactly one client and carries a
  client-user role plus a visibility scope. The model integrity rule: staff ⇒ no client; client ⇒
  exactly one client. **Login email is globally unique** across all users (staff and client alike).
- **Staff Role**: The authority level of an internal staff user — `manager` (superuser: client roster +
  all staff accounts), `admin` (client operations, client-user management, report-delivery config),
  `reviewer` (cross-client visibility + report approve/reject/edit permission). All staff roles act
  across all clients.
- **Client (revised)**: A pharma company workspace (from spec 3), now with a managed lifecycle
  (create / soft-delete / reactivate via its existing active flag) and new **report-delivery**
  attributes: a regular recipient email, an urgent recipient email, and an urgent severity threshold.
  Never hard-deleted in this spec.
- **Client-Side User**: A user belonging to one client (`user_type = client`), with a **visibility
  scope** = a minimum severity (reusing the `non-serious < serious < life-threatening` ordering)
  and/or a set of that client's watchlists. Created and scoped only by staff; can never widen its own
  scope. Scope is **explicitly chosen at creation** (full client visibility or a narrowing scope);
  an absent/empty scope means **no visibility** (least-privilege default-deny). Login +
  report-visibility enforcement deferred to the report spec.
- **Client-User Watchlist Scope**: The many-to-many link recording which of a client's watchlists a
  given client-side user may see, constrained so every linked watchlist belongs to that user's own
  client.
- **Acting-Client Context**: The explicit target client a staff user names for a client-scoped action;
  validated server-side and recorded in the audit trail as the action's target client (a staff actor
  has no home client of their own).
- **Audit Entry (reused, append-only)**: The existing audit record, now reliably carrying the **target
  client** for cross-client staff actions (the acting staff user has no home client); immutable, never
  updated or deleted by any role.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A manager can sign in (from the seeded bootstrap account), create a staff admin and a
  staff reviewer, and those staff can sign in — verified end-to-end with each created as a
  no-home-client staff user of the requested role.
- **SC-002**: A staff admin can perform a client-scoped action against **any** existing client by
  naming that client, and the action is recorded against the correct **target client** — verified
  across at least two different clients with correct attribution and zero implicit "all clients"
  access.
- **SC-003**: Zero privilege escalation: every attempt by a non-manager to create or promote a manager
  is refused, and every attempt to remove the last active manager is refused — verified with zero
  incorrect allows.
- **SC-004**: A manager can create a client, soft-delete it (after which new ingestion runs are refused
  and its client-users cannot sign in while all its data remains intact and staff-readable), and
  reactivate it — verified through the full lifecycle with no data loss.
- **SC-005**: Client-side users are stored bound to exactly one client with a severity/watchlist scope
  that is explicitly chosen at creation (an absent/empty scope means no visibility); a cross-client
  watchlist can never enter a client-user's scope, and a client-user can never widen their own scope —
  verified with zero incorrect allows.
- **SC-006**: Per-client regular and urgent recipient emails plus the urgent threshold are stored and
  audited, malformed emails are refused, and only admins/managers (never reviewers or client-users)
  can change them — verified with valid and invalid inputs.
- **SC-007**: A demoted, deactivated, or soft-deleted user loses the corresponding access on their
  **next** request without re-login, and existing session tokens confer no stale privilege; the
  access-token session lasts ~8 hours, after which the user re-authenticates — verified by changing
  state mid-session and observing the next request, and by token expiry behavior.
- **SC-008**: The audit log is append-only: no role, including manager, can alter or delete an audit
  entry, and every sensitive write in this spec produces exactly one audit entry naming the acting
  staff user and the target client — verified by attempted tampering and by per-action audit counts.
- **SC-009**: Multi-tenant isolation for **client-side users** is preserved with zero cross-client
  leakage (a client-user reaches only their own client's data), while staff cross-client access works
  as designed — verified across multiple clients with zero incorrect allows for client-users.
- **SC-010**: The authorization and account-write code paths meet the constitution's elevated coverage
  bar (95%+ on auth/database-write paths) and the overall suite stays at or above the 80% gate.
- **SC-011**: The migration applies cleanly on top of spec-4, clears prior user rows and their
  dependent referencing rows (ingestion runs/run-sources and user-authored audit rows) with no
  dangling foreign key, seeds exactly one bootstrap manager idempotently, preserves
  documents/watchlists/watermarks, and is reversible — verified by an up/down migration cycle that
  leaves the spec-1/2/3/4 schema intact and creates no duplicate manager on re-run.

## Assumptions

- **Backend/API only**: This spec delivers the revised user/authorization model, the client lifecycle,
  the client-user account+scope schema, and the per-client report-delivery configuration at the API
  level. Admin Console / client portal UIs and any report-viewing screens are a later frontend slice.
- **Constitution V is reframed, not weakened**: Principle V's guarantee — one client's data must never
  appear in another **client's** report or retrieval context — still holds in full for **client-side
  users**, who remain strictly isolated to their own client and scope. Internal **staff** are Pantera
  *operators*, not a competing tenant; their deliberate, audited cross-client access is an operator
  capability, not tenant leakage. The plan's Constitution Check must ratify this interpretation
  explicitly (and, if required, record a governance note/amendment); this spec assumes that
  reframing is accepted.
- **Reuse of spec-1/2/3/4 foundations**: The existing authentication (JWT, login rate limit, password
  policy), the domain-event dispatcher + passive append-only audit handler with the human-actor
  foreign key, the `clients`/`watchlists`/`watchlist_items` tables and their active flags, the
  `SeverityLevel` ordering, and the race-safe write pattern are reused. The `documents`/ingestion
  tables and their `client_id` columns are unchanged.
- **Wipe-and-reseed is acceptable**: This is a development system with no real production user data, so
  the migration drops existing user rows (and their dependent referencing rows) and seeds a single
  bootstrap manager rather than performing an ambiguous (and security-sensitive) backfill that could
  silently grant cross-client access. The bootstrap manager's email + initial password are read from
  **Vault** into memory (never hard-coded or written to disk), the seed is **idempotent** (created
  once; never duplicated on re-run/restart), and the password is **changeable after first login**.
- **Client-user enforcement is deferred**: Client-side login and the enforcement of a client-user's
  severity/watchlist scope against actual reports are owned by the later report spec; this spec stores
  and manages the accounts and scope so that later enforcement needs no schema change.
- **Report sending is deferred**: Per-client recipient emails and the urgent threshold are stored here;
  the notification spec performs the actual sending, honoring the recorded requirement that
  urgent/emergency reports are sent immediately when written rather than batched on cadence.
- **Acting-client context mechanism**: Staff name the target client per action via the API surface
  (e.g., a path parameter or explicit header), validated server-side; the precise transport is an
  implementation detail for the plan, but "default to all clients" is never permitted.
- **No new runtime dependency or required secret**: The change is expected to need no new runtime
  dependency and no new **required** Vault secret (so no CI secret-writer change); any new
  configuration is non-secret `Settings`.
- **Lean change surface**: This revision touches the auth/user and clients packages plus one additive
  migration; it does not alter the ingestion data tables or adapters delivered in spec 4.

### Future Improvements (out of scope here)

- **Refresh tokens**: A short-lived access token paired with a long-lived refresh token (so staff
  sessions feel continuous for days while access tokens rotate) is a documented future improvement;
  this spec uses a single ~8-hour access token with no refresh token.
- **Client-user sub-roles**: Finer roles within a client (beyond the severity/watchlist scope) are a
  documented future improvement.
- **Journal/author follow-up form**: A follow-up trigger that emails an empty structured form to the
  journal/author and returns the completed form to the client is a future improvement.
- **Multiple report recipients**: Holding several regular/urgent recipient addresses per client (rather
  than one each) is a documented future improvement.
- **Verified-domain allow-listing**: Restricting report recipient emails to verified client domains is
  a future hardening, out of scope here.
- **Read/access auditing of cross-client views**: Logging *who viewed which client's data* is deferred
  to the report spec, where the most sensitive readable artifact (finished reports) exists.
- **Cross-client platform-operator console**: A dedicated operator UI surface is a later frontend
  concern.
- **Policy engine (Casbin) for authorization**: This spec uses plain role guards + `acting_client` +
  scope checks, which is sufficient for the fixed 4-role model. Adopt an external policy engine (e.g.,
  Casbin RBAC-with-domains/ABAC) **only if** authorization later outgrows simple RBAC — concretely, when
  any of these appear: many distinct resource types with per-object ACLs, customer-configurable
  authorization policies, role delegation/sharing, or record-level grants beyond the
  severity/watchlist scope. Until then it adds a dependency + policy DSL for little gain (Constitution
  VI/VII). Deferred, not planned.
- **Row-Level Security (RLS) defense-in-depth**: DB-enforced tenant isolation (Postgres RLS) so a
  forgotten app-layer `client_id` filter cannot leak cross-tenant rows. A strong fit for this regulated,
  isolation-critical product, but it requires role-aware policies (staff cross-client vs client-user
  own-client) and careful async/pooled session-context plumbing (`SET LOCAL` per transaction +
  `BYPASSRLS` for migrations/seed) — too much to bundle with this foundation revision. **Folded into the
  Spec 12 security-hardening scope** (alongside Presidio redaction / NeMo guardrails), not built here.
