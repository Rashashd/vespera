# Feature Specification: Platform Foundation & Security Skeleton

**Feature Branch**: `001-platform-foundation`

**Created**: 2026-06-05

**Status**: Draft

**Input**: User description: "Platform foundation and security skeleton: docker-compose with Vault, app lifespan and startup checks, secret loading, health endpoint, database baseline and indexes, security headers, error tracking, structured logging, and in-process domain event dispatcher"

## Overview

This feature establishes the operational and security spine that every later Pantera
feature depends on: a one-command local stack, a managed-secret bootstrap, fail-fast
startup validation, shared singleton resources, a liveness probe, baseline persistence
with multi-tenant-ready indexing, structured observability, and an in-process domain-event
backbone with a passive audit listener. It delivers no end-user pharmacovigilance
capability on its own; its value is that it makes every subsequent feature safe to build,
boot, observe, and audit. The primary actors are the **Platform Operator** (who deploys
and runs the stack) and the **Developer** (who builds features on top of it).

## Clarifications

### Session 2026-06-05

- Q: If the audit-log write fails while the originating state change is being committed, what happens? → A: Atomic — the audit entry is written in the same database transaction as the state change; if the audit write fails, the whole operation rolls back.
- Q: How deep should the health endpoint's checks be? → A: Shallow liveness only — confirms the process is up and serving; does not re-check the database/cache per call (dependency health is enforced once at startup).
- Q: Does this feature include the background worker, and to what extent? → A: Include the worker skeleton only — its container plus the shared startup/shutdown bootstrap (secrets, engine, cache) loaded identically to the app, with no job functions or cron (those are spec #11).
- Q: Should foundation wire distributed (OpenTelemetry/Langfuse) tracing now? → A: Defer — foundation provides structured logging + Sentry error tracking only; distributed tracing is added with the pipeline/agent features.

### Session 2026-06-05 (cont.)

- Q: How should the audit log represent the actor for system-initiated (non-human) events? → A: Use a reserved system-actor identity plus an explicit actor_type discriminator (human/system); actor_id is never null.
- Q: What access control and detail level should the health endpoint have? → A: Public and minimal — unauthenticated, returns only a bare status with no internal/diagnostic details.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Stack boots safely or refuses to start (Priority: P1)

A Platform Operator clones the repository and starts the full stack with a single command.
The application loads all required secrets from the secrets manager **before** initializing
any resource, validates that its critical dependencies (secrets manager, relational
database, cache) are reachable, and only then begins serving. If any required secret is
missing or any critical dependency is unreachable, the application refuses to boot and
reports a clear, actionable error instead of starting in a partially working state.

**Why this priority**: A platform that can silently start without secrets or without a
database is unsafe in a regulated domain. Fail-fast startup is the foundation that makes
every later feature trustworthy.

**Independent Test**: From a fresh clone, run the stack up command with all dependencies
healthy and confirm the service reaches a serving state; then disable each dependency in
turn (secrets manager, database, cache) and confirm the service refuses to boot with a
specific error each time.

**Acceptance Scenarios**:

1. **Given** a fresh clone with secrets written to the secrets manager and all services
   healthy, **When** the operator starts the stack, **Then** the application loads secrets,
   passes all startup checks, and the liveness probe reports healthy.
2. **Given** the secrets manager is unreachable or cannot authenticate, **When** the
   application starts, **Then** it aborts startup with an error naming the secrets manager
   as the cause and does not begin serving requests.
3. **Given** the relational database (or cache) is unreachable, **When** the application
   starts, **Then** it aborts startup with an error naming the unreachable dependency.
4. **Given** the application has started successfully, **When** it shuts down, **Then** all
   shared resources (database engine, cache connection) are released cleanly.

---

### User Story 2 - Secrets never appear in the repository, files, or logs (Priority: P1)

A security stakeholder must be able to confirm that no real secret value (API key, database
URL, cache URL, service credential) exists anywhere in the repository, its history, any
configuration file, or any log or trace output. All real secrets live only in the secrets
manager and are fetched into memory at startup; the only bootstrap values present outside
the secrets manager are the secrets-manager address and access token, supplied through the
container environment rather than a committed file.

**Why this priority**: Secret leakage is a catastrophic, often irreversible failure in a
life-sciences B2B context. The foundation must make the secure path the only path.

**Independent Test**: Run a secret-scanning tool over the working tree and full git history
and confirm zero findings; trigger error and request logging and confirm no secret value
appears in any log line or trace.

**Acceptance Scenarios**:

1. **Given** the repository and its full history, **When** a secret scan runs, **Then** it
   reports zero secret values.
2. **Given** the running application emits logs and error reports, **When** those outputs
   are inspected, **Then** no secret value or patient identifier appears in any of them.
3. **Given** a developer attempts to commit a file containing a secret-like value, **When**
   the pre-commit check runs, **Then** the commit is blocked.

---

### User Story 3 - Operators can confirm liveness and observe failures (Priority: P2)

A Platform Operator (and the hosting platform's automated probes) can query a lightweight
health endpoint to confirm the service is alive, every unhandled exception is captured by
an error-tracking service, and every log line is structured JSON carrying tenant and
finding context so failures can be traced to a specific client and finding without
exposing sensitive data.

**Why this priority**: Without a liveness probe and centralized error capture, outages and
silent failures go unnoticed — directly relevant to the "worker dies silently at 3am"
risk. Important, but the stack can be built and demoed before full observability is wired,
so it sits just below the fail-fast and secret-safety guarantees.

**Independent Test**: Call the health endpoint and confirm a fast healthy response; raise
an unhandled exception and confirm it appears in the error-tracking service; inspect logs
and confirm they are structured JSON with tenant/finding fields and no sensitive data.

**Acceptance Scenarios**:

1. **Given** the application is serving, **When** the health endpoint is called, **Then** it
   returns a healthy status quickly enough to satisfy the hosting platform's liveness probe.
2. **Given** an unhandled exception occurs while serving a request, **When** the request
   fails, **Then** the exception is recorded in the error-tracking service.
3. **Given** any log line is produced during request handling, **When** it is inspected,
   **Then** it is structured JSON and includes the relevant tenant (`client_id`) and, where
   applicable, `finding_id` context.

---

### User Story 4 - State-changing actions are auditable through domain events (Priority: P2)

When any module performs a significant state change, it raises a typed domain event to an
in-process dispatcher rather than calling other modules directly. A passive audit-log
listener, registered at startup, records every dispatched event into an append-only audit
log. This gives every later feature a consistent, decoupled way to become auditable.

**Why this priority**: The audit trail is a regulatory requirement and the decoupling
mechanism the rest of the system relies on. It must exist before report, approval, and
erasure features are built, but slightly after the boot-safety and secret guarantees.

**Independent Test**: Register a sample event type and handler, dispatch an event, and
confirm a corresponding append-only audit-log entry is created with actor, action, target,
event type, and timestamp.

**Acceptance Scenarios**:

1. **Given** the dispatcher and audit listener are registered at startup, **When** a module
   dispatches a domain event, **Then** exactly one audit-log entry is recorded for it.
2. **Given** an audit-log entry exists, **When** the system runs normal operations, **Then**
   the entry is never automatically deleted or mutated.
3. **Given** a module needs to notify another module of a state change, **When** it does so,
   **Then** it emits a domain event rather than importing and calling the other module
   directly.

---

### User Story 5 - Persistence baseline is multi-tenant-ready and migration-managed (Priority: P3)

The relational store starts from a versioned baseline in which every tenant-scoped table
carries a `client_id` column and the high-traffic lookup columns are indexed. All schema
changes are applied through migration files, and every API response carries standard
security headers.

**Why this priority**: Getting tenant scoping and indexing into the schema baseline avoids
costly retrofits later, but it can follow the boot, secret, observability, and audit
guarantees since no business tables are populated yet.

**Independent Test**: Apply the baseline migration to an empty database and confirm the
expected tables, the `client_id` column on tenant-scoped tables, and the required indexes
exist; send any request and confirm the security headers are present on the response.

**Acceptance Scenarios**:

1. **Given** an empty database, **When** the baseline migration is applied, **Then** the
   audit-log and tenant-scoped baseline tables exist with a `client_id` column where
   applicable and indexes on tenant, external-id, status, and deadline columns.
2. **Given** a later schema change is needed, **When** it is introduced, **Then** it is
   delivered as a new migration file rather than an ad-hoc change.
3. **Given** any HTTP response from the application, **When** its headers are inspected,
   **Then** the standard security headers (transport security, framing, content-type, and
   content-security policy) are present.

---

### Edge Cases

- **Secrets manager reachable but missing a required key** → startup aborts and names the
  missing key; the app does not start with empty credentials.
- **Secrets manager available at boot but drops mid-run** → already-loaded secrets remain in
  memory; the app keeps serving and does not re-read secrets from disk (there is no disk
  copy).
- **Partial dependency availability** (e.g., database up, cache down) → startup aborts; the
  app never serves in a half-initialized state.
- **Liveness probe called during startup before checks complete** → the application is not
  yet serving, so the endpoint is simply unavailable (not yet routable) rather than
  returning a false healthy status; it begins responding healthy only once startup completes
  successfully.
- **Model-artifact hash validation** is part of startup checks but only enforced once model
  artifacts exist (delivered with the modelserver feature); until then it is a no-op that
  must not block boot.
- **Duplicate event dispatch** → each dispatched event yields exactly one audit entry; the
  dispatcher does not silently drop or double-count events.
- **Audit write fails during a state change** → the enclosing transaction is rolled back so
  no un-audited state change is committed; the caller receives an error.
- **Log line that would contain a patient identifier or secret** → the value is excluded or
  redacted before the line is written.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST fetch all real secrets from the secrets manager into memory as
  the first startup step, before any other resource is initialized.
- **FR-002**: The system MUST refuse to start if the secrets manager cannot be reached or
  authenticated, or if any required secret is absent, reporting a clear cause naming the
  failure. For this feature the **required** secrets are the relational database URL, the
  cache (Redis) URL, and at least one language-model provider key (Anthropic or OpenAI);
  service credentials for downstream services (e.g., modelserver, guardrails) are loaded by
  the same mechanism but only become required once those services are introduced.
- **FR-003**: The system MUST NOT store any real secret value in the repository, git
  history, any committed or on-disk file, or any log or trace; only the secrets-manager
  address and access token may be supplied via the container environment.
- **FR-004**: The system MUST validate that critical dependencies (relational database and
  cache) are reachable at startup and refuse to boot if any is unavailable.
- **FR-005**: The system MUST validate configured model-artifact integrity (content hashes)
  at startup when such artifacts are present, without blocking boot when they are not yet
  present.
- **FR-006**: The system MUST initialize shared resources (database engine, cache
  connection, language-model client) exactly once at startup and release them cleanly at
  shutdown.
- **FR-007**: The system MUST expose a lightweight health endpoint suitable for an automated
  liveness probe that confirms the process is up and serving. The endpoint performs a
  shallow liveness check only and MUST NOT re-check the database or cache on each call;
  dependency health is enforced once at startup (FR-004). The endpoint MUST be publicly
  accessible without authentication and MUST return only a bare status with no internal or
  diagnostic detail (no versions, dependency states, or build info).
- **FR-008**: The system MUST emit all logs as structured JSON, binding tenant (`client_id`)
  and, where applicable, `finding_id` context, and MUST never log patient identifiers or
  secrets.
- **FR-009**: The system MUST capture every unhandled exception in a centralized
  error-tracking service.
- **FR-010**: The system MUST apply standard security response headers to all responses,
  with these baseline values: strict transport security enabled (HSTS), framing denied
  (`X-Frame-Options: DENY`), MIME-sniffing disabled (`X-Content-Type-Options: nosniff`), and
  a content-security policy present. The exact content-security-policy directives are
  decided during planning, but a policy MUST be present on every response.
- **FR-011**: The system MUST provide a rate-limiting capability backed by the shared cache
  that later features can apply to sensitive endpoints.
- **FR-012**: The system MUST provide an in-process domain-event dispatcher through which
  modules raise typed events instead of calling one another directly.
- **FR-013**: The system MUST register a passive audit-log listener at startup that records
  exactly one append-only audit-log entry per dispatched domain event, capturing actor,
  actor type, action, target, event type, and timestamp. The actor MUST always be
  populated: human-initiated events reference the acting user, and system-initiated events
  reference a reserved system-actor identity, distinguished by an `actor_type` of `human`
  or `system`.
- **FR-013a**: The audit-log entry for a state-changing event MUST be persisted in the same
  database transaction as the state change it records, so that a failure to write the audit
  entry rolls back the originating operation (no un-audited state changes).
- **FR-014**: The system MUST never automatically delete or mutate audit-log entries.
- **FR-015**: The relational baseline MUST include a `client_id` column on every
  tenant-scoped table and indexes on the tenant, external-id, status, and deadline columns.
- **FR-016**: The system MUST apply all schema changes through versioned migration files.
- **FR-017**: The system MUST keep all non-secret configuration in a single validated
  settings object that rejects unknown fields, and MUST NOT read configuration from the
  environment outside that settings layer.
- **FR-018**: All application request handlers and external calls MUST be asynchronous.
- **FR-019**: The entire stack MUST start from a fresh clone with a single command, with no
  manual secret entry beyond a one-time write of secrets into the secrets manager.
- **FR-020**: The background worker MUST be present as a skeleton — its own container plus the
  shared startup/shutdown bootstrap (loading secrets, database engine, and cache identically
  to the application) — and MUST load secrets at startup the same way the application does.
  Job functions and scheduled cron are out of scope for this feature (delivered in the
  scheduling feature).

### Key Entities *(include if feature involves data)*

- **Service Configuration**: The validated set of non-secret settings plus the in-memory
  secret values loaded at startup; rejects unknown fields; the single source of runtime
  configuration.
- **Secret Bundle**: The collection of real secret values (model-provider keys, database
  URL, cache URL, service credentials) held only in memory after being fetched from the
  secrets manager.
- **Domain Event**: A typed record of a significant state change (e.g., a finding
  classified, a report approved, a client erased) carrying at minimum the tenant context;
  dispatched in-process to registered handlers.
- **Audit Log Entry**: An append-only record of an actor, actor type (`human` / `system`),
  action, target, event type, and timestamp, written by the passive audit listener for
  every dispatched domain event; the actor is always populated (a reserved system-actor
  identity for system-initiated events); retained long-term and never auto-deleted.
- **Health Status**: The readiness/liveness signal returned by the health endpoint.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From a fresh clone, an operator brings the full stack to a healthy state with a
  single command and no manual secret entry beyond a one-time secret write.
- **SC-002**: In 100% of cases where the secrets manager, database, or cache is unavailable,
  the application refuses to start and reports the specific cause.
- **SC-003**: A secret scan of the working tree and full history reports zero secret values,
  and no secret or patient identifier appears in any log or trace output.
- **SC-004**: The health endpoint returns a healthy response fast enough to satisfy the
  hosting platform's liveness probe (well under one second).
- **SC-005**: 100% of unhandled exceptions raised while serving are captured by the
  error-tracking service.
- **SC-006**: Every dispatched domain event produces exactly one audit-log entry, and no
  audit entry is ever automatically removed.
- **SC-007**: 100% of HTTP responses carry the required security headers.
- **SC-008**: Applying the baseline migration to an empty database yields the expected
  tenant-scoped schema and indexes with zero manual schema edits.
- **SC-009**: The application fails fast at startup when configuration contains an unknown or
  invalid field, rather than starting with unvalidated configuration.
- **SC-010**: The rate-limiting capability can be applied to an endpoint and demonstrably
  rejects requests that exceed the configured limit within the window (verifiable
  independently of any specific login policy).

## Assumptions

- **Stack choices are pre-decided by the project brief and constitution**: a containerized
  local stack via Docker Compose; a dev-mode HashiCorp Vault container as the secrets
  manager fetched with `hvac`; FastAPI for the application with a lifespan-managed startup;
  PostgreSQL (with pgvector available for later features) as the relational store; Redis as
  the cache/queue backend; Alembic for migrations; Sentry for error tracking; structlog for
  logging; the `secure` middleware for headers; and slowapi for rate limiting. These are
  recorded here rather than in the requirements so the plan phase owns the exact wiring.
- **Out of scope for this feature** (delivered by later specs): authentication endpoints and
  roles; business/admin tables and their full columns; model artifacts and the modelserver;
  the language-model adapter's provider behavior beyond constructing the client; any
  pharmacovigilance pipeline logic; the actual rate-limit policy on the login endpoint; and
  the background worker's job functions and scheduled cron (only its bootstrap skeleton is
  in scope here); and distributed/service-level tracing (OpenTelemetry/Langfuse), which is
  wired with the pipeline and agent features. Observability in this feature is limited to
  structured JSON logging and Sentry error tracking.
- The dev-mode secrets-manager token is a well-known, non-sensitive convention; in
  production the hosting platform's secret manager holds only that token and all other
  secrets remain in the secrets manager.
- Secrets are written into the secrets manager once during first-time setup; the application
  and background worker both read them at startup using the same mechanism.
- A single relational instance and a single cache instance are sufficient for the capstone
  scale; horizontal scaling is out of scope.
