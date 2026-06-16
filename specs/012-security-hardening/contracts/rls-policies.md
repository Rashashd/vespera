# Contract: RLS Policies, Role & Session Context

## Role contract

| Role | Privileges | Used by | Connection string |
|---|---|---|---|
| `pantera_app` (NEW) | LOGIN, NOSUPERUSER, NOBYPASSRLS, table SELECT/INSERT/UPDATE/DELETE via GRANT; NOT table owner | FastAPI app + ARQ worker (runtime) | `app_database_url` (Vault, `_REQUIRED_SECRETS`) |
| `pantera` (existing) | DB owner / superuser (dev) — bypasses RLS | Alembic migrations + seed scripts | `database_url` (Vault, existing) |

Role `pantera_app` is created at **DB bootstrap** (compose init SQL + CI step + `write_secrets.py`), NOT in the migration. Password MUST match `app_database_url`.

## Policy template (applied per policied table)

```sql
ALTER TABLE <t> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <t> FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON <t>
  USING (
    current_setting('app.is_staff', true) = 'on'
    OR <scope_col> = NULLIF(current_setting('app.current_client_id', true), '')::bigint
  )
  WITH CHECK (
    current_setting('app.is_staff', true) = 'on'
    OR <scope_col> = NULLIF(current_setting('app.current_client_id', true), '')::bigint
  );
GRANT SELECT, INSERT, UPDATE, DELETE ON <t> TO pantera_app;
```
- `<scope_col>` = `client_id` for all tables except `clients` where it is `id`.
- `WITH CHECK` blocks INSERT/UPDATE into another client's scope (write isolation, FR + CHK031).
- `current_setting(name, true)` → second arg `true` = `missing_ok`, returns `''`/NULL when unset (no error), enabling default-deny.

## Policied table list

`clients` (scope=`id`), `watchlists`, `watchlist_items`, `watchlist_budget_usage`, `documents`, `document_sources`, `document_watchlists`, `ingestion_runs`, `ingestion_run_sources`, `source_watermarks`, `chunks`, `document_index_state`, `index_build_runs`, `findings`, `reports`, `report_findings`, `report_followups`, `llm_usage`, `watchlist_cycles`, `dead_letter`, `user_watchlist_scope`.

**Exempt (documented):** `users`, `audit_log`. (Also non-tenant tables with no `client_id` — e.g. alembic version — are naturally unpolicied.)

## Session-context contract (`app/db/rls.py`)

```python
async def set_rls_context(session, *, client_id: int | None, is_staff: bool) -> None:
    # transaction-local (is_local=true); must run inside an open transaction
    await session.execute(
        text("SELECT set_config('app.is_staff', :s, true)"),
        {"s": "on" if is_staff else "off"},
    )
    await session.execute(
        text("SELECT set_config('app.current_client_id', :c, true)"),
        {"c": "" if client_id is None else str(client_id)},
    )
```

**Set points (must cover ALL session-open sites — see research R7):**
- Request: `app/auth/dependencies.py:current_active_principal`, after `session.get(User, ...)` → client-user `(client_id=user.client_id, is_staff=False)`; staff `(client_id=None, is_staff=True)`.
- Worker/pipeline/agent/lifespan-ingestion sessions: `(client_id=None, is_staff=True)` (system context).
- Migrations/seed: no context needed (privileged role bypasses).

**Default-deny invariant**: any session that opens on `pantera_app` without `set_rls_context` returns zero rows from policied tables. This is the safe failure mode — it breaks loudly, never leaks.

## Engine contract (`app/db/base.py`)

- Runtime engine connects via `app_database_url`.
- `create_async_engine(url, pool_pre_ping=True, connect_args={"statement_cache_size": 0})` — disable asyncpg prepared-statement cache for transaction-pooling (PgBouncer-forward) compatibility.
