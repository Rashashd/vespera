# Phase 1 Data Model: Security Hardening

This feature adds **no new business tables**. It adds: database RLS policies + a new DB role, three application schemas (guard request/response, redaction result), and three domain events. Migration **0011** (`down_revision = "0010"`).

## 1. RLS policies (migration 0011)

For each `client_id`-bearing table: `ALTER TABLE … ENABLE ROW LEVEL SECURITY; ALTER TABLE … FORCE ROW LEVEL SECURITY;` then one `tenant_isolation` policy (template in `contracts/rls-policies.md`), plus `GRANT SELECT/INSERT/UPDATE/DELETE … TO pantera_app`.

**Policied tables (~22)** — verified against live models:

| Table | client_id? | Policy predicate keys on |
|---|---|---|
| `clients` | self (`id`) | `id` |
| `watchlists`, `watchlist_items`, `watchlist_budget_usage` | direct | `client_id` |
| `documents`, `document_sources`, `document_watchlists`, `ingestion_runs`, `ingestion_run_sources`, `source_watermarks` | direct | `client_id` |
| `chunks`, `document_index_state`, `index_build_runs` | direct | `client_id` |
| `findings` | direct | `client_id` |
| `reports`, `report_findings`, `report_followups` | direct | `client_id` |
| `llm_usage` | direct | `client_id` |
| `watchlist_cycles`, `dead_letter` (nullable) | direct | `client_id` |
| `user_watchlist_scope` | direct | `client_id` |

**Exempted (documented, NOT policied):**
- `users` — login resolves a user pre-context; no client-user enumeration endpoint; identity isolation stays at app-layer role guards.
- `audit_log` — append-only, staff-read-only, already query-filtered by `client_id`.

**Nullable-`client_id` note**: `dead_letter.client_id` and `audit_log.client_id` are nullable (system rows). For `dead_letter` (policied), a NULL `client_id` row is visible only to staff (`is_staff='on'`); the predicate `client_id = …` is false for NULL, so client-users never see system rows — correct.

**New role**: `pantera_app` (LOGIN, NOSUPERUSER, NOBYPASSRLS, not table owner) — provisioned at DB bootstrap (R5), not in the migration. Migration GRANTs table privileges to it.

**Downgrade**: drop policies, `NO FORCE`, `DISABLE ROW LEVEL SECURITY`, revoke grants (role drop NOT in downgrade — role is bootstrap-managed).

## 2. Session security context (GUC — not a table)

| GUC | Type | Set by | Values |
|---|---|---|---|
| `app.current_client_id` | text (cast to bigint) | `set_rls_context` per txn | client-user's `client_id`; unset for staff/system |
| `app.is_staff` | text | `set_rls_context` per txn | `'on'` for staff/system; unset/`'off'` for client-users |

Set via `SELECT set_config('app.current_client_id', :cid, true)` (transaction-local). Default-deny when unset.

## 3. Application schemas (pydantic)

### GuardRequest / GuardResponse (`app/guardrails/schemas.py`)

```
GuardRequest:
  text: str                      # the payload to check (prompt or model output)
  direction: "input" | "output"
  client_id: int                 # acting tenant context (for the cross-client rail)
  call_site: str                 # "triage" | "agent" | "intake"

GuardResponse:
  action: "allow" | "block"
  rail: str | None               # which rail blocked (injection|jailbreak|topic_scope|cross_client)
  reason: str | None             # non-PII reason code
  checked: list[str]             # rails evaluated
```

### RedactionResult (`app/redaction/redactor.py`)

```
RedactionResult:
  text: str                      # redacted text (placeholders substituted)
  entities: list[RedactedEntity] # category + count only — NEVER the original value
RedactedEntity:
  type: str                      # PERSON | DATE_TIME | PHONE | EMAIL | LOCATION | MEDICAL_RECORD | SECRET | ...
  count: int
```
Only category + count are retained (for non-PII metrics/audit); the original text is never stored or logged.

## 4. Domain events (`app/domain/events.py` — extend)

New `DomainEvent` subclasses (auto-picked-up by `register_audit_handlers` via `__subclasses__`, `app/audit/handler.py:52`). Each carries `actor_id`, `actor_type`, `client_id`/`target_client_id` per the existing base so the audit handler records them with no handler change.

| Event | Fields (beyond base) | Raised when |
|---|---|---|
| `GuardrailRefused` | `rail: str`, `call_site: str`, `direction: str` | A rail blocks a guarded call (FR-005) |
| `GuardrailUnavailable` | `call_site: str`, `fail_action: str` | Sidecar unreachable/errored → fail-safe taken (FR-006) |
| `DocumentQuarantined` | `document_id: int`, `reason: str` | Intake scan couldn't run; doc held out (FR-006a) |

Payloads MUST contain no PII (rail reasons are codes, not document text).

## 5. Configuration additions (`app/core/config.py` Settings)

| Field | Type | Default | Secret? |
|---|---|---|---|
| `guardrails_url` | str | `"http://guardrails:8002"` | No (non-secret config) |
| `app_database_url` | str | `""` | Yes (Vault → `_REQUIRED_SECRETS`) |
| `guardrails_token` | str | `""` (exists) | Yes — **promote to `_REQUIRED_SECRETS`** |
| `redaction_enabled` | bool | `True` | No |
| `guardrails_enabled` | bool | `True` | No |

`tracing_enabled` (exists, default `False`) may be flipped on in non-prod once redaction is verified (FR-023); keep default `False`.

## 6. State / lifecycle

- **Guarded call**: `redact(text)` → `guard(input)` → external LLM → `guard(output)` → use result. Any block or guardrails-unavailable → fail-safe (escalate/quarantine) + domain event.
- **Quarantined document**: held out of indexing/triage (no INDEXED transition); a later cycle may re-attempt when guardrails recovers (no automatic re-scan obligation this feature).
- **RLS context**: created at txn start (request: after principal; worker: system), discarded at txn end; never persisted.
