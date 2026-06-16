---
description: "Task list for 012-security-hardening implementation"
---

# Tasks: Security Hardening

**Input**: Design documents from `/specs/012-security-hardening/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

> **⚠️ READ FIRST: [implementation-notes.md](./implementation-notes.md)** — anti-hallucination guide. It pins exact live APIs, what does NOT exist yet, file:line anchors, and 8 sharp edges. A weaker model implements this cold; do not import or call anything not verified there. Standing rule: [[anti-hallucination-spec-notes]], [[verify-before-claiming-done]].

**Tests**: INCLUDED — the constitution + Brief require CI gates (redaction, grounding/injection red-team) and an RLS isolation test. Test tasks are first-class here.

**Organization**: By user story (US1–US5). US1/US2/US3 are P1 (independently testable); US4/US5 are P2 (gated behind US1/US2).

## Format: `[ID] [P?] [Story] Description with file path`

- **[P]** = parallelizable (different files, no dependency on an incomplete task)
- Lint authority on every task: BOTH `ruff` AND `black` must pass (include `guardrails/` in targets).

---

## Phase 1: Setup (Shared Infrastructure)

- [ ] T001 Add Presidio deps (`presidio-analyzer`, `presidio-anonymizer`, `en_core_web_sm` model) to `pyproject.toml` main deps and a new `guardrails` uv group (lean, torch-free); run `uv lock`. Verify `en_core_web_sm` install is torch-free (research R3).
- [ ] T002 [P] Add Settings fields in `app/core/config.py`: `guardrails_url: str = "http://guardrails:8002"`, `app_database_url: str = ""`, `redaction_enabled: bool = True`, `guardrails_enabled: bool = True` (do NOT re-add existing `guardrails_token`/`tracing_enabled`). **`guardrails_enabled`/`redaction_enabled` are non-production/test-only kill-switches (FR-003/FR-014a): they MUST NOT bypass the mandatory boundary in production.** Default `True`; the production guard lives in T002a.
- [ ] T002a In `app/core/startup.py` (after secrets load, alongside the existing required-secrets check): refuse to boot when `guardrails_enabled` or `redaction_enabled` is `False` in a production environment (gate on the existing prod/env signal — grep `config.py`/`startup.py` for an `environment`/`is_production`/`ENV` marker; if none exists, key off `tracing_enabled`'s prod convention or add a single `environment` Setting). Non-prod may disable for test isolation. Implements FR-003 / FR-014a (resolves analyze C1/C2).
- [ ] T003 [P] In `app/core/startup.py`: add `app_database_url` to `_REQUIRED_SECRETS` (+ `guardrails_token`), and `settings.app_database_url = data.get("app_database_url", "")` in `load_secrets_from_vault`.
- [ ] T004 Wire the two newly-required secrets (`app_database_url`, `guardrails_token`) into `scripts/write_secrets.py`, the inline secret writer in `.github/workflows/ci.yml`, and `docker-compose.yml` (spec-2 lesson: missing CI writer entry fails alembic/tests fast).
- [ ] T005 [P] Add a `security:` thresholds block to `eval_thresholds.yaml` (`redaction_leak_max: 0`, `guardrail_block_rate_min: 1.0`, `guardrail_false_refusal_max: 0`).

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ Complete before any user story.**

- [ ] T006 [P] Create `app/redaction/` package skeleton (`__init__.py` + `RedactionResult`/`RedactedEntity` models per `contracts/redaction.md`).
- [ ] T007 [P] Create `app/guardrails/` package skeleton (`__init__.py` + `GuardRequest`/`GuardResponse` schemas in `app/guardrails/schemas.py` per `contracts/guardrails-api.md`).
- [ ] T008 Add 3 domain events to `app/domain/events.py`: `GuardrailRefused`, `GuardrailUnavailable`, `DocumentQuarantined` (match the existing `DomainEvent` dataclass shape with `actor_id`/`actor_type`/`client_id`/`target_client_id`; auto-audited via `register_audit_handlers`, `app/audit/handler.py:52` — no handler change). Payloads = reason codes only, NO PII.

**Checkpoint**: packages exist, events auditable, config + secrets + thresholds in place.

---

## Phase 3: User Story 1 — Guardrails boundary (Priority: P1) 🎯 MVP

**Goal**: Every external-LLM egress + document intake passes a mandatory torch-free guardrails boundary (input + output rails); blocks injection/jailbreak/off-topic/cross-client; fails safe on outage.

**Independent Test**: Send injection/jailbreak/off-topic/cross-client payloads through each guarded path; legitimate PV content passes; stop the sidecar → triage escalates, agent escalates, intake quarantines (each audited). Run `tests/integration/test_guardrails_redteam.py`.

### Tests for User Story 1

- [ ] T009 [P] [US1] Red-team gate: `tests/integration/test_guardrails_redteam.py` + golden set `tests/data/guardrails_redteam.jsonl` (injection/jailbreak/off-topic/cross-client attacks + legitimate PV controls; assert block-rate=1.0, false-refusal=0).
- [ ] T010 [P] [US1] Unit tests for the rails engine in `tests/unit/test_guardrails_rails.py` (each rail, input vs output direction, fail-safe `rail_engine_error`).

### Implementation for User Story 1

- [ ] T011 [US1] Build the sidecar: top-level `guardrails/` (`app.py` with `POST /guard` + `GET /health`, `core/` heuristic rails engine for injection/jailbreak/topic-scope/cross-client) + torch-free `guardrails/Dockerfile`; copy the `modelserver/` layout + `X-Service-Token` auth.
- [ ] T012 [US1] Add the `guardrails` service to `docker-compose.yml` (port 8002, stdlib `/health` probe like modelserver `:91`, `VAULT_ADDR`/`VAULT_TOKEN`).
- [ ] T013 [US1] Implement `app/guardrails/client.py` (`httpx.AsyncClient` + tenacity, `X-Service-Token=settings.guardrails_token`, URL `settings.guardrails_url`, retry 5xx/timeout/network only, raise `GuardrailsUnavailable`) — mirror `app/infra/modelserver_client.py` + triage `_should_retry`.
- [ ] T014 [US1] Wire `guard(input)` + `guard(output)` around `_call_llm` in `app/triage/llm.py` (`resolve_yes_no`/`assess_valence`): block/unavailable → fail-safe (raise so caller escalates; `assess_valence` keeps its `"positive"` default); emit `GuardrailRefused`/`GuardrailUnavailable`.
- [ ] T015 [US1] Wire `guard(output)` (and input echo-check) around `chat_model.ainvoke` in `app/agent/graph.py` `agent_node`: block/unavailable → set `escalated` so the graph ends (escalate to reviewer); emit events.
- [ ] T016 [US1] Add intake injection scan + quarantine in `app/ingestion/` (before a fetched doc is accepted/indexed): on block/unavailable, hold the document out of indexing+triage and emit `DocumentQuarantined`; continue the cycle for other documents (FR-006a). Grep `app/ingestion/service.py` for the `Document`/`DocumentSource` persist site first.
- [ ] T017 [US1] Sidecar secret loading (`guardrails_token`) + add the `guardrails` service to the CI workflow so the red-team gate can reach it (or import the rails engine directly in-test).

**Checkpoint**: US1 independently functional — guardrails on all egress + intake, fail-safe verified, red-team gate green.

---

## Phase 4: User Story 2 — PII & secret redaction at egress (Priority: P1)

**Goal**: Patient identifiers + secrets are redacted before any external-LLM call, log, trace, or derived summary, uniformly across all text sources; clinical signal preserved; persisted report body/findings untouched.

**Independent Test**: Plant a fake patient id + fake API key into text routed to each egress point; assert zero survive (`security.redaction_leak_max: 0`); legitimate clinical control cases keep drug/AE terms. Run `tests/integration/test_redaction_gate.py`.

### Tests for User Story 2

- [ ] T018 [P] [US2] Redaction gate: `tests/integration/test_redaction_gate.py` + golden set `tests/data/redaction_golden_set.jsonl` (planted PII + secret across external-LLM/log/trace/summary egress; + over-redaction control cases). **Include at least one config-derived case** (a secret/PII token planted in watchlist or custom-severity-keyword text) so FR-009a's "no egress path exempt" is tested, not just asserted by design (resolves analyze A1).
- [ ] T019 [P] [US2] Unit tests for `redact()` + secret recognizers in `tests/unit/test_redaction.py`.

### Implementation for User Story 2

- [ ] T020 [US2] Implement `app/redaction/redactor.py`: Presidio analyzer+anonymizer singleton (`@lru_cache`, mirror `app/triage/ner.py:_get_nlp`); `redact(text) -> RedactionResult`; offload analyze with `asyncio.to_thread`; never log raw text. Use `en_core_web_sm` (NOT scispaCy).
- [ ] T021 [US2] Implement `app/redaction/recognizers.py`: custom secret-pattern recognizer (`sk-`, `sk-ant-`, AWS `AKIA`, JWT, high-entropy key contexts) + medical-record/case-number recognizer.
- [ ] T022 [US2] Add a structlog redaction processor in `app/observability/logging.py` (redact string event values before render); confirm against the existing `configure_logging`.
- [ ] T023 [US2] Extend agent-path trace redaction in `app/observability/tracing.py` so the agent trace carries no content (FR-023); do not duplicate the existing triage `traced_llm_call`.
- [ ] T024 [US2] Insert `redact()` BEFORE the guard+`_call_llm` calls at the triage egress in `app/triage/llm.py` (ordering FR-012). **Sequential after T014** (same function).
- [ ] T025 [US2] Insert `redact()` on message content BEFORE `chat_model.ainvoke` in `app/agent/graph.py` (covers retrieved RAG context; citations are chunk_id refs so grounding is unaffected). **Sequential after T015** (same function).

**Checkpoint**: US2 independently functional — redaction gate green, no leak at any egress, clinical signal preserved.

---

## Phase 5: User Story 3 — Database Row-Level Security (Priority: P1)

**Goal**: All `client_id`-bearing tables enforce client scoping at the DB layer; client-users see only their own rows even on an unfiltered query; staff/system act across clients; default-deny when context unset.

**Independent Test**: As `pantera_app` with no context → 0 rows; with client context → only that client's rows; with staff context → all; cross-client INSERT rejected; migrations/seed succeed on the privileged role. Run `tests/integration/test_rls_isolation.py`.

### Tests for User Story 3

- [ ] T026 [P] [US3] RLS isolation integration test `tests/integration/test_rls_isolation.py` (default-deny, client-scoped read, staff read-all, cross-client write rejection, migration/seed bypass) — needs real Postgres + both roles. **Also assert FR-020: a staff cross-client action under staff context still emits an audit row naming the server-validated target client** (RLS staff-context must not break the existing `acting_client` attribution — Principle V compensating control (a); resolves analyze G1).

### Implementation for User Story 3

- [ ] T027 [US3] DB role bootstrap: idempotent `CREATE ROLE pantera_app LOGIN PASSWORD … NOSUPERUSER NOBYPASSRLS` via a docker-compose postgres init script + a CI step on the fresh Postgres service (password matches `app_database_url`). NOT in the migration.
- [ ] T028 [US3] Migration `app/db/migrations/versions/0011_rls_policies.py` (`revision="0011"`, `down_revision="0010"`): loop the policied-table list (`contracts/rls-policies.md`) applying `ENABLE`+`FORCE ROW LEVEL SECURITY` + `tenant_isolation` policy (USING + WITH CHECK) + `GRANT … TO pantera_app`; `clients` keys on `id`; `users`/`audit_log` exempt. Working downgrade (drop policy/NO FORCE/DISABLE/revoke; do NOT drop role).
- [ ] T029 [US3] Implement `app/db/rls.py:set_rls_context(session, *, client_id, is_staff)` using `set_config('app.current_client_id'|'app.is_staff', …, true)` (transaction-local).
- [ ] T030 [US3] Switch the runtime engine to `app_database_url` + `connect_args={"statement_cache_size": 0}` in `app/db/base.py:create_engine`; update `app/core/lifespan.py:65` and the worker engine to use `app_database_url`. Migrations/seed/`env.py` stay on `database_url`.
- [ ] T031 [US3] Set request RLS context in `app/auth/dependencies.py:current_active_principal` right after `session.get(User, …)`: client-user → `(client_id=user.client_id, is_staff=False)`, staff → `(client_id=None, is_staff=True)`.
- [ ] T032 [US3] Set SYSTEM RLS context `(client_id=None, is_staff=True)` at every non-request session-open site after `session.begin()`: worker job sessions, `app/core/lifespan.py` bootstrap + ingestion-startup sessions, triage runner, `app/embedding/runner.py`, scheduling cadence loop, agent `run_agent`. **Enumerate all** (research R7 / implementation-notes §9.1) — a missed site returns 0 rows.

**Checkpoint**: US3 independently functional — isolation test green; stack boots + migrates with RLS active.

---

## Phase 6: User Story 4 — Re-enable tracing safely (Priority: P2)

**Goal**: With redaction in place, tracing can be enabled and the drafting-agent trace verified PII-free.

**Independent Test**: Enable tracing in a non-prod env; run an agent draft over planted PII; inspect the captured trace → no unredacted PII/secret.

**Depends on**: US2 (redaction at the trace boundary).

- [ ] T033 [US4] In `app/observability/tracing.py`: confirm `configure_tracing` keeps default-off + its warning, and that agent-path traces route through redaction (T023); document the "redaction is the control" note (FR-024).
- [ ] T034 [P] [US4] Integration test `tests/integration/test_trace_redaction.py`: tracing on + agent run over planted PII → assert no PII/secret in the captured trace (SC-007).

**Checkpoint**: tracing safely re-enablable; SC-007 proven.

---

## Phase 7: User Story 5 — Close spec-8 constitution deviations (Priority: P2)

**Goal**: The two recorded triage deviations are formally closed, referencing the controls that replaced them.

**Independent Test**: Triage path redacts + guards before the external LLM call; deviation records updated to "closed".

**Depends on**: US1 (guardrails on triage) + US2 (redaction before triage call).

- [ ] T035 [US5] Mark both spec-8 deviations closed in `specs/008-triage-routing/` (plan Complexity Tracking) and `docs/DECISIONS.md`, referencing spec-12 controls (FR-025/SC-008).
- [ ] T036 [P] [US5] Assertion test confirming the triage path order is redact → guard → external call in `app/triage/llm.py` (lightweight; complements US1/US2 gates). **Also add a guarded-path inventory assertion** enumerating the four guarded sites (triage resolution, triage valence, drafting agent, document intake) and asserting each routes through `guard` — satisfies SC-001's "verified by inventory and test" (resolves analyze G3).

**Checkpoint**: constitution Complexity Tracking carries no open triage security deviations.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T037 [P] Add `docs/` runbook updates: guardrails sidecar ops, RLS role provisioning (`pantera_app`), redaction behavior, tracing re-enable procedure.
- [ ] T038 [P] Add `docs/DECISIONS.md` entries: guardrails engine choice (+ torch-free/nemoguardrails deviation if the literal library isn't used, research R1), RLS two-role design.
- [ ] T039 Run `quickstart.md` validation — all 5 scenarios on the live stack (RLS isolation, redaction leak=0, red-team block + fail-safe, trace redaction, deviation closure). Do NOT trust green checkmarks ([[verify-before-claiming-done]]).
- [ ] T040 Full gate: `ruff check` + `black --check` on `app worker guardrails tests`; `pytest tests/unit` + `pytest tests/integration` (live DB); coverage ≥80% overall (auth/HITL/DB-write ≥95%); both new eval gates pass. **Also verify SC-004 (no redaction regression):** run the existing triage golden-set and RAG golden-set eval gates with redaction active in the path, confirming triage recall + report grounding stay ≥ their committed `eval_thresholds.yaml` thresholds (confirm those gates exercise the redacted path; if they bypass it, add a redacted-path variant) — resolves analyze G2.

---

## Dependencies & Execution Order

### Phase order
- **Setup (P1)** → **Foundational (P2)** → **US1/US2/US3 (P3–5, all P1 priority)** → **US4/US5 (P6–7, P2)** → **Polish (P8)**.

### Cross-story dependencies (important)
- **US2 egress tasks (T024/T025) are sequential after US1 egress tasks (T014/T015)** — they edit the same two functions (`app/triage/llm.py`, `app/agent/graph.py`). Final order at each egress: `redact → guard(input) → call → guard(output)`. Build the guard wrapper (US1) first, then insert redaction before it (US2).
- **US4** depends on **US2** (T023 trace redaction). **US5** depends on **US1 + US2** (triage redact+guard).
- **US3 is fully independent** of US1/US2 (DB layer only) — can proceed in parallel.

### Within a story
- Tests can be written first ([P]); models/schemas before services; services before wiring.

### Parallel opportunities
- Setup: T002, T003, T005 in parallel (T001 first for deps; T004 after T003; T002a after T002 + T003 — needs the toggles + a loaded environment signal).
- Foundational: T006, T007 in parallel; T008 independent.
- US1 tests T009/T010 in parallel; US2 tests T018/T019 in parallel.
- US3 can run as a parallel track to US1/US2 (different files).

---

## Parallel Example: User Story 1

```bash
# Tests together:
Task: "Red-team gate test in tests/integration/test_guardrails_redteam.py"
Task: "Rails-engine unit tests in tests/unit/test_guardrails_rails.py"
# Then implementation (sidecar before client before egress wiring).
```

---

## Implementation Strategy

### MVP (smallest valuable slice)
1. Setup (Phase 1) + Foundational (Phase 2).
2. **US1 (guardrails)** — the highest-value security gap (closes spec-8 deviation b). STOP & validate with the red-team gate + a real fail-safe run.

### Incremental delivery (all three P1 are shippable increments)
- US1 → US2 (redaction; unblocks tracing + closes deviation a) → US3 (RLS; independent DB track) → US4/US5 (consequences) → Polish.
- US3 can be developed in parallel with US1/US2 by a second track since it touches only the DB layer + session plumbing.

### Validate before "done"
Per [[verify-before-claiming-done]]: actually run build/lint/tests + one real e2e per story (RLS isolation query, redaction leak=0, guardrails block + outage fail-safe). Two chain-breaking bugs in spec 11 were caught only by a real run — do the same here.

---

## Notes
- [P] = different files, no incomplete-task dependency.
- Every task: `ruff` + `black` clean; migration up AND down on a live DB; audit rows atomic on the caller's session; NO PII in any log/trace/event/external payload.
- New required secrets (`app_database_url`, `guardrails_token`) must be in Vault + CI inline writer + `write_secrets.py` + compose, or boot/tests fail fast.
