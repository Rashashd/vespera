# Database conventions (applied by every owning feature spec)

The foundation creates only the `audit_log` table and the Postgres extension baseline.
Every later spec adds its own tables via its own Alembic migration, following these rules.

## Multi-tenancy (Constitution V)

- Every tenant-scoped table MUST carry a `client_id` column and index it.
- One client's rows MUST never be returned in another client's query — repository queries
  are client-scoped, and RAG retrieval is client-filtered.

## Indexing

Index the high-traffic lookup columns:

| Column | Where | Why |
|--------|-------|-----|
| `client_id` | every tenant-scoped table | tenant filtering |
| `external_id` | `documents` | dedup on PubMed ID / DOI / alert ID |
| `status` | `findings`, `reports` | pipeline/queue filtering |
| `sla_deadline` | `reports` | SLA monitoring |

## Migrations

- Every schema change ships as its own Alembic migration file (FR-016); no ad-hoc DDL.
- The baseline migration (`0001_baseline.py`) owns extensions (`vector`, `pg_trgm`) and
  `audit_log` only.

## Audit log

- Append-only: never `UPDATE` or `DELETE` (FR-014).
- `actor_id` is never null; system events use the reserved sentinel `SYSTEM_ACTOR_ID = 0`
  with `actor_type = 'system'`; human events use the user id with `actor_type = 'human'`.
- Audit rows are written in the same transaction as the change they record (FR-013a).
