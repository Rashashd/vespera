# Quickstart: Validating Security Hardening

Runnable validation that the three layers work end-to-end. Host commands assume the Vault-repoint procedure (see `memory/host-integration-test-vault-repoint.md`); CI uses service-name hosts. Lint authority: BOTH `ruff` AND `black` must pass.

## Prerequisites

```powershell
docker compose up -d                      # api, worker, postgres, redis, vault, modelserver, guardrails (NEW)
# Provision the least-privilege role + secrets (one-time / per fresh DB):
uv run python scripts/write_secrets.py    # writes app_database_url + guardrails_token
# Apply migration 0011 (privileged role) from the host:
$env:VAULT_ADDR="http://localhost:8200"; $env:VAULT_TOKEN="root"
$env:PANTERA_DATABASE_URL="postgresql+asyncpg://pantera:pantera@localhost:5433/pantera"
uv run alembic upgrade head               # creates RLS policies + grants to pantera_app
```

## Scenario 1 — RLS tenant isolation (User Story 3)

Goal: an intentionally-unfiltered query returns only the in-context client's rows; default-deny when unset.

1. Connect as `pantera_app` (least-priv). With NO context set, `SELECT count(*) FROM findings;` ⇒ **0** (default-deny).
2. `SELECT set_config('app.current_client_id','1',true); SELECT count(*) FROM findings;` ⇒ only client 1's rows.
3. `SELECT set_config('app.is_staff','on',true); SELECT count(*) FROM findings;` ⇒ all rows (staff/system).
4. Attempt `INSERT INTO findings(client_id, …) VALUES (2, …)` while context is client 1 ⇒ **rejected** by `WITH CHECK`.
5. As `pantera` (privileged): migrations/seed succeed (bypass). 
Expected: integration test `tests/integration/test_rls_isolation.py` green; SC-005/006/009.

## Scenario 2 — Redaction at egress (User Story 2)

Goal: planted PII + secret never leave the trust boundary; clinical signal preserved.

1. Run the redaction golden set: `uv run pytest tests/integration/test_redaction_gate.py`.
2. The set plants a fake patient identifier + fake API key into document text routed to: the external-LLM payload, a log line, a trace, and a derived summary.
3. Assert: zero planted tokens survive at any egress point (`security.redaction_leak_max: 0`).
4. Assert: legitimate control cases keep drug/AE terms (no over-redaction).
Expected: SC-003/004.

## Scenario 3 — Guardrails red-team (User Story 1)

Goal: injection/jailbreak/off-topic/cross-client blocked (input+output); legitimate PV content passes; fail-safe on outage.

1. `GET http://localhost:8002/health` ⇒ `{"status":"ok"}`.
2. `POST /guard` with an injection payload (`X-Service-Token` set) ⇒ `action="block", rail="injection"`.
3. `POST /guard` with legitimate PV text ⇒ `action="allow"`.
4. Run the gate: `uv run pytest tests/integration/test_guardrails_redteam.py` ⇒ block-rate=1.0, false-refusal=0.
5. Stop the guardrails container; trigger a triage LLM fallback ⇒ finding **escalates** (fail-safe) and a `GuardrailUnavailable` audit row is written; trigger intake ⇒ document **quarantined** (not indexed), `DocumentQuarantined` audit row.
Expected: SC-001/002; FR-006/006a.

## Scenario 4 — Tracing re-enable verification (User Story 4)

1. Set `tracing_enabled=true` + a LangSmith key in a NON-prod env.
2. Run a drafting-agent run over content with a planted patient identifier.
3. Inspect the captured agent trace ⇒ no unredacted patient identifier or secret present.
Expected: SC-007; startup logs the "tracing on, redaction is the control" note.

## Scenario 5 — Deviation closure (User Story 5)

- Confirm `app/triage/llm.py` redacts + guards before `_call_llm`.
- Confirm the two spec-8 deviation records are marked closed referencing this feature (spec-8 plan Complexity Tracking / `DECISIONS.md`).
Expected: SC-008.

## Full gate

```powershell
uv run ruff check app worker guardrails tests
uv run black --check app worker guardrails tests
uv run pytest tests/unit
$env:PANTERA_INTEGRATION="1"; uv run pytest tests/integration   # live DB (RLS) required
```
Coverage gate ≥80% overall; auth/HITL/DB-write paths ≥95%. Both new eval gates must pass.
