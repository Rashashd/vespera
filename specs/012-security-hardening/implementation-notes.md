# Implementation Notes — READ FIRST (anti-hallucination guide)

**Spec 012-security-hardening.** A weaker model will implement this cold in a fresh session. Everything below was VERIFIED against the live codebase on 2026-06-16. Do NOT import, call, or assume anything not confirmed here. When in doubt, grep — don't guess. Standing rule: [[anti-hallucination-spec-notes]], [[verify-before-claiming-done]].

---

## 0. Things that DO NOT EXIST yet (do not import them)

- ❌ `app/guardrails/` — **you create it**. No guardrails client exists today.
- ❌ `app/redaction/` — **you create it**. No redaction module exists.
- ❌ top-level `guardrails/` sidecar — **you create it** (copy the `modelserver/` layout).
- ❌ `app/db/rls.py` — **you create it** (`set_rls_context`).
- ❌ `Settings.guardrails_url`, `Settings.app_database_url`, `Settings.redaction_enabled`, `Settings.guardrails_enabled` — do not exist; add them to `app/core/config.py`.
- ❌ A `presidio` / `nemoguardrails` / `guardrails` dependency group — not in `pyproject.toml`. Add a new `guardrails` uv group + add `presidio-analyzer`/`presidio-anonymizer` + `en_core_web_sm` to the main deps (redaction runs in-process in the app/worker).
- ❌ `migration 0011` — latest is `0010_scheduling.py` (`revision="0010"`). Create `0011_rls_policies.py` with `down_revision = "0010"`.
- ❌ `security:` block in `eval_thresholds.yaml` — add it (see contracts).
- ❌ Any `set_config`/RLS usage anywhere today — the engine has no RLS context.
- ⚠️ `guardrails_token` DOES already exist in `Settings` (`config.py:36`) and is loaded (`startup.py:40`) but is NOT in `_REQUIRED_SECRETS`. Do not re-add the field; just promote it to `_REQUIRED_SECRETS` and add it to the Vault loader's data.get block already present.
- ⚠️ scispaCy `en_ner_bc5cdr_md` IS a dependency (`pyproject.toml:28`) but it is a **biomedical chemical/disease NER**, NOT a PII model. Do NOT use it for redaction. Presidio needs a PII spaCy model (`en_core_web_sm`).

## 1. Exact LLM egress sites (where redaction + guardrails wrap)

### Triage — `app/triage/llm.py`
- `_call_llm(...)` (line ~48) is the raw HTTP call (Anthropic/OpenAI branch). It is decorated with `@traced_llm_call` then `@retry(...)`. `_should_retry` (line ~35) retries on 5xx/timeout/network, never 4xx — mirror this in the guardrails client.
- `resolve_yes_no(text, ...)` (line ~127) and `assess_valence(text, ...)` (line ~157) build `user_content = text` and call `_call_llm`. **Redact `text` and run `guard(input)` here BEFORE `_call_llm`; run `guard(output)` on the returned `raw` before `model_validate`.** `resolve_yes_no` raises on failure (caller fail-safe escalates); `assess_valence` already returns `"positive"` (fail-safe) on any exception — keep that.
- Usage capture (`record_usage`) is best-effort in `_call_llm` (lines ~104-122) — don't disturb it.

### Agent — `app/agent/graph.py`
- `agent_node` (line ~42) calls `response = await chat_model.ainvoke(state["messages"])`. **This is the agent egress.** Redact the content of the messages before `ainvoke` and `guard(output)` on `response.content`. Messages include `SystemMessage` (prompt), `HumanMessage` (finding fields + prior draft), and `ToolMessage`s carrying retrieved passage text (from the `retrieve` tool, `tools.py:104`).
- `chat_model = build_agent_chat_model(settings).bind_tools(tools)` (line ~40) — `build_agent_chat_model` is in `app/agent/llm_binding.py`.
- **Grounding is safe:** `draft_report` validates `source_ref` against `Chunk.id` for the client in the DB (`tools.py:_validate_chunk_refs` ~66 and the distinct-document corroboration query ~195). Citations are chunk_id references, NOT the redacted prompt text — so redacting prompt text does NOT break grounding. (Resolves CHK022.)
- Fail-safe: on a blocked guard or guardrails-unavailable, raise so the graph escalates. The graph already converts tool errors/exceptions into escalation (`should_continue` → END on `escalated`; `run_agent` returns `escalated=True` on fatal error, line ~219). Prefer raising `EscalationSignal`/`ToolError` from a guard wrapper inside a tool, or set `escalated` in `agent_node`.

### Document intake — `app/ingestion/`
- Intake injection scan + quarantine is NEW. Find where a fetched document's raw text is first persisted (`app/ingestion/service.py` / the adapters write `documents` + `document_sources.raw_payload`). Add a `guard(text, direction="input", call_site="intake")` before the doc is accepted; on block or `GuardrailsUnavailable`, **quarantine** (do not create the INDEXED-eligible row / hold it out of indexing+triage) and raise `DocumentQuarantined`. Continue the cycle for other documents (FR-006a). Grep the ingestion service for where `DocumentSource`/`Document` rows are added before wiring.

## 2. Guardrails client — copy this pattern

Mirror `app/infra/modelserver_client.py` (httpx.AsyncClient + tenacity, `X-Service-Token` header, retry 5xx/timeout/network only). The triage `_should_retry` (`app/triage/llm.py:35`) is the canonical retry predicate. Service token = `settings.guardrails_token`; URL = `settings.guardrails_url`. On exhausted retries raise `GuardrailsUnavailable` (new exception in `app/guardrails/client.py`). See `contracts/guardrails-api.md`.

The sidecar itself: copy `modelserver/` structure (`modelserver/Dockerfile`, `modelserver/core/`, its `X-Service-Token` auth, its `/health` probe in `docker-compose.yml:91`). Keep it torch-free (own uv group; onnxruntime only if a classifier rail is added).

## 3. Redaction module — patterns

- Singleton analyzer like `app/triage/ner.py:_get_nlp` (`@lru_cache`). Offload `analyzer.analyze(...)` with `asyncio.to_thread` when called from async code (constitution: no blocking in async).
- `redact(text) -> RedactionResult` (text + (type,count) entities only; never the original value). See `contracts/redaction.md`.
- Log redaction: add a structlog processor in `app/observability/logging.py`. Check how logging is configured there first (`configure_logging`). The processor redacts string values in the event dict before the renderer.
- Trace redaction: `app/observability/tracing.py` already has `traced_llm_call` with `_redact_inputs`/`_redact_outputs` (drops to `_SAFE_INPUT_KEYS = ("client_id","max_tokens")`) for triage. Extend the agent path so its trace carries no content (FR-023). Re-read that file — do not duplicate the triage decorator.

## 4. RLS — exact wiring

### Migration 0011 (`app/db/migrations/versions/0011_rls_policies.py`)
- `revision = "0011"`, `down_revision = "0010"`. Copy the header/imports style of `0010_scheduling.py`.
- Use `op.execute("...")` with the policy template from `contracts/rls-policies.md` for each policied table (loop over a Python list of `(table, scope_col)` to stay DRY and auditable).
- `GRANT ... TO pantera_app` per table. Assume the role EXISTS (bootstrap-created); guard grants so a missing role gives a clear error.
- Downgrade: drop policy, `NO FORCE`, `DISABLE ROW LEVEL SECURITY`, revoke grants. Do NOT drop the role in downgrade.
- env.py (`app/db/migrations/env.py`) imports all model modules so `Base.metadata` is populated — **no change needed** unless you add a model (you don't). Migrations run on `database_url` (privileged) — correct as-is.

### Role + secret provisioning
- New role `pantera_app` created at DB bootstrap: add an init SQL to `docker-compose.yml` (postgres `volumes:` mount of an init script, or a one-shot), a CI step on the fresh Postgres service, and have `scripts/write_secrets.py` write `app_database_url = postgresql+asyncpg://pantera_app:<pw>@.../pantera`. Password must match the role.
- `app_database_url` + `guardrails_token` → add to `_REQUIRED_SECRETS` (`app/core/startup.py:13`) AND the CI inline secret writer in `.github/workflows/ci.yml` (spec-2 lesson: a new required secret missing from the CI writer fails alembic/tests fast). Also `scripts/write_secrets.py` and `docker-compose`.

### Engine + context
- `app/db/base.py:create_engine` (line 18-20): switch the RUNTIME engine to `app_database_url` and add `connect_args={"statement_cache_size": 0}`. The lifespan calls `create_engine(settings.database_url)` (`app/core/lifespan.py:65`) — change to `settings.app_database_url`. The worker bootstrap creates its own engine — switch it too (grep `worker/` for `create_engine`/`create_async_engine`).
- `app/db/rls.py:set_rls_context(session, *, client_id, is_staff)` — uses `text("SELECT set_config('app.current_client_id', :c, true)")` etc. (see contract). Transaction-local.
- Request set point: `app/auth/dependencies.py:current_active_principal` (line ~25), right after `fresh = await session.get(User, user.id)` (line ~34). Set client-user vs staff context. `acting_client` (line ~76) and routes depend on this and share the `get_session` transaction (`app/core/dependencies.py:21`, opens `session.begin()` at line 25) — context is set before any policied query. `users` is EXEMPT so the `session.get(User)` read works pre-context.
- Worker/pipeline/lifespan/agent sessions: call `set_rls_context(session, client_id=None, is_staff=True)` (system context) right after each `session.begin()`. **Enumerate every session-open site** (research R7): `app/core/lifespan.py` (bootstrap ensure_manager ~108, ingestion startup ~39 — these may run on the privileged role via migrations? No — lifespan uses the runtime engine, so they need system context), triage runner, `app/embedding/runner.py`, scheduling cadence loop, agent `run_agent` session. Missing one → that path's queries return 0 rows (loud failure, not a leak).

## 5. Config & secrets — exact edits

- `app/core/config.py` (Settings, `extra="forbid"`): add `guardrails_url: str = "http://guardrails:8002"`, `app_database_url: str = ""`, `redaction_enabled: bool = True`, `guardrails_enabled: bool = True`. (`guardrails_token` and `tracing_enabled` already exist.)
- **`guardrails_enabled`/`redaction_enabled` are NON-PRODUCTION/TEST-ONLY kill-switches** (FR-003 / FR-014a). They exist so test suites can isolate non-guardrails / non-redacted behavior — they MUST NEVER bypass the mandatory boundary in production. Add a production guard in `app/core/startup.py` (T002a): refuse to boot (or hard-fail the guarded call) if either is `False` in a prod environment. There is no `environment`/`is_production` Setting today — grep `config.py`/`startup.py`; if absent, add a single `environment: str = "development"` Setting and key the guard off it (do NOT scatter `os.getenv` — constitution: no `os.getenv` outside `config.py`). Disabling guardrails or redaction in prod is a Principle V / §Security violation.
- `app/core/startup.py`: `_REQUIRED_SECRETS = ("database_url", "redis_url", "auth_jwt_secret", "app_database_url", "guardrails_token")`; add `settings.app_database_url = data.get("app_database_url", "")` in `load_secrets_from_vault` (`guardrails_token` load already at line 40).
- No `os.getenv` outside `config.py` (constitution). Runtime knobs → Settings; CI thresholds → `eval_thresholds.yaml` ONLY (never loaded at runtime — spec-8 lesson).

## 6. Domain events & audit

- Add `GuardrailRefused`, `GuardrailUnavailable`, `DocumentQuarantined` to `app/domain/events.py` as `DomainEvent` subclasses. They are auto-registered for audit by `register_audit_handlers` which walks `DomainEvent.__subclasses__()` (`app/audit/handler.py:52-62`) — **no handler change needed**. Match the existing event dataclass shape (`actor_id`, `actor_type`, `client_id`/`target_client_id`); the handler reads `target_client_id` fallback (`handler.py:37`). Payloads = reason codes, NEVER document text/PII.
- To emit, dispatch through the in-process `EventDispatcher` (`app/core/dispatcher.py`) on the active session, same as existing emitters. Grep an existing emit site (e.g. triage/reports) for the exact `await dispatcher.dispatch(event, session)` signature before using.

## 7. CI / eval gate

- `eval_thresholds.yaml`: add the `security:` block (see `research.md` R8 / contracts). This file is CI-gate-only; nothing loads it at runtime.
- New gates run in the existing `eval` job in `.github/workflows/ci.yml`. If a gate touches ONNX artifacts, the job's `actions/checkout@v4` needs `lfs: true` (spec-7 lesson). Use service-name DB host in CI (`postgres:5432`); host ports (`5433`/`6380`) only locally.
- Tests: `tests/integration/test_rls_isolation.py` (needs real Postgres + both roles), `tests/integration/test_redaction_gate.py`, `tests/integration/test_guardrails_redteam.py`. Golden sets under `tests/data/`. Reuse the `make_client()` fixture (see [[test-isolation-pattern]]) and the host Vault-repoint procedure for local runs.

## 8. Per-task Definition of Done

For every task: `ruff check` + `black --check` clean (include `guardrails/` in the lint targets); migration runs up AND down on a live DB; coverage ≥80% overall (auth/HITL/DB-write ≥95%); audit rows atomic on the caller's session; NO PII in any log/trace/event/external payload; one real run validates behavior (RLS isolation query, redaction leak=0, guardrails block + fail-safe) per `quickstart.md` — do not trust green checkmarks (spec-10/11 lesson, [[verify-before-claiming-done]]).

## 9. Sharp edges (most likely to bite a cold implementer)

1. **Forgetting `set_rls_context` at a session-open site** → that path silently returns 0 rows (default-deny). Symptom: a pipeline stage "finds nothing." Audit every `session.begin()`.
2. **Using scispaCy for PII** → wrong entities. Use `en_core_web_sm` for Presidio.
3. **Putting RLS on `users`** → breaks login (pre-context lookup). It is EXEMPT.
4. **Role not created before migration in CI** → grants fail. Create `pantera_app` at DB bootstrap, before `alembic upgrade`.
5. **Redacting the persisted report body** → destroys clinical content. Redaction is EGRESS-ONLY.
6. **Adding torch to the guardrails sidecar** → constitution violation. Keep it torch-free.
7. **New required secret missing from CI inline writer** → alembic/tests fail fast (spec-2 lesson). Wire `app_database_url` everywhere secrets are written.
8. **`statement_cache_size` not disabled** → latent break under transaction pooling. Set it on the runtime engine now.
9. **Shipping `guardrails_enabled`/`redaction_enabled` without the prod guard (T002a)** → a deployed env could silently bypass a mandatory boundary (Principle V / §Security violation, FR-003/FR-014a). The toggles are test-only; the production refuse-to-boot guard is what makes them safe. Never honor a `False` toggle in production.
