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

<!-- Classifier / RAG / triage model comparisons and their golden-set numbers are added by
     their owning feature specs. -->
