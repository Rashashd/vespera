# Implementation Plan: Triage & Routing

**Branch**: `008-triage-routing` | **Date**: 2026-06-12 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/008-triage-routing/spec.md`

## Summary

Triage is the decision gate between the RAG index build (spec 6) and report drafting (spec 9).
For each newly-embedded document it: (1) verifies a watchlist drug is substantively mentioned and
extracts the drug + reaction entities (NER pre-filter), (2) runs the trained adverse-event classifier
(YES/NO + confidence) with an LLM fallback for low-confidence cases, (3) assigns a severity bucket via
a transparent ICH-keyword rule extended by per-client custom keywords and a regulatory-alert floor, or
an LLM valence call for NO findings, and (4) creates a `findings` row already routed to the expedited
queue, the batch queue, or terminal `classified`. Spec 8 owns a new migration (0007) creating the
`findings` table and adding the `clients.custom_severity_keywords` column, a new `app/triage/` package,
the first real outbound LLM call path, and a CI-gated triage golden-set eval
(recall ≥ 0.90, precision ≥ 0.75). Triage runs in-process per-document off the embedding runner;
durable per-document ARQ jobs are deferred to spec 11.

## Technical Context

**Language/Version**: Python 3.13 + uv (matches existing repo)

**Primary Dependencies**: FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, structlog, tenacity,
httpx (async LLM + modelserver calls); **new:** `scispacy` + `en_ner_bc5cdr_md` (BC5CDR
chemical+disease NER) for the drug pre-filter and reaction extraction. No torch in any serving
container (scispaCy runs in the app/worker pipeline, not the modelserver).

**Storage**: PostgreSQL + pgvector. New `findings` table (migration 0007); additive
`clients.custom_severity_keywords` JSONB column.

**Testing**: pytest (`uv run pytest`); integration tests need `PANTERA_INTEGRATION=1` + docker compose.
New triage golden-set eval runner extends the existing CI `eval` job pattern
(`modelserver/eval/run_eval.py` → add a triage gate reading `eval_thresholds.yaml`).

**Target Platform**: Linux server (modular monolith + ARQ worker); same containers as today.

**Project Type**: Web service backend (modular monolith); new internal `app/triage/` module.

**Performance Goals**: Urgent/emergency findings reach `pending_expedited` within 5 minutes of
ingestion (SC-008). In-process per-document triage meets this trivially at the expected corpus scale
(tens–low hundreds of docs/cycle).

**Constraints**: Async throughout (httpx.AsyncClient + tenacity `stop_after_attempt(3)`, never on 4xx).
Triage decisions audited atomically within the finding-write transaction. Client-scoped at the
repository layer. Files ≤ ~300 lines; one-sentence module docstrings. No `os.getenv()` outside config.

**Scale/Scope**: ~10–15 new source files under `app/triage/`, one migration, one ICH keyword artifact,
two LLM prompts, one read endpoint, one golden-set + eval runner + CI wiring.

## Constitution Check

*GATE: evaluated against `.specify/memory/constitution.md` v1.2.0.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Human-in-the-Loop Authority | ✅ PASS | Triage only routes into queues; it neither drafts nor sends. No send path touched. |
| II. Grounding Is the Grade | ⚠️ PARTIAL → see Complexity | The LLM valence/resolution calls feed on ingested document text → prompt-injection surface. Full NeMo Guardrails are spec 12. v1 mitigates with a hardened system prompt that frames document text as untrusted data, and a planted-instruction case in the triage golden set. Residual risk closed by spec 12. |
| III. Triage Fails Safe | ✅ PASS | Core of this spec: low-confidence → LLM → escalate-on-LLM-failure (FR-002/016); recall floor 0.90 > precision floor 0.75; escalation-direction gate (SC-003). |
| IV. Every Decision Backed by a Number | ✅ PASS | Triage golden set + `eval_thresholds.yaml` committed floors; CI blocks on regression (FR-015). |
| V. Multi-Tenant Isolation & Data Protection | ⚠️ PARTIAL → see Complexity | Client-scoping enforced (FR-012). PII redaction (Presidio) before the LLM call is spec 12; v1 sends document text to the LLM provider as the pipeline already will for drafting. Documented, sequenced deviation. |
| VI. Lean, Reproducible, Justified Architecture | ✅ PASS (justified) | New `scispacy` dependency justified in Complexity Tracking; no new container; no torch in serving image. |
| VII. Own Every Line | ✅ PASS | Spec-driven; Conventional Commits; PR < 400 lines (may split into US-sized PRs). |

**Gate result: PASS** with two documented, intentionally-sequenced deviations (Principles II & V),
both closed by spec 12 (guardrails + redaction). Recorded in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/008-triage-routing/
├── plan.md              # This file
├── implementation-notes.md  # READ FIRST — pinned APIs, exact patterns, anti-hallucination guide
├── research.md          # Phase 0 — key decisions (NER/reaction source, trigger, LLM path, threshold)
├── data-model.md        # Phase 1 — findings table, custom_severity_keywords, migration 0007
├── quickstart.md        # Phase 1 — runnable validation scenarios
├── contracts/
│   ├── finding_state.read.md     # FR-013 GET finding triage state
│   └── triage_runner.internal.md # internal per-document triage entrypoint contract
├── checklists/
│   ├── requirements.md
│   └── triage-pipeline.md
└── tasks.md             # Phase 2 (/speckit-tasks — not created here)
```

### Source Code (repository root)

```text
app/
  triage/
    __init__.py
    enums.py            # Bucket, FindingStatus, ResolutionPath StrEnums + CHECK mirrors
    models.py           # Finding ORM (findings table)
    schemas.py          # Pydantic: FindingStateResponse, internal DTOs (no ORM at boundaries)
    ner.py              # scispaCy bc5cdr loader + drug/reaction entity extraction (pre-filter input)
    prefilter.py        # FR-001 substantive-mention gate against the client's watchlist drugs
    classify.py         # modelserver /classify call + confidence-threshold decision (FR-002)
    llm.py              # first real outbound LLM call: YES/NO resolution + valence (FR-002/005/016/017)
    severity.py         # ICH keyword rule + custom keywords + regulatory floor (FR-003/004)
    routing.py          # bucket → status mapping + idempotent finding upsert (FR-006/007/008/010)
    service.py          # orchestrates pre-filter → classify → bucket/valence → route; raises events
    runner.py           # per-document triage entrypoint invoked by the embedding runner (FR-009)
    routes.py           # GET /clients/{id}/findings/{finding_id} triage state (FR-013)
    sweep.py            # staleness sweep: embedded docs with no finding past max age (SC-001)
    keywords/
      ich_seriousness.py # versioned ICH E2E keyword→tier artifact (application code)
  prompts/
    triage_valence.txt          # NO-finding positive/irrelevant, receives source_reliability (FR-017)
    triage_lowconf_resolve.txt  # low-confidence YES/NO re-decision (FR-002)
  domain/
    events.py           # extend FindingClassified (+ client_id, resolution_path, routing_outcome)
  db/migrations/versions/
    0007_findings_and_custom_keywords.py

tests/
  unit/
    test_triage_severity.py     # keyword rule, custom keywords, regulatory floor, no-downgrade
    test_triage_prefilter.py    # substantive vs incidental mention
    test_triage_routing.py      # bucket→status, idempotency by (document_id, drug, reaction)
    test_triage_failsafe.py     # LLM-unavailable escalation + valence positive-default
  integration/
    test_triage_pipeline.py     # end-to-end per-document triage over seeded documents
    test_triage_eval.py         # golden-set precision/recall gate (recall≥0.90, precision≥0.75)
  data/
    triage_golden_set.jsonl     # ≥6 mandatory case categories (see spec Assumptions)

app/core/config.py              # add Settings: modelserver_url, triage_confidence_threshold, triage_staleness_max_age_minutes, triage_llm_max_tokens
eval_thresholds.yaml            # add triage: {recall_min: 0.90, precision_min: 0.75}  (CI-gate floors ONLY; runtime knobs are in Settings)
.github/workflows/ci.yml        # extend eval job to run the triage gate
pyproject.toml                  # add scispacy + en_ner_bc5cdr_md (pipeline group, not modelserver)
```

**Structure Decision**: New self-contained `app/triage/` package mirroring the established
`app/rag/` layout (enums / models / schemas / service / routes + focused helpers), each file
single-purpose and ≤ ~300 lines. Triggered in-process by the existing `app/embedding/runner.py`
per-document path; no new container and no ARQ dependency in v1 (durable jobs land in spec 11).

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| New `scispacy` + `en_ner_bc5cdr_md` dependency (Principle VI) | The finding grain is `(document_id, drug, reaction)`. BC5CDR NER supplies both the drug-mention verification for the pre-filter (FR-001) *and* the disease/reaction entity that forms the finding key. It is the brief-specified component. Runs in the app/worker pipeline, not the modelserver serving image, so the no-torch serving constraint is untouched. | Pure substring matching against watchlist drug names verifies the drug but yields **no reaction term**, leaving the finding grain unsatisfiable without an LLM extraction call per document (higher cost, less deterministic, weaker auditability). Asking the LLM for the reaction also widens the injection surface. NER is the leaner, more deterministic, brief-aligned choice. |
| LLM call without NeMo Guardrails / Presidio (Principles II & V) | Triage needs LLM valence + low-confidence resolution now; the guardrails sidecar and Presidio redaction are scheduled for spec 12. Blocking spec 8 on spec 12 would invert the planned build order. | Shipping no LLM fallback would force every low-confidence finding to auto-escalate, producing the noisy expedited queue the user explicitly rejected. v1 mitigates with a hardened "treat document text as data" system prompt + a planted-injection golden-set case; spec 12 adds the full rails and redaction. Deviation is bounded and sequenced. |

**✅ CLOSED by spec 12 (012-security-hardening), 2026-06-16.** Both deviations above are resolved:
(a) Presidio redaction now runs **before** the triage LLM call (`app/triage/llm.py` order:
redact → guard(input) → call → guard(output); FR-012) — Principle V residual closed. (b) The
torch-free NeMo-Guardrails sidecar wraps both triage egress sites (resolution + valence) with
input/output rails (injection/jailbreak/topic-scope/cross-client), CI-gated by the red-team gate
(block-rate=1.0, false-refusal=0) — Principle II residual closed. See spec-12 FR-025/SC-008 and
`docs/DECISIONS.md` (Security Hardening).
