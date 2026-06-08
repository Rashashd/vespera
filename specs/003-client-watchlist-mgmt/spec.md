# Feature Specification: Client & Watchlist Management

**Feature Branch**: `003-client-watchlist-mgmt`

**Created**: 2026-06-06

**Status**: Draft

**Input**: User description: "client-watchlist-mgmt — clients, watchlists (drugs/keywords/MeSH), monitoring cadence, severity thresholds, custom keywords, cost budget (spec 3 of the Pantera 13-spec build order)"

## Clarifications

### Session 2026-06-06

- Q: Spec 3 names an "Admin Console UI" in the build plan, but specs 1–2 shipped backend-only (the React SPA is a separate container). What should spec 3 cover? → A: Backend/API only — deliver the client + watchlist management API, data model, and rules; defer the React Admin Console to a later dedicated frontend slice.
- Q: When a client reaches its configured monitoring cost budget, how should the platform behave? → A: Warn + soft cap — track spend against budget, alert at thresholds (e.g., 80%/100%), flag/pause *new* scheduled runs at 100% while letting in-flight/critical work finish; an admin can raise the budget to resume.
- Q: Can a client have one watchlist or several, and where does configuration live? → A: A client can have **multiple named watchlists** (1:many); each watchlist is independently configured with its own cadence, severity threshold + custom keywords, and cost budget. A single watchlist still holds many drugs/MeSH terms/keywords; multiple watchlists let a client *segment* monitoring into separately-scheduled, separately-budgeted groups.
- Q: Is the cost budget cumulative or per-period, and does it reset? → A: **Recurring monthly** budget — recorded spend accumulates within a calendar month and resets at the start of each month; a watchlist that was soft-capped at 100% auto-resumes at the next period reset without an admin manually raising the limit (raising the budget mid-period also clears the cap).
- Q: Should MeSH terms be validated against the controlled vocabulary in this spec? → A: No — store MeSH terms as **free-form strings** here; validation/resolution against the MeSH controlled vocabulary happens in the ingestion spec (spec 4) where the PubMed/MeSH adapters live. Keeps this config-only spec free of a MeSH-lookup dependency.
- Q: How is the severity threshold represented? → A: An ordered set of **named, ICH-aligned severity levels** (e.g., `non-serious` < `serious` < `life-threatening`); the threshold is the minimum level that triggers escalation. Auditable and categorical (per the constitution's transparent ICH-based severity rules), not an opaque numeric score.
- Q: How is a client uniquely identified? → A: A **system-generated stable ID** is the durable key every other entity references; the client's **human-readable name MUST be unique across the platform** (no two tenants share a name). Name uniqueness is a constraint layered on the surrogate key, cheap to relax later if needed.
- Q: Should per-watchlist custom *severity* keywords be in this spec? → A: No — **deferred to future improvements** (and specified in the triage spec, spec 8, where they are consumed). For v1 simplicity, spec 3 keeps only the severity **threshold** (named ICH level). Note: watchlist *retrieval* keywords (FR-003) are unaffected — those remain in scope and are the drug-related search terms used to find reports.
- Q: How is a watchlist removed — hard delete or soft delete? → A: **Soft-delete only** — deactivating a watchlist marks it inactive (stops being scheduled for monitoring) while preserving its data and audit trail, mirroring the client soft-delete behavior. No hard delete in this spec.
- Q: What is the canonical set of severity levels and the default threshold? → A: Exactly three ordered levels — `non-serious` < `serious` < `life-threatening`. Default threshold is **`serious`** (escalate serious-and-above), consistent with the constitution's fail-safe-toward-escalation principle.
- Q: What is the supported cadence set and default? → A: `daily`, `weekly`, `monthly`; default **`weekly`** when unset.
- Q: Is the budget warning threshold fixed or configurable? → A: **Platform-fixed at 80%** for v1 (admin-configurable threshold is a possible future improvement).
- Q: How is the monthly budget period defined? → A: **Calendar month in UTC** — spend accumulates from 00:00 UTC on the first of the month and resets at the start of the next calendar month (UTC).
- Q: How is an empty watchlist handled? → A: **Rejected** — a watchlist MUST contain at least one item (drug, MeSH term, or keyword) to be created or activated; an attempt to create/activate an empty watchlist fails with a clear validation message.

## User Scenarios & Testing *(mandatory)*

Pantera monitors medical literature for adverse drug events on behalf of its business customers (clients). Spec 1 established the `client_id` tenant boundary as a bare value; spec 2 added authenticated users scoped to a client. This feature gives a client its **first-class identity** and the **configuration that drives all later monitoring**: which drugs and topics to watch (including the search keywords used to find reports), how often to check, the severity level at which a signal warrants escalation, and how much they are willing to spend. Nothing in this spec ingests literature or produces reports — it defines *what each client wants monitored and under what limits*, so that specs 4–13 (ingestion, triage, drafting, scheduling) have a configuration to act on. This spec is **backend/API only**; the React Admin Console that surfaces this configuration is a later slice.

### User Story 1 - Establish a client (tenant) record (Priority: P1)

A platform operator (or an admin acting within the bounds of their own client) needs a real client record to exist so that users, watchlists, budgets, and all downstream monitoring data have a concrete tenant to belong to. Until now `client_id` was just a number with no backing row; this story creates the `clients` table and the client lifecycle (create, view, update status).

**Why this priority**: Every other entity in this spec and in later specs references a client. Without a first-class client record, watchlists and budgets have nothing to attach to and the existing `client_id` on users remains an unenforced integer. This is the irreducible foundation of the spec.

**Independent Test**: Create a client record, confirm it is retrievable with its attributes, and confirm that an existing user's `client_id` resolves to this client. Confirm a deactivated/suspended client is marked as such without deleting its data.

**Acceptance Scenarios**:

1. **Given** no client exists for a tenant, **When** an authorized operator creates a client with its identifying details, **Then** the client record exists, is retrievable, and is in an active state.
2. **Given** an existing client, **When** its profile attributes are updated, **Then** the changes are persisted and the action is recorded in the audit log.
3. **Given** an existing client with users and configuration, **When** it is suspended/deactivated, **Then** the client is flagged inactive and its data is preserved (no destructive delete), and monitoring configuration tied to it is treated as inactive.
4. **Given** the existing `users` table, **When** the client record exists, **Then** every user's `client_id` references a real client and cannot reference a non-existent client.

---

### User Story 2 - Define one or more watchlists of what to monitor (Priority: P1)

An admin defines, for their own client, one or more **named watchlists** — each a distinct monitoring group (e.g., "Oncology portfolio", "Legacy products"). Each watchlist holds one or more **drugs** (active substances/products), associated **MeSH terms** for precise literature targeting, and free-text **keywords**. A watchlist is the search intent that drives every later ingestion and retrieval cycle; multiple watchlists let a client segment monitoring into separately-configured groups.

**Why this priority**: A client with no watchlist has nothing to monitor — the watchlist is the core deliverable of this spec and the direct input to the ingestion spec (spec 4). It ships alongside the client record because together they form the minimal "a client and what they want watched" MVP.

**Independent Test**: As an admin, create two named watchlists for the admin's client, each containing at least one drug, one MeSH term, and one keyword; retrieve them and confirm each watchlist's items are present, distinct, and scoped to that client only; confirm an admin of another client cannot see or edit them.

**Acceptance Scenarios**:

1. **Given** an authenticated admin, **When** they create a named watchlist with drugs, MeSH terms, and keywords for their own client, **Then** the watchlist is stored, scoped to that client, has a client-unique name, and is retrievable.
2. **Given** a client with an existing watchlist, **When** the admin creates an additional named watchlist, **Then** both watchlists coexist independently under the same client and can be listed.
3. **Given** an existing watchlist, **When** the admin adds or removes drugs, MeSH terms, or keywords, **Then** that watchlist reflects the change without affecting the client's other watchlists, and the change is audit-logged.
4. **Given** an admin of client A, **When** they attempt to read or modify a watchlist belonging to client B, **Then** the request is refused and no client B data is revealed.
5. **Given** a watchlist, **When** a duplicate drug/keyword/MeSH term is added, **Then** the watchlist does not create a redundant duplicate entry (idempotent membership).
6. **Given** an admin, **When** they create a watchlist whose name duplicates an existing watchlist of the same client, **Then** the request is rejected with a clear validation message (names are unique per client).
7. **Given** a reviewer (non-admin), **When** they attempt to create or modify a watchlist, **Then** the request is refused as forbidden, but they may view their client's watchlist configuration.

---

### User Story 3 - Configure monitoring cadence per watchlist (Priority: P2)

An admin sets how often each watchlist is checked for new literature (e.g., daily, weekly), so that later scheduling (spec 11) knows when to run each watchlist's monitoring cycle. Different watchlists of the same client may use different cadences.

**Why this priority**: Cadence governs *when* monitoring happens. The watchlist (P1) defines *what* is monitored and is demonstrable on its own with a sensible default cadence; configurable cadence is the next layer of operational value, so it is P2.

**Independent Test**: Set two watchlists of the same client to different supported cadences, retrieve them, and confirm each stored cadence reflects its choice independently; confirm an unsupported cadence value is rejected with a clear validation error; confirm a default cadence applies to a watchlist when none is set.

**Acceptance Scenarios**:

1. **Given** a watchlist, **When** an admin sets a supported cadence on it, **Then** the cadence is stored on that watchlist and retrievable for use by later scheduling, without affecting other watchlists.
2. **Given** a watchlist with no explicit cadence, **When** it is read, **Then** a documented default cadence applies.
3. **Given** an admin, **When** they submit an unsupported or malformed cadence, **Then** it is rejected with a clear validation message and the prior cadence is unchanged.

---

### User Story 4 - Configure a severity threshold per watchlist (Priority: P2)

An admin configures, per watchlist, the **severity threshold** — the named ICH-aligned level at which a detected adverse-event signal warrants attention/escalation. This feeds the constitution's transparent, auditable severity rules used in later triage (spec 8). (Per-watchlist custom *severity* keywords are deferred to future improvements / spec 8; they are not part of this spec.)

**Why this priority**: The severity threshold tailors monitoring sensitivity per watchlist and is required before triage can apply tailored rules, but the monitoring foundation (client + watchlist) is demonstrable without it using the platform default level. It is therefore P2.

**Independent Test**: Set a watchlist's severity threshold to a valid named level; retrieve it and confirm it is stored and scoped to that watchlist/client; confirm validation rejects a value outside the level set; confirm the documented default level applies when unset.

**Acceptance Scenarios**:

1. **Given** a watchlist, **When** an admin sets a severity threshold to a valid named level, **Then** it is stored on that watchlist and retrievable for later triage rules.
2. **Given** a watchlist with no explicit severity threshold, **When** it is read, **Then** the documented platform-default level applies.
3. **Given** an admin, **When** they submit a value outside the defined level set, **Then** it is rejected with a clear validation message and the prior value is unchanged.

---

### User Story 5 - Set and enforce a monitoring cost budget per watchlist (Priority: P3)

An admin sets a monitoring **cost budget** for each watchlist. The platform tracks each watchlist's spend against its budget, warns as thresholds are approached, and **soft-caps** new scheduled monitoring for that watchlist at 100% (pausing *new* runs while letting in-flight/critical work finish), until an admin raises that watchlist's budget. One watchlist reaching its cap does not pause the client's other watchlists.

**Why this priority**: Cost control protects against runaway spend but is not required for the core "configure what to monitor" value; it is a guardrail layered on top, and the actual spend it meters is produced by later specs. It is P3 — valuable for production operation, demonstrable last.

**Independent Test**: Set a watchlist's budget; simulate recorded spend crossing the warning threshold and the 100% limit; confirm a warning state is raised at the warning threshold, that new monitoring runs for that watchlist are flagged/paused at 100%, that in-flight work is not abruptly killed, that a sibling watchlist under budget is unaffected, and that raising the budget clears the paused state.

**Acceptance Scenarios**:

1. **Given** a watchlist with a configured budget, **When** recorded spend reaches the warning threshold (e.g., 80%), **Then** a warning state is raised/visible for that watchlist without pausing monitoring.
2. **Given** a watchlist whose recorded spend reaches 100% of budget, **When** the next scheduled monitoring run is due, **Then** new runs for that watchlist are flagged/paused (soft cap) while any in-flight or critical work is allowed to complete, and the client's other watchlists are unaffected.
3. **Given** a watchlist paused at its budget limit, **When** an admin raises that watchlist's budget above its current spend, **Then** the paused state clears and monitoring of that watchlist may resume.
4. **Given** budget enforcement, **When** a watchlist's spend is below its budget, **Then** monitoring proceeds without restriction.
5. **Given** a watchlist soft-capped at month-end, **When** the new monthly period begins, **Then** its recorded spend resets to zero and the paused state clears automatically without admin action.

---

### Edge Cases

- **Client referenced before it exists**: Existing users carry a `client_id`; introducing the `clients` table must reconcile existing `client_id` values to real client rows without orphaning users or breaking the spec-2 audit FK.
- **Empty watchlist**: Creating or activating a watchlist with no drugs/keywords/MeSH terms is rejected with a clear validation message; a watchlist must hold at least one item to exist as active.
- **Duplicate watchlist name**: Creating a watchlist whose name collides with an existing watchlist of the same client must be rejected (names are unique per client); the same name MAY be reused across different clients.
- **Cross-tenant configuration access**: An admin of one client must never read, edit, or even enumerate another client's watchlists, severity config, or budgets.
- **Deactivated client**: All watchlists belonging to a suspended/deactivated client must be treated as inactive by later specs and not scheduled for monitoring.
- **Per-watchlist isolation within a client**: A change to one watchlist's items, cadence, severity, or budget (including a budget soft-cap) must not affect the client's other watchlists.
- **Watchlist deactivation**: A deactivated (soft-deleted) watchlist is preserved with its data and audit trail but is excluded from monitoring/scheduling; reactivation, if supported, restores it without data loss. No hard delete occurs.
- **Conflicting/duplicate watchlist entries**: Adding the same drug, MeSH term, or keyword twice must not create duplicates; removing a non-existent entry must fail gracefully.
- **Out-of-range or malformed configuration**: Unsupported cadence, out-of-range severity threshold, or negative/zero/invalid budget values must be rejected with clear validation, leaving prior state intact.
- **Budget set below current spend**: Setting a watchlist's budget at or below its already-recorded current-period spend must immediately place that watchlist in the soft-capped state rather than retroactively erroring.
- **Audit continuity**: Every create/update/deactivate on clients and configuration must produce an audit-log entry attributed to the acting admin (reusing the spec-2 human-actor mechanism).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a first-class **client (tenant)** record with at least: a system-generated stable identifier (the durable key all other entities reference), a human-readable name/identifying details, and an active/suspended status. The client name MUST be unique across the platform (no two clients share a name), rejected with a clear validation message on collision. Every existing and future user's `client_id` MUST reference a real client record; the system MUST reconcile existing `client_id` values when the client record is introduced, without orphaning users or breaking the spec-2 audit foreign key.
- **FR-002**: System MUST allow an authorized actor to create, retrieve, and update a client record, and to suspend/deactivate a client without destructively deleting its data; deactivation MUST mark the client (and its configuration) inactive for downstream monitoring.
- **FR-003**: System MUST allow an `admin` to define one or more **named watchlists** for their own client, each consisting of **drugs** (active substances/products), **MeSH terms**, and free-text **keywords**, and to add/remove each of these item types after creation. A watchlist name MUST be unique within its client (the same name MAY be reused across different clients).
- **FR-004**: System MUST scope every client record and all watchlist/cadence/severity/budget configuration to a single client; all read and write operations MUST be restricted to the acting admin's own client, and no operation may read, modify, or enumerate another client's configuration. Cross-tenant access MUST be refused (per the constitution's multi-tenant isolation principle).
- **FR-005**: System MUST treat watchlist membership as idempotent: within a watchlist, adding a drug, MeSH term, or keyword already present MUST NOT create a duplicate entry; removing an absent entry MUST fail gracefully without error state corruption.
- **FR-006**: System MUST allow an `admin` to set a **monitoring cadence** per watchlist from exactly the supported set `{daily, weekly, monthly}`, MUST reject any other/malformed cadence value with a clear validation message, and MUST apply the default cadence `weekly` when a watchlist has none set.
- **FR-007**: System MUST allow an `admin` to set a per-watchlist **severity threshold** to one of exactly three ordered, ICH-aligned named levels: `non-serious` < `serious` < `life-threatening`; the threshold is the minimum level that triggers escalation. The system MUST reject any value outside this set and MUST apply the platform-default level `serious` (escalate serious-and-above) when unset.
- **FR-008**: Per-watchlist custom *severity* keywords are **OUT OF SCOPE** for this spec (deferred to future improvements; specified in the triage spec, spec 8, where they are consumed). This spec stores only the per-watchlist severity threshold (FR-007). This deferral does not affect watchlist *retrieval* keywords (FR-003), which remain in scope.
- **FR-009**: System MUST allow an `admin` to set a per-watchlist **recurring monthly monitoring cost budget**, rejecting invalid (e.g., negative or non-numeric) values with a clear validation message. The period is a **calendar month in UTC**: recorded spend accumulates from 00:00 UTC on the first of the month and MUST reset to zero at the start of the next calendar month (UTC).
- **FR-010**: System MUST track recorded monitoring spend against each watchlist's budget and raise a **warning state** for that watchlist when its spend reaches the platform-fixed warning threshold of **80%** of budget, without pausing monitoring. (The threshold is fixed in v1; making it admin-configurable is a possible future improvement.)
- **FR-011**: System MUST **soft-cap** a watchlist's monitoring when its recorded spend reaches 100% of its budget: new scheduled monitoring runs for that watchlist MUST be flagged/paused while any in-flight or critical work is allowed to complete; the cap MUST NOT abruptly terminate work in progress, and MUST NOT pause the client's other watchlists.
- **FR-012**: System MUST clear a watchlist's soft-capped/paused state and allow its monitoring to resume when EITHER an `admin` raises that watchlist's budget above its current recorded spend, OR a new monthly period begins (spend resets to zero). Setting a budget at or below current spend MUST place that watchlist into the soft-capped state without retroactive error.
- **FR-013**: System MUST enforce that only an `admin` may modify their own client record (e.g., rename) and create or modify any of that client's configuration (watchlists and their cadence, severity, budget); a `reviewer` MAY view their own client's record, watchlists, and configuration but MUST NOT modify them; unauthenticated callers MUST be refused before any tenant check. (Creating or suspending a *client/tenant* itself is a platform-operator action, not an admin API action — see FR-002 and §Assumptions.)
- **FR-014**: System MUST validate all configuration inputs at the API boundary and MUST reject malformed input with clear, non-leaking validation messages, leaving prior persisted state unchanged on rejection.
- **FR-015**: System MUST record every create/update/suspend action on clients and on watchlist/cadence/severity/budget configuration to the existing audit log, attributed to the acting admin via the spec-2 human-actor mechanism.
- **FR-016**: System MUST **reject** creation or activation of an **empty watchlist**: a watchlist MUST contain at least one item (drug, MeSH term, or keyword) to be created or made active, returning a clear validation message otherwise, so downstream specs never receive a schedulable watchlist with nothing to monitor.
- **FR-017**: System MUST allow an `admin` to list all watchlists belonging to their own client and to retrieve, rename, and **deactivate** (soft-delete) an individual watchlist. Deactivation MUST mark the watchlist inactive (no longer scheduled for monitoring) while preserving its data and audit trail; there is no hard delete in this spec. Deactivating one watchlist MUST NOT affect the client's other watchlists, and the action MUST be audit-logged.
- **FR-018**: New schema introduced by this spec MUST follow the established database conventions (carry `client_id` where applicable, include required indexes) and MUST be delivered as a new versioned migration that does not break the spec-1 baseline or spec-2 schema.

### Key Entities *(include if feature involves data)*

- **Client (Tenant)**: The organization Pantera monitors on behalf of. Key attributes: system-generated stable identifier (durable key referenced by users, watchlists, audit rows), platform-unique human-readable name, active/suspended status. Owns one or more watchlists; every user (spec 2) belongs to exactly one client. The first-class backing for the `client_id` boundary introduced in spec 1.
- **Watchlist**: A named monitoring group for a client — the set of subjects to watch, plus its own cadence, severity configuration, and cost budget. Composed of **Drugs**, **MeSH terms**, and **Keywords**. A client may have many watchlists (1:many); each watchlist's name is unique within its client. Belongs to exactly one client; is the primary input to the ingestion spec (spec 4).
- **Drug / Active Substance**: A product or active substance the client wants monitored for adverse events; a member of a specific watchlist.
- **MeSH Term**: A medical subject heading associated with a watchlist for precise literature targeting. Stored as free-form text in this spec; resolution/validation against the MeSH controlled vocabulary occurs in the ingestion spec (spec 4).
- **Keyword**: A free-text term included in a watchlist's search intent (distinct from severity custom keywords).
- **Monitoring Cadence**: How often a given watchlist is checked, from the set `{daily, weekly, monthly}` (default `weekly`); consumed by later scheduling (spec 11). Set per watchlist.
- **Severity Threshold**: A watchlist's escalation **threshold** — one of exactly three ordered, ICH-aligned named levels `non-serious` < `serious` < `life-threatening` (default `serious`); the minimum level that triggers escalation. Feeds the transparent severity rules used in later triage (spec 8). Scoped per watchlist. (Per-watchlist custom *severity* keywords are deferred to spec 8 and are not modeled here.)
- **Cost Budget**: A watchlist's **recurring monthly** (calendar month, UTC) monitoring spend limit with a fixed 80% warning threshold and a current-period recorded-spend value; drives the warn → soft-cap behavior for that watchlist independently. Spend accumulates within the UTC calendar month and resets at the next period. The spend it meters is produced by later specs; this spec defines the budget, the period/reset, the threshold, and the resulting states.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A client record can be created and retrieved with its full attribute set, attempting to create a second client with an already-used name is rejected, and 100% of existing and new users resolve to a real client (no orphaned `client_id`).
- **SC-002**: An admin can define multiple complete named watchlists (each with at least one drug, one MeSH term, one keyword) under one client, and have each persisted and retrievable independently, scoped to their client; a duplicate watchlist name within the client is rejected.
- **SC-003**: Zero cross-tenant access: no admin or reviewer can read, modify, or enumerate another client's clients, watchlists, severity config, or budgets — verified across multiple clients with zero incorrect allows.
- **SC-004**: For every configuration type (cadence, severity threshold, budget), valid inputs are accepted and out-of-range/malformed inputs are rejected with a clear message and no change to prior state — verified per watchlist with both valid and invalid cases.
- **SC-005**: Adding a duplicate item within a watchlist never increases the stored item count for that type (idempotent membership), verified by repeated additions.
- **SC-006**: When a watchlist's recorded spend crosses its warning threshold, a warning state is observable for that watchlist without monitoring being paused; when it reaches 100%, that watchlist's new runs are flagged/paused while in-flight work is not terminated and sibling watchlists are unaffected; raising the watchlist's budget clears the paused state — all verified by simulating spend.
- **SC-007**: Only admins can modify client configuration; every reviewer or unauthenticated modification attempt is refused, while reviewers can still view their own client's configuration — zero incorrect allows or denies.
- **SC-008**: Every create/update/suspend on clients and configuration produces exactly one audit-log entry attributed to the correct acting admin.
- **SC-009**: The configuration write code paths meet the constitution's elevated coverage bar (95%+ on database-write paths), and the overall suite stays at or above the 80% gate.

## Assumptions

- **Backend/API only**: This spec delivers the client + watchlist management data model, rules, and API surface. The React Admin Console that presents this configuration is deferred to a later dedicated frontend slice; "Admin Console" in the build plan is satisfied at the API level here.
- **Reuse of spec-1/spec-2 foundations**: The `client_id` tenant boundary (spec 1), the audit log with the human-actor foreign key (spec 2), and the role guards (`require_admin`, `require_reviewer`, `current_active_user`) are reused; this spec adds the `clients` table, the `watchlists` table, and per-watchlist configuration tables, and MAY add/strengthen the `users.client_id` foreign key.
- **Watchlist multiplicity**: A client may own multiple named watchlists (1:many), and cadence, severity configuration, and cost budget are owned **per watchlist**, not per client. This lets a client segment monitoring (e.g., by drug portfolio) into separately-scheduled, separately-budgeted groups. Watchlist names are unique within a client.
- **No literature ingestion or spend generation here**: This spec defines *configuration and limits*; the ingestion, triage, drafting, and scheduling that consume the watchlist/cadence/severity and that generate actual cost are later specs (4, 8, 9, 11). The cost budget meters spend recorded elsewhere; this spec owns the budget, thresholds, and warn/soft-cap states, not the metering of LLM/API usage itself.
- **MeSH terms are free-form here**: Watchlist MeSH terms are stored as plain strings in this spec; they are validated/resolved against the MeSH controlled vocabulary in the ingestion spec (spec 4), so spec 3 takes on no MeSH-lookup or external-vocabulary dependency.
- **Severity model alignment**: The named ICH-aligned threshold level feeds the constitution's transparent severity rules; the precise ICH bucketing/scoring logic is exercised in the triage spec (spec 8). Here we store only the watchlist's threshold level, not the full triage algorithm. The canonical ordered list of severity levels is a small documented enum established in this spec and reused by spec 8.
- **Custom severity keywords deferred (future improvement)**: The constitution's "ICH criteria + per-client custom keywords" severity model is satisfied in two parts: this spec ships the per-watchlist threshold (and the standard ICH levels), while the per-client/per-watchlist custom *severity* keywords are deferred to the triage spec (spec 8) that consumes them, keeping v1 simple. This is a deliberate sequencing decision, not a removal — the custom-keyword capability still lands before triage ships. Watchlist *retrieval* keywords (FR-003), used to find reports, are a separate, in-scope feature.
- **Supported cadence set and defaults**: The cadence set is exactly `{daily, weekly, monthly}` with default `weekly`; finer-grained or cron-style scheduling is an implementation/scheduling-spec concern (spec 11).
- **Soft-cap semantics**: "In-flight/critical work" is allowed to finish at the 100% cap; the precise definition of an atomic monitoring "run" is refined when scheduling (spec 11) exists. This spec defines the budget states and the rule that new runs pause while running work completes.
- **Budget period**: The cost budget is a **recurring monthly** limit on a **calendar month in UTC**; recorded spend resets at the start of each UTC calendar month and a soft-capped watchlist auto-resumes at reset. The warning threshold is platform-fixed at 80%. The exact reset trigger mechanism (e.g., scheduled job) is a scheduling/implementation concern (spec 11); this spec owns the period semantics, the 80% threshold, and the reset/auto-resume rule.
- **Secrets and config discipline**: Any new secrets go to Vault via the established path; non-secret settings live in `Settings`. No client configuration is stored in environment files.
- **Operator vs admin client creation**: Bootstrapping a brand-new client (tenant onboarding) is performed by a platform operator path; ongoing per-client configuration is performed by that client's `admin`. In this spec the operator surface is an **operator-run CLI script** (`scripts/seed_client.py`), consistent with the spec-2 seed-script precedent. A dedicated **platform-operator account + cross-tenant client-management console** (a real authenticated operator login, likely via the existing `is_superuser` flag, paired with the deferred React Admin Console) is intentionally **deferred to its own later spec** — it is a cross-tenant capability that deserves its own security review and is out of scope here.
