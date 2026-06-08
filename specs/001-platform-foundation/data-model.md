# Phase 1 Data Model: Platform Foundation & Security Skeleton

Foundation owns only cross-cutting persistence: the `audit_log` table and the Postgres
extension baseline. Tenant/business tables are added by their owning specs following the
conventions documented here.

## Entity: AuditLogEntry (`audit_log`)

Append-only record written by the passive audit handler for every dispatched domain event.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | BIGINT | PK, autoincrement | |
| `actor_id` | BIGINT | NOT NULL | Authenticated user id for human events; reserved sentinel `0` for system events |
| `actor_type` | TEXT/ENUM | NOT NULL, in (`human`, `system`) | Discriminator (D1) |
| `action` | TEXT | NOT NULL | e.g., `report.approved`, `client.erased` |
| `target` | TEXT | NOT NULL | Stable reference to the affected entity (e.g., `report:123`) |
| `event_type` | TEXT | NOT NULL | Domain event class name (e.g., `ReportApproved`) |
| `client_id` | BIGINT | NULL | Tenant context when the event is client-scoped |
| `payload` | JSONB | NULL | Redacted event detail (never secrets/PII) |
| `created_at` | TIMESTAMPTZ | NOT NULL, default now() | Event timestamp |

**Indexes**: `actor_id`, `actor_type`, `client_id`, `created_at`, `event_type`.

**Rules**:
- Append-only: no UPDATE or DELETE paths exist; never auto-deleted (FR-014).
- Written in the **same transaction** as the originating state change; audit-write failure
  rolls back the unit of work (FR-013a).
- `actor_id` is never null; `0` is the reserved system sentinel and is never a real user.
- `payload` passes through the redaction processor before persistence.

**State transitions**: none — entries are immutable once written.

## Reserved value: System Actor

- `actor_id = 0`, `actor_type = 'system'` — used by all cron/pipeline-initiated events.
- Defined as a module-level constant (`SYSTEM_ACTOR_ID = 0`) so every later feature emits
  system events consistently.

## Postgres extension baseline

- `CREATE EXTENSION IF NOT EXISTS vector;` (pgvector — for later chunk embeddings)
- `CREATE EXTENSION IF NOT EXISTS pg_trgm;` (reserved for later lexical search)

## Conventions for later specs (not created here)

These are documented so every owning spec applies them; foundation does not create the
tables.

- Every tenant-scoped table carries a `client_id` column and indexes it (FR-015,
  Constitution V).
- High-traffic lookup columns are indexed: `client_id` (all tenant tables), `external_id`
  (documents — dedup), `status` (findings/reports), `sla_deadline` (reports).
- Every schema change ships as its own Alembic migration (FR-016).

## In-memory entities (not persisted)

- **Settings** (`app/core/config.py`): non-secret fields with defaults + empty secret fields
  populated from Vault at startup; `model_config = SettingsConfigDict(extra="forbid")`.
- **Secret Bundle**: the in-memory secret values on `Settings` after `load_secrets_from_vault`
  (`database_url`, `redis_url`, `anthropic_api_key`/`openai_api_key`, and later service
  tokens). Never persisted, logged, or written to disk.
- **Domain Event**: frozen dataclasses in `app/domain/events.py` carrying at least the
  tenant context; dispatched in-process to registered handlers.
