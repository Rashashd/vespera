# Phase 0 Research: Security Hardening

Decisions resolving the technical unknowns. Each: Decision · Rationale · Alternatives rejected. Grounded against live code (see [implementation-notes.md](./implementation-notes.md) for file:line anchors).

## R1 — Guardrails sidecar engine (torch-free, no-LLM)

**Decision**: Build the guardrails sidecar as a **lean FastAPI service** in a new top-level `guardrails/` folder (mirroring `modelserver/`), exposing `POST /guard` and `GET /health`, authenticated by `X-Service-Token`. Platform rails are **local/heuristic** custom checks (regex/keyword/optional small ONNX classifier) with **no external LLM call and no torch**. Attempt to back it with the `nemoguardrails` library configured with custom Python actions and **no model**; if `nemoguardrails` cannot be installed torch-free in the sidecar image, implement the rails directly and record the swap as a justified deviation in `DECISIONS.md`. Either way the HTTP contract (`contracts/guardrails-api.md`) is identical, so the app side is unaffected.

**Rationale**: Constitution VI bars torch in any serving container and the clarify decision (Session 2026-06-15) chose heuristic/local rails with no per-call LLM round trip for cost + deterministic CI gating. A fixed HTTP contract decouples the app from the engine choice so the (uncertain) library question can't block the app-side work.

**Alternatives rejected**: (a) NeMo LLM-backed self-check rails — adds an LLM call + cost + nondeterminism per guarded request, and risks pulling torch; (b) in-process rails (no sidecar) — Constitution VI + Brief explicitly name the guardrails *sidecar* as the security boundary; keeping it a separate service preserves the boundary and the service-credential pattern.

## R2 — Rail set & detection methods

**Decision**: Four platform rails, applied to **both input and output** payloads:
- **prompt-injection** — curated regex/phrase set ("ignore previous instructions", "disregard the system", role-override, delimiter-escape, tool/exfiltration patterns) + a normalized-text scan.
- **jailbreak** — known jailbreak phrase set (DAN-style, "pretend you have no rules", policy-override).
- **topic-scope** — pharmacovigilance allow-signal: lightweight keyword/embedding affinity (drug/AE/clinical lexicon); refuse clearly off-domain content. Tuned to favor recall of legitimate PV content (avoid false refusals).
- **cross-client** — refuse content that references another client by name/id than the call's `client_id` context; the request carries the acting `client_id` so the rail can detect a mismatch.
PII is **NOT** a rail (owned by Presidio, R3). Each rail returns `{rail, action: allow|block, reason}`; any block ⇒ overall block.

**Rationale**: Heuristic detection is deterministic (CI-gateable to a fixed block-rate) and torch-free. Output-side checks catch a manipulated model response (injection-echo) before it is stored/shown (FR-002a).

**Alternatives rejected**: ML-only detection (nondeterministic gate, heavier image); input-only checks (misses a jailbroken response).

## R3 — Presidio redaction placement & engine

**Decision**: In-process redaction via `presidio-analyzer` + `presidio-anonymizer` with a spaCy NER model, wrapped in `app/redaction/redactor.py` exposing `redact(text) -> RedactionResult(text, entities)`. The analyzer/engine is a process singleton (`@lru_cache`, like `app/triage/ner.py`'s `_get_nlp`). Applied at four egress points:
1. **External LLM** — in `app/triage/llm.py` before building the request body, and in `app/agent/graph.py` on message content before `chat_model.ainvoke` (covers retrieved RAG context too).
2. **Logs** — a structlog processor that redacts string values before emit (`app/observability/logging.py`).
3. **Traces** — the existing trace redaction (`app/observability/tracing.py`) already drops inputs to safe keys for triage; extend to the agent path so the agent trace carries no PII (FR-023).
4. **Derived stored summaries** — any operational summary persisted (not the report body).

Redaction runs **before** the guardrails call and the external call (FR-012). Persisted report body / findings / chunks are NOT redacted.

**spaCy model choice**: reuse a small English model. scispaCy `en_ner_bc5cdr_md` is already a dependency but it is a *biomedical entity* model (chemicals/diseases), NOT a PII model — do not use it for PII. Presidio's default `en_core_web_lg`/`_sm` is the PII NER. Pin `en_core_web_sm` (small, no torch) for Presidio; verify install size. (See implementation-notes "does NOT exist" list.)

**Rationale**: Presidio is the constitution-named redactor. In-process avoids an unjustified container. Singleton avoids per-call model load. Redacting at the LLM-egress boundary (not the DB) preserves clinical fidelity for reviewers while protecting the external boundary; citations are `chunk_id`-based so grounding survives redaction.

**Alternatives rejected**: regex-only PII (misses names/addresses); redacting at the DB layer (destroys reviewer/clinician content, breaks grounding); a separate redaction microservice (unjustified container).

## R4 — RLS policy model & GUC context

**Decision**: `ENABLE` + `FORCE ROW LEVEL SECURITY` on every `client_id`-bearing table (inventory in `contracts/rls-policies.md`). One reusable policy per table:

```sql
CREATE POLICY tenant_isolation ON <table>
  USING (
    current_setting('app.is_staff', true) = 'on'
    OR client_id = NULLIF(current_setting('app.current_client_id', true), '')::bigint
  )
  WITH CHECK ( /* same predicate — blocks cross-client writes */ );
```

Context is set per transaction via `SELECT set_config('app.current_client_id', :cid, true)` and `set_config('app.is_staff', :flag, true)` (the `true` third arg = `is_local`, scoped to the transaction). `clients` table policy keys on `id` instead of `client_id`. `users` and `audit_log` are **exempted** (documented): users because login resolves pre-context and has no client-user enumeration endpoint; audit_log because it is append-only, staff-read-only, and already filtered by `client_id` at the query layer (revisit if a client-facing audit view is ever added).

**Default-deny**: with no context set, `current_setting('app.current_client_id', true)` returns `''` → `NULLIF` → NULL → predicate false, and `app.is_staff` unset → not `'on'` → false ⇒ zero rows. Never fail-open.

**Rationale**: One templated policy keeps the migration mechanical and auditable across ~22 tables. GUC + `set_config(..., true)` is the standard per-transaction RLS context and is PgBouncer-transaction-pooling compatible. `FORCE` ensures even the table owner is subject (so the app role can't be accidentally the owner and bypass).

**Alternatives rejected**: per-table bespoke policies (error-prone at 22 tables); `SET LOCAL app.x` literal SQL (can't be parameterized safely — use `set_config` with bind param); session-level `SET` (leaks across pooled connections).

## R5 — Two-role split & provisioning

**Decision**: 
- **App runtime role** (`pantera_app`, least-privilege, NOT owner, NOT superuser, NOT BYPASSRLS) — used by the FastAPI app + ARQ worker via a new `app_database_url` secret. Subject to FORCE RLS.
- **Privileged role** (existing `pantera`, DB owner/superuser in dev) — used by Alembic migrations + seed scripts via the existing `database_url`. Bypasses RLS for schema/seed.

Role + password are provisioned at **DB bootstrap**, not inside the migration: docker-compose runs an init SQL (`CREATE ROLE pantera_app LOGIN PASSWORD ...`), CI adds a step creating the role on the fresh Postgres service, and `write_secrets.py` writes `app_database_url` with the matching password. Migration **0011** only does `GRANT`s + `ENABLE/FORCE RLS` + `CREATE POLICY` (assumes the role exists; idempotent-guarded).

**Rationale**: The user's clarify decision explicitly chose a dedicated least-privilege role + new secret. Keeping role/password provisioning out of the migration respects "secrets only in Vault" and keeps the migration portable. `env.py` and seed scripts stay on `database_url` (no change). Only `lifespan.py:65` and the worker switch to `app_database_url`.

**Alternatives rejected**: single role + `SET row_security=off` for migrations (the user chose the two-role model; also relies on superuser); creating the role inside the migration with a password (puts a secret in a migration).

## R6 — Engine config for RLS + pooling

**Decision**: The runtime engine (`app/db/base.py:create_engine`) connects via `app_database_url` and sets `connect_args={"statement_cache_size": 0}` (asyncpg) to stay correct under future PgBouncer transaction pooling. Keep `pool_pre_ping=True`. The RLS context is set inside the existing `session.begin()` transaction (`core/dependencies.py:25`, `db/base.py:33`) via `app/db/rls.py:set_rls_context`.

**Rationale**: Honors the spec-breakdown PgBouncer/asyncpg caveat. Disabling the prepared-statement cache is the documented requirement for transaction pooling; doing it now avoids a latent break when PgBouncer is added.

**Alternatives rejected**: introducing PgBouncer now (out of scope); leaving statement cache on (breaks under transaction pooling later).

## R7 — Where RLS context is set (request + worker + pipeline)

**Decision**:
- **Request path**: set context in `app/auth/dependencies.py:current_active_principal`, immediately after `fresh = await session.get(User, ...)` (users table is exempt so this read works pre-context). Client-user → `current_client_id = user.client_id, is_staff=off`; staff → `is_staff=on`. Because `acting_client` and all route bodies depend (transitively) on `current_active_principal` and share the `get_session` transaction, the context is set before any RLS-relevant query.
- **Worker / pipeline / agent path** (no FastAPI deps): a system context (`is_staff=on`) set when the worker opens its session (these are trusted system operations across clients, not client-user responses). Provide `set_rls_context(session, client_id=None, is_staff=True)` and call it at each worker/pipeline session-open site.

**Rationale**: The defense-in-depth target is the request path serving client-users. Worker code does not return cross-client responses to a client-user, so a system context is appropriate and keeps the wiring bounded. Default-deny means any missed context fails loudly (no rows), never leaks.

**Alternatives rejected**: setting per-real-client context in the worker (the worker legitimately spans clients per cycle — would require re-setting context per client and breaks cross-client sweeps); running the worker on the privileged role (loses all RLS protection AND mixes the migration role into runtime).

**Open wiring risk (flag in implementation-notes)**: every session-open site must set context or its queries return nothing. Enumerate them: `core/dependencies.py:get_session` (request), `lifespan.py` bootstrap/ingestion-startup sessions, worker job sessions, triage runner, embedding/index runner, scheduling cadence loop, agent run. Bootstrap/seed run on the privileged role so they are unaffected.

## R8 — CI gates & secrets wiring

**Decision**: Add a `security:` block to `eval_thresholds.yaml`:
```yaml
security:
  redaction_leak_max: 0          # planted PII/secret tokens surviving any egress
  guardrail_block_rate_min: 1.0  # fraction of known attack payloads blocked
  guardrail_false_refusal_max: 0 # legitimate PV control cases wrongly blocked
```
Two CI jobs in the existing `eval` workflow: a **redaction** gate (golden set with planted fake patient id + fake API key across egress points) and a **guardrails red-team** gate (injection/jailbreak/off-topic/cross-client payloads + legitimate controls). The red-team gate runs the sidecar (compose service) or imports the rails engine directly. New secrets `app_database_url` + `guardrails_token` added to `_REQUIRED_SECRETS`, the CI inline secret writer in `ci.yml`, `scripts/write_secrets.py`, and `docker-compose`. Honor `actions/checkout@v4 lfs: true` on jobs touching ONNX artifacts; use service-name hosts in CI (`postgres:5432`) vs host ports locally (`5433`).

**Rationale**: Constitution IV requires committed thresholds; Brief eval gates #5 (grounding/injection) and #6 (redaction) become real. Secret wiring mirrors the spec-2 lesson (a new `_REQUIRED_SECRETS` entry must also go in the CI inline writer or alembic/tests fail fast).

**Alternatives rejected**: thresholds in Settings (CI-gate-only values belong in `eval_thresholds.yaml`, never loaded at runtime — spec-8 lesson); skipping the false-refusal metric (over-blocking legitimate PV content would silently degrade the product).
