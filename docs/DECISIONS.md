# DECISIONS

Architecture and model decisions, with the numbers that justify them. Per-feature design
rationale lives in each `specs/<feature>/research.md`; this file records project-level
decisions defended on demo day.

## Foundation (001-platform-foundation)

- **Secrets in Vault only** — fetched at startup via `hvac`; no `.env` for secrets.
- **Atomic audit** — audit rows are written in the same transaction as the change they
  record; a failed audit write rolls back the operation.
- **Reserved system actor** — `actor_id = 0`, `actor_type = 'system'`; keeps the audit log
  decoupled from the (later) users table while guaranteeing a non-null actor.
- **Shallow public health endpoint** — liveness only, to avoid restart storms.

## Auth & Roles (002-auth-and-roles)

Full rationale in `specs/002-auth-and-roles/research.md` (D1–D13). Project-level highlights:

- **fastapi-users for auth** — vetted async JWT + argon2 hashing; safer than hand-rolling
  crypto. Used for the read path (token validation, `current_active_user`) and JWT issuance.
- **Writes are manual within the request transaction** — fastapi-users' DB adapter commits
  internally, which would break the foundation's atomic-audit guarantee, so user create/update
  is done directly on the `get_session` transaction and the audit event is dispatched in the
  same transaction.
- **Stateless JWT, ~30 min, no refresh** — deactivation takes effect within ≤1 token lifetime;
  no session store to revoke.
- **Two roles, transparent guards** — `admin`/`reviewer` via a `require_role` dependency
  (401 unauthenticated vs 403 forbidden); the `reviewer` send-authority is declared here and
  exercised by the later HITL spec.
- **Audit human-actor FK** — a new nullable `audit_log.actor_user_id` → `users.id`; the
  system sentinel (`actor_id = 0`) stays unlinked, preserving the foundation's audit behavior.
- **Account email is intentionally stored in `UserLoggedIn`/`LoginFailed` audit payloads**
  (analyze finding L1, signed off 2026-06-06): it is an account identifier — not patient PII —
  and is required for credential-stuffing / forensic investigation. Passwords and hashes are
  never stored or logged.
- **Bootstrap email must use a deliverable domain** — `UserRead.email` is `EmailStr`, which
  rejects reserved TLDs (e.g. `.local`) on read-back; the seed default is `admin@pantera.io`.
- **Login rate limit 5/min/IP (no account lockout)** — per-IP throttling avoids an
  account-lockout denial-of-service vector.

## Literature Ingestion (004-literature-ingestion)

Full rationale in `specs/004-literature-ingestion/research.md` (D1–D16). Highlights:

- **In-process BackgroundTasks (not ARQ)** — spec 11 adds durable scheduling; using
  BackgroundTasks now avoids a premature dependency and keeps the worker spec-11 only.
- **Cross-source dedup by normalized external ID** — `doi:<x>` > `pmid:<x>` > `<source>:<id>`;
  lowercased + stripped so the same paper matches regardless of how adapters report it.
- **Source reliability tiers** — `regulatory_alert(3) > peer_reviewed(2) > preprint(1) >
  case_report(0)`; a document's tier is recomputed as `max(rank)` across all contributing sources
  on each dedup hit, so the highest-confidence source wins.
- **Watermarks per (watchlist, source)** — only advanced on source success; first run uses a
  configurable lookback window (default 365 days). Missing watermark → use lookback.
- **Optional API keys** — `pubmed_api_key`/`openfda_api_key` are NOT in `_REQUIRED_SECRETS`;
  adapters fall back to the public rate-limited tier. This avoids a CI change per spec.
- **Bundled slim MeSH list** — ~120 headings from NLM 2024; validated at write time via
  `importlib.resources`; missing artifact degrades to `unvalidated` (non-fatal). The runner
  excludes confirmed-invalid terms from PubMed MeSH targeting.
- **Per-source semaphore** — 3 concurrent requests per source; prevents hammering public APIs.
- **No raw payload / PII in logs** — FAERS `patient` field is stripped at parse time; structlog
  only binds `client_id`/`run_id`.

<!-- Classifier / RAG / triage model comparisons and their golden-set numbers are added by
     their owning feature specs. -->
