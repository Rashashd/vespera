# Quickstart — Validating Report Delivery & Final Wiring

Runnable validation scenarios that prove spec 013 end-to-end. Implementation details live in `tasks.md`; schema in [data-model.md](./data-model.md); endpoints in [contracts/delivery-api.md](./contracts/delivery-api.md). On this Windows host see [[host-integration-test-vault-repoint]] for the localhost Vault/DB/Redis repoint; n8n is **mocked** in tests.

## Prerequisites

- `docker compose up` (api, worker, postgres, redis, modelserver, guardrails) + Vault seeded (`scripts/write_secrets.py`).
- `uv run alembic upgrade head` reaches **0012** (the `pantera_app` role must exist first — see [[spec-012-security-hardening-handoff]]).
- A seeded client with a `report_email_regular`, a reviewer, and a client-user; a drafted report in `under_review`.
- `GUARDRAILS_ENABLED=false` in `tests/conftest.py` (unchanged); `TRACING_ENABLED=false` by default.

## Setup

```bash
uv run alembic upgrade head          # applies 0012_delivery
uv run pytest tests/unit -q          # fast unit gates (tracing, status derivation, rendering, sweep)
# Integration (live DB/Redis, n8n mocked):
PANTERA_INTEGRATION=1 uv run pytest tests/integration/test_delivery.py -q
```

## Scenario A — Approve → deliver → confirm (US1, P1)

1. As a reviewer, `POST /clients/{id}/reports/{rid}/approve`.
2. **Expect**: a `task_deliver_report` job enqueues; the report becomes `sent` with `sent_at`; a `delivery_attempt` row per configured channel (`pending`); the n8n POST is invoked (mocked) with the rendered HTML.
3. Post the n8n callback: `POST /clients/{id}/reports/{rid}/delivery-callback` `{channel:"email", outcome:"delivered", delivered_at:...}` with the `X-Delivery-Token`.
4. **Expect**: the attempt → `delivered`; since it's the only configured channel, the report → `delivered` with `delivered_at`; an audited `ReportDelivered` row exists; no PII in any log/trace.
5. Negative: invoke any delivery path on a `drafted`/`rejected` report → **not** dispatched.

## Scenario B — Multi-channel + failure + re-send (US1)

1. Configure the client with both email and SFTP (`sftp_enabled=true`). Approve a report.
2. **Expect**: two `delivery_attempt` rows; report stays `sent` until both confirm.
3. Callback email→delivered, SFTP→failed. **Expect**: report → `delivery_failed` (names SFTP); a staff alert is routed; email attempt stays `delivered`.
4. `POST .../resend` as admin. **Expect**: only the SFTP channel re-dispatches; on its delivered callback the report → `delivered`. The email channel is NOT re-sent.

## Scenario C — Held paths (US1, FR-007/007a)

1. Approve a report for a client with **no** configured channel → report held (approved-pending-delivery) + staff alert; not dispatched.
2. Suspend a client, then approve/contain an approved report → delivery held; reactivate → held report released (re-dispatched) and cycles resume automatically (no watchlist `is_active` change).

## Scenario D — No-callback timeout + SLA tiers (US3, FR-006a/012)

1. Force a report `sent` with `sent_at` older than the window (default 6h) → run `task_delivery_sla_sweep` → report → `delivery_failed` + alert.
2. Create an open expedited report past `sla_deadline` → sweep → Tier-1 escalation to the client's reviewers (`sla_escalation_tier=1`); advance past the Tier-2 interval (default 2h) still unactioned → Tier-2 to manager/admin (`tier=2`). Each tier fires once; an actioned report never escalates.

## Scenario E — Visibility light-ups (US2)

1. With reports across `approved`/`sent`/`delivered`/`delivery_failed`: reviewer All-Reports + detail show the right `DeliveryStatusChip`; the client portal lists sent/delivered with status; `GET /clients/{id}/metrics` returns a non-null `delivery {sent,delivered,failed,success_rate}` and the dashboard Delivery section renders it.

## Scenario F — Export + audit role model (US5, FR-017/018)

1. `GET /clients/{id}/reports/{rid}/download` as the owning client-user → 200 HTML; as another client's user → 404.
2. `GET /audit/export?format=csv` as **manager** → all events; as **admin** → only client/watchlist events; as **reviewer** → 403. The export writes an `AuditExported` audit row.

## Scenario G — Account management (US4)

1. As manager: `StaffPage` → create a reviewer → the new reviewer signs in and lands on `/queue`.
2. As manager/admin: `ClientUsersPage` for a client → create a scoped client-user → it signs in to `/portal` and sees only in-scope data.

## Scenario H — Budget notification + residual controls (US6/US7)

1. Drive a watchlist across its budget warning threshold → `WatchlistBudgetThresholdReached` fires → an n8n notification routes to the client's manager+admin (audited); staying in the same state does not re-notify.
2. Dead-letter a job → the admin `DeadLetterCard` shows the unresolved count (from `GET /admin/dead-letters` / `failed_jobs`). Verify the manual consolidate trigger acknowledges the **202** enqueue (no inline report).

## Scenario I — Tracing wiring (US8)

```bash
uv run pytest tests/unit/test_tracing_config.py -q     # enabled+key sets LANGCHAIN_*, disabled/empty = no-op
```
- With `TRACING_ENABLED=true` + a key: a worker-executed triage/agent call produces a run in the LangSmith `pantera` project; the run carries only `{client_id, max_tokens}` / `{redacted: true}` / Presidio-redacted messages — no PII.
- With the switch off (default): zero traces, worker boots normally.

## Gates (must stay green)

- `uv run ruff check app worker tests` **and** `uv run black --check app worker tests`.
- Coverage ≥80% overall; ≥95% on delivery DB-writes + the callback/HITL-adjacent paths.
- Redaction gate (no PII/secret in delivery/notification logs or traces); fresh-clone smoke builds + serves the SPA incl. the new Staff/Users screens.
