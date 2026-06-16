# Implementation Plan: Security Hardening

**Branch**: `012-security-hardening` | **Date**: 2026-06-16 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/012-security-hardening/spec.md`

> **READ FIRST before implementing:** [implementation-notes.md](./implementation-notes.md) — anti-hallucination guide pinning exact live APIs, what does NOT exist yet, and patterns to copy. A weaker model implements this cold in a fresh session; do not import or call anything not verified there.

## Summary

Harden the existing Pantera pipeline along three independent security layers plus close two recorded triage deviations and re-enable tracing:

1. **Guardrails sidecar** — a lean, torch-free, no-LLM HTTP service exposing `POST /guard` (platform rails: prompt-injection, jailbreak, topic-scope, cross-client). The app wraps every external-LLM egress (triage `_call_llm`, agent `chat_model.ainvoke`) and the document-intake path; both **input and output** are checked. Service auth = `X-Service-Token` (`guardrails_token`). Fail-safe: triage escalates, agent escalates, intake quarantines.
2. **Presidio redaction** — an in-process redaction pass applied at every egress point (external LLM call, log line, trace, derived summary), uniformly across all text sources (document/finding/report/config). PII = patient identifiers; secrets = key/token patterns. Persisted report body/findings/chunks are NOT redacted. Runs **before** guardrails and the external call.
3. **Postgres RLS** — `FORCE ROW LEVEL SECURITY` + role-aware policies on all `client_id`-bearing tables (users + clients special-cased). Runtime connects as a new least-privilege role (`app_database_url`); migrations/seed keep the privileged `database_url`. Per-transaction context via `set_config('app.current_client_id'/'app.is_staff', ..., true)` set right after the principal is resolved. Default-deny when unset.
4. **Deviation closure + tracing** — redaction lands before the triage LLM call (closes spec-8 deviation a); guardrails cover triage (closes deviation b); tracing can be re-enabled and the agent trace verified PII-free.

**Technical approach:** one Alembic migration (0011) for RLS policies + GRANTs; two new `app/` packages (`app/guardrails/` client + `app/redaction/`); a new top-level `guardrails/` sidecar service (mirrors `modelserver/` layout); wiring at the two LLM egress sites + intake + the request/worker session-context setter; two new CI eval gates (redaction, guardrails red-team) in `eval_thresholds.yaml`; new secrets `app_database_url` + `guardrails_token` (promote to `_REQUIRED_SECRETS`) and non-secret `guardrails_url`.

## Technical Context

**Language/Version**: Python 3.13 (project `requires-python >=3.12`); uv-managed.

**Primary Dependencies**: FastAPI, SQLAlchemy 2.x async + asyncpg, LangGraph + langchain-anthropic/openai, httpx + tenacity, structlog, Presidio (`presidio-analyzer` + `presidio-anonymizer` + a spaCy model), guardrails sidecar (lean FastAPI; onnxruntime only if a classifier rail is added — **no torch**).

**Storage**: PostgreSQL 16 + pgvector (RLS policies added; no new business tables). Redis (unchanged).

**Testing**: pytest (unit + integration, `PANTERA_INTEGRATION=1` on a live DB); two new eval gates run in the CI `eval` job. RLS isolation tests need a real Postgres (not SQLite).

**Target Platform**: Linux server containers (api, worker, modelserver, **guardrails (new)**, frontend) + managed Postgres/Redis/Vault.

**Project Type**: Modular monolith + justified sidecars (modelserver, ARQ worker, **NeMo Guardrails**, React SPA — all four named in Constitution VI).

**Performance Goals**: No committed latency SLA in this feature (deferred — see Complexity/Assumptions). Redaction + guardrails add two in-region hops per guarded LLM call; rails are local/heuristic (no LLM round trip) to keep added latency low and deterministic.

**Constraints**: Guardrails sidecar MUST stay torch-free (Constitution VI). Redaction MUST not log raw text. RLS context MUST be per-transaction (no leak across pooled connections); asyncpg statement caching disabled where it would break per-transaction context (PgBouncer-forward). Default-deny on missing RLS context.

**Scale/Scope**: ~22 `client_id`-bearing tables get RLS; 2 LLM egress sites + 1 intake path get guardrails+redaction; B2B scale (tens of clients), not consumer scale.

## Constitution Check

*GATE: must pass before Phase 0 and re-checked after Phase 1.*

| Principle | Status | Notes |
|---|---|---|
| I. Human-in-the-Loop | ✅ unaffected | No change to the HITL gate; guardrails on the agent path strengthen it. |
| II. Grounding Is the Grade | ✅ strengthened | Injection resistance moves from prompt-only to a CI-gated guardrails boundary (input+output). Redaction at the LLM egress redacts prompt text but citations are `chunk_id` refs validated server-side against un-redacted DB chunks (`tools.py:173`), so grounding is preserved. New red-team gate. |
| III. Triage Fails Safe | ✅ preserved | Guardrails-down on triage → escalate (existing fail-safe). |
| IV. Every Decision Backed by a Number | ✅ | Two new gates with thresholds in `eval_thresholds.yaml` (redaction leak=0; red-team block-rate). |
| V. Multi-Tenant Isolation & Data Protection | ✅ core of this feature | RLS = DB-level isolation; Presidio redaction = the named PII control; staff cross-client retains target-client audit attribution (compensating control a). |
| VI. Lean, Reproducible, Justified Architecture | ✅ with care | Guardrails sidecar is a constitution-named container; it MUST stay torch-free and no-LLM. Presidio runs in-process (no new serving container). See research R1 for the torch-free verification gate. |
| VII. Own Every Line | ✅ | Spec-driven; implementation-notes.md grounds every API. |
| Security & Secrets section | ✅ | New secrets via Vault only (`app_database_url`, promote `guardrails_token`); added to `_REQUIRED_SECRETS` + CI inline writer + `write_secrets.py` + compose. Guardrails mandatory boundary realized. Startup refuses boot if required secrets missing (existing mechanism). |

**Initial gate: PASS** (no unjustified violations). One watch-item carried to research: guardrails library/torch (R1).

## Project Structure

### Documentation (this feature)

```text
specs/012-security-hardening/
├── plan.md                      # This file
├── research.md                  # Phase 0 — decisions (R1..R8)
├── data-model.md                # Phase 1 — RLS policy model, redaction/guard schemas (no new business tables)
├── quickstart.md                # Phase 1 — runnable validation (RLS isolation, redaction, guardrails)
├── implementation-notes.md      # READ FIRST anti-hallucination guide (grounded to live code)
├── contracts/
│   ├── guardrails-api.md         # POST /guard request/response + /health
│   ├── rls-policies.md           # policy SQL template + per-table list + role/GUC contract
│   └── redaction.md              # redaction function contract + entity/secret categories
└── checklists/
    ├── requirements.md           # spec quality (16/16)
    └── security.md               # security & compliance requirements checklist (CHK001-045)
```

### Source Code (repository root)

```text
app/
├── guardrails/                  # NEW — client to the sidecar
│   ├── __init__.py
│   ├── client.py                #   httpx + tenacity; mirrors app/infra/modelserver_client.py; X-Service-Token
│   └── schemas.py               #   GuardRequest/GuardResponse pydantic models
├── redaction/                   # NEW — Presidio in-process redaction
│   ├── __init__.py
│   ├── redactor.py              #   redact(text) -> RedactionResult; singleton analyzer (lru_cache)
│   └── recognizers.py           #   secret-pattern + PV-specific recognizers
├── db/
│   ├── rls.py                   # NEW — set_rls_context(session, client_id|None, is_staff) helper
│   ├── base.py                  # EDIT — engine uses app_database_url; disable stmt cache (R6)
│   └── migrations/versions/0011_rls_policies.py   # NEW — ENABLE/FORCE RLS + policies + GRANTs
├── observability/
│   └── logging.py               # EDIT — structlog processor redacts PII before emit (FR-009)
│   └── tracing.py               # EDIT — agent-path trace redaction + re-enable note (FR-023)
├── triage/llm.py                # EDIT — redact + guard around _call_llm (input+output)
├── agent/graph.py               # EDIT — redact + guard around chat_model.ainvoke (input+output)
├── ingestion/…                  # EDIT — intake injection scan + quarantine path (FR-006a)
├── auth/dependencies.py         # EDIT — set RLS context after current_active_principal
├── core/{config.py,startup.py}  # EDIT — guardrails_url + app_database_url; _REQUIRED_SECRETS
└── domain/events.py             # EDIT — GuardrailRefused / GuardrailUnavailable / DocumentQuarantined events

guardrails/                       # NEW top-level sidecar (mirrors modelserver/ layout)
├── Dockerfile                    #   lean, torch-free
├── app.py                        #   FastAPI: POST /guard, GET /health
└── core/                         #   rails engine (heuristic input/output rails)

worker/…                          # EDIT — worker sessions set system RLS context (is_staff/system)
tests/{unit,integration}/…        # NEW — RLS isolation, redaction golden set, guardrails red-team
eval_thresholds.yaml              # EDIT — security: redaction + guardrails gates
.github/workflows/ci.yml          # EDIT — guardrails service + new secrets in inline writer + eval gates
docker-compose.yml                # EDIT — guardrails service; app uses app_database_url; role bootstrap
```

**Structure Decision**: Follow the established package-per-concern layout. The guardrails sidecar copies the `modelserver/` precedent (own folder, own uv group, own Dockerfile, service-token auth). Redaction is in-process (no container — Presidio is a library, and Constitution VI forbids unjustified containers). RLS is migration + a thin `app/db/rls.py` helper invoked at the request and worker session boundaries.

## Complexity Tracking

No constitution violations requiring justification. Two scope decisions recorded for transparency (not violations):

| Decision | Why | Note |
|---|---|---|
| Guardrails sidecar may not use the literal `nemoguardrails` package | Constitution VI bars torch in serving containers; rails are local/heuristic + no-LLM for deterministic CI gating | If `nemoguardrails` installs torch-free it MAY back the sidecar; otherwise a lean purpose-built rails engine exposes the same `/guard` contract. Resolved in research R1; record as a justified deviation in `DECISIONS.md` if the literal library is not used. |
| No committed latency SLA | Hardening feature; correctness/safety first. Rails are local (no LLM hop) to keep cost down | CHK043 — latency budget explicitly deferred, not forgotten. |
