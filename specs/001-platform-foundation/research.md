# Phase 0 Research: Platform Foundation & Security Skeleton

All decisions below resolve the spec's design choices and the two checklist items
(CHK007, CHK012) accepted as plan-level. No open NEEDS CLARIFICATION remain.

## D1 — Reserved system-actor representation (resolves CHK012)

- **Decision**: The audit log uses a reserved sentinel actor id `0` with `actor_type =
  'system'` for all system-initiated events; human-initiated events use the authenticated
  user's id with `actor_type = 'human'`. `audit_log.actor_id` is `BIGINT NOT NULL` (always
  populated). No hard foreign key to `users` is created in this feature.
- **Rationale**: Keeps the audit log fully functional and non-null before the `users` table
  exists (auth is spec #2), avoids a forward dependency, and still supports the compliance
  query "human vs system" via `actor_type`. The sentinel `0` is reserved and never assigned
  to a real user.
- **Alternatives considered**: (a) Nullable `actor_id` — rejected, violates the "actor never
  null" clarification; (b) FK to a `users` row seeded in foundation — rejected, couples
  foundation to auth's table ownership; spec #2 may add an FK for human actors later
  (excluding the sentinel) without changing foundation.

## D2 — Baseline migration scope (resolves CHK007)

- **Decision**: The Alembic baseline migration (1) enables required Postgres extensions
  (`vector` for pgvector; `pg_trgm` reserved for later lexical search) and (2) creates the
  `audit_log` table with its indexes. All business/tenant tables (`clients`, `users`,
  `documents`, `chunks`, `findings`, `reports`) are created by their owning feature specs'
  own migrations.
- **Rationale**: Foundation owns only cross-cutting infrastructure (audit + extensions).
  Each later spec adds its tables via its own migration, keeping ownership clean and PRs
  small. The `client_id` + index conventions (FR-015) are documented here and applied by
  each owning spec.
- **Alternatives considered**: Create all tables up front — rejected; couples foundation to
  every later feature's data model and produces an oversized migration.

## D3 — Secret loading via Vault + hvac

- **Decision**: `load_secrets_from_vault(settings)` is the first call in `lifespan`; it reads
  KV v2 path `pantera/secrets` using `hvac` with `VAULT_ADDR`/`VAULT_TOKEN` from the
  container environment, populates the empty secret fields on `Settings` in memory, and
  raises (aborting boot) if Vault is unauthenticated/unreachable or a required key is
  missing. Required keys for this feature: `database_url`, `redis_url`, and at least one of
  `anthropic_api_key` / `openai_api_key` (FR-002).
- **Rationale**: Matches the brief exactly; guarantees no secret on disk and fail-fast on
  misconfiguration. The worker uses the identical function in its ARQ `on_startup`.
- **Alternatives considered**: pydantic-settings reading a `.env` — rejected by the
  constitution (no `.env` for secrets); AppRole auth — deferred to production hardening.

## D4 — Lifespan ordering & singletons

- **Decision**: Order is: load secrets → create async engine → create Redis client → build
  LLM client (adapter, by available key) → run startup checks (DB ping, Redis ping, model
  hashes if present) → `yield` → dispose engine, close Redis on shutdown. Resources live on
  `app.state` and are exposed via `Depends()`.
- **Rationale**: Secrets must exist before any resource is constructed; checks run after
  construction so they validate the real clients. Single construction satisfies FR-006.
- **Alternatives considered**: Module-level globals — rejected (constitution: resources load
  once in lifespan, accessed via `Depends`).

## D5 — Domain-event dispatcher with atomic audit (satisfies FR-013a)

- **Decision**: An in-process `EventDispatcher` maps event type → handlers and is dispatched
  **synchronously within the caller's database transaction/session**. The audit handler
  writes the `audit_log` row using that same session, so a failed audit write rolls back the
  whole unit of work. "Passive listener" means the audit handler never initiates work and is
  registered once at startup — it does not mean asynchronous.
- **Rationale**: Reconciles the "passive listener" and "always consistent" language (the
  clarified atomic decision). No extra broker; integration events later use ARQ + n8n.
- **Alternatives considered**: After-commit async dispatch — rejected per clarification
  (would allow un-audited committed changes); separate audit transaction — rejected (not
  atomic).

## D6 — Logging, redaction, and error tracking

- **Decision**: `structlog` emits JSON; a context processor binds `client_id` and
  `finding_id` when present; a denylist/redaction processor drops known secret/PII keys so
  they never reach output. Sentry is initialized once at startup with `send_default_pii =
  False`. Full Presidio-based redaction is spec #12; foundation guarantees logs never carry
  secrets/PII via the structlog processor and by never logging secret values.
- **Rationale**: Satisfies FR-008/FR-009 and SC-003/SC-005 without pulling the Presidio
  dependency into the foundation.
- **Alternatives considered**: stdlib logging — rejected (not structured); deferring all
  redaction to spec #12 — rejected (logs exist from day one).

## D7 — Security headers (resolves CHK013) & rate-limit capability

- **Decision**: Use the `secure` library middleware with: HSTS enabled, `X-Frame-Options:
  DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and a baseline
  CSP `default-src 'self'`. The CSP will be revisited when the SPA lands (spec #10). A
  `slowapi` `Limiter` backed by Redis is constructed and attached to `app.state`; no login
  policy is applied here (spec #2 applies `@limiter.limit` to the login route).
- **Rationale**: Concrete, testable header values now; CSP intentionally minimal until a
  frontend exists. SC-010 verifies the capability independently of any login policy.
- **Alternatives considered**: Hand-rolled middleware — rejected (reuse `secure`).

## D8 — Health endpoint

- **Decision**: `GET /health` is public, unauthenticated, returns `{"status": "ok"}` with a
  shallow check only (no per-call DB/Redis ping). It is registered as a normal route, so it
  is unavailable until lifespan startup completes successfully (FR-007 + reworded edge case).
- **Rationale**: Matches the clarified shallow-liveness decision and avoids restart storms.
- **Alternatives considered**: Deep readiness / dual endpoints — rejected per clarification.

## D9 — Worker skeleton

- **Decision**: `worker/worker.py` defines `WorkerSettings` with `on_startup`/`on_shutdown`
  that call the same secret-loading + engine/Redis bootstrap as the app, `functions = []`,
  and no `cron_jobs`. `handle_signals = True` for graceful shutdown.
- **Rationale**: Establishes app/worker secret-loading parity (FR-020) now; jobs and cron
  are spec #11.
- **Alternatives considered**: Defer the worker entirely — rejected per clarification.

## D10 — Testing approach

- **Decision**: Unit tests for config validation (`extra="forbid"`), the dispatcher
  (exactly-one-entry, rollback on handler failure), and log redaction. Integration tests
  (against Compose services) for: fresh-clone boot to healthy, refuse-to-boot when
  Vault/DB/Redis unavailable, `/health` shape + latency, security headers on responses, and
  audit atomicity (forced audit failure rolls back the state change). Coverage target 80%
  overall, 95%+ on audit DB-write path (constitution).
- **Rationale**: Directly maps tests to SC-001..SC-010 and the high-risk audit path.
