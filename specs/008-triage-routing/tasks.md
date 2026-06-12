---
description: "Task list for Triage & Routing (Spec 8) implementation"
---

# Tasks: Triage & Routing

**Input**: Design documents from `specs/008-triage-routing/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Included — the spec mandates a CI golden-set eval (FR-015), fail-safe tests (SC-007),
client-isolation tests (SC-005); the constitution requires 95%+ coverage on the classifier path.

**Organization**: Grouped by user story (US1–US4 from spec.md) for independent implementation/testing.

> ⚠️ **READ FIRST — MANDATORY:** Before writing any code, read
> [`implementation-notes.md`](./implementation-notes.md) in full. It pins every existing API signature,
> the exact patterns to copy (with file:line references), the things that **do not exist yet** (the
> `LLMClient` has **no call method** — you build the HTTP call), and the config placement rules. Do not
> invent methods, fields, or imports. When in doubt, grep the repo to confirm before using something.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1–US4; Setup/Foundational/Polish carry no story label
- All paths are repository-root-relative.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Dependencies and package scaffolding.

- [x] T001 [P] Add `scispacy` + `en_ner_bc5cdr_md` (pinned wheel URL) to the app/worker dependency group in `pyproject.toml` (NOT the `modelserver` group — preserve the no-torch serving image); run `uv lock`.
- [x] T002 Add triage config. **Runtime knobs go in `Settings` (`app/core/config.py`)** — `modelserver_url: str = "http://modelserver:8001"`, `triage_confidence_threshold: float = 0.70`, `triage_staleness_max_age_minutes: int = 30`, `triage_llm_max_tokens: int = 256` (see implementation-notes §5; nothing loads `eval_thresholds.yaml` at runtime). **CI-gate floors go in `eval_thresholds.yaml`** — add a `triage:` block with `recall_min: 0.90` and `precision_min: 0.75` ONLY (read by the eval runner, not the app).
- [x] T003 Create the `app/triage/` package skeleton (`app/triage/__init__.py`, `app/triage/keywords/__init__.py`) and confirm `app/prompts/` exists for the new prompt files.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared spine every user story builds on — schema, model, enums, events, NER, classifier client.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T004 [P] Define triage enums `Bucket`, `FindingStatus`, `ResolutionPath` (StrEnum, mirrored by DB CHECKs) in `app/triage/enums.py`.
- [x] T005 Create migration `app/db/migrations/versions/0007_findings_and_custom_keywords.py` (`down_revision = "0006"`) — create `findings` (columns + `UNIQUE(document_id, drug, reaction)` + indexes on client_id/status/(client_id,bucket)) and add `clients.custom_severity_keywords` JSONB default `'[]'`. **Also add the `custom_severity_keywords` `mapped_column` to the `Client` ORM model in `app/clients/models.py`** (the migration changes the DB; the ORM model must match). Verify `alembic upgrade head` AND `alembic downgrade -1` both run clean.
- [x] T006 Create the `Finding` ORM model in `app/triage/models.py` mirroring migration 0007 (unique constraint, indexes, CHECKs). **Register it by adding `from app.triage import models as triage_models  # noqa: F401` to `app/db/migrations/env.py`** (next to the existing per-module model imports — this is how tables register on `Base.metadata`).
- [x] T007 [P] Extend `FindingClassified` in `app/domain/events.py` to add `resolution_path: str` and `routing_outcome: str` (keep auto-audit registration intact).
- [x] T008 [P] Define Pydantic schemas in `app/triage/schemas.py`: `FindingStateResponse` (API boundary) and internal `FindingOutcome` DTO (no ORM at boundaries).
- [x] T009 Implement the scispaCy BC5CDR loader + drug/reaction entity extraction in `app/triage/ner.py` (load model once as a lifespan/module singleton; run extraction via `asyncio.to_thread`; return CHEMICAL + DISEASE spans).
- [x] T010 Implement the modelserver `/classify` wrapper call in `app/triage/classify.py` (reuse `ModelserverClient`; return raw `confidence` + `is_adverse`).

**Checkpoint**: Schema, model, enums, events, NER, and classifier client are ready.

---

## Phase 3: User Story 1 - Document Triaged and Routed to Correct Queue (Priority: P1) 🎯 MVP

**Goal**: For each embedded document, produce a `findings` row with the correct bucket and routing
status across all five buckets (incl. regulatory-alert floor and LLM valence/low-confidence paths),
queryable via the read endpoint.

**Independent Test**: Seed five documents (one per bucket) + a weak-keyword regulatory alert; run the
index build; assert each finding's bucket/status and the audit row; confirm the read endpoint returns
the triage state.

### Tests for User Story 1

- [x] T011 [P] [US1] Unit tests for the severity rule (emergency/urgent/minor mapping, ICH criteria, regulatory-alert floor) in `tests/unit/test_triage_severity.py`.
- [x] T012 [P] [US1] Integration test routing all five buckets end-to-end per-document in `tests/integration/test_triage_pipeline.py`. MUST also assert: (a) each triaged finding has `corroboration_sources IS NULL` (FR-014); (b) the emitted `audit_log` row's payload contains `bucket`, `model_confidence`/confidence, `resolution_path`, and `routing_outcome` with no gaps (FR-011, SC-006).
- [x] T013 [P] [US1] Contract test for `GET /clients/{id}/findings/{finding_id}` (200 shape, 404 cross-tenant, 400 suspended) in `tests/integration/test_finding_state_endpoint.py`.

### Implementation for User Story 1

- [x] T014 [P] [US1] Implement the versioned ICH E2E seriousness keyword→tier artifact in `app/triage/keywords/ich_seriousness.py` (six criteria; reuse `SeverityLevel`).
- [x] T015 [US1] Implement severity bucketing (ICH defaults + regulatory-alert floor via `document.source_reliability`, reuse `SeverityLevel.rank`) in `app/triage/severity.py` (depends T014). Custom keywords are added in US3.
- [x] T016 [P] [US1] Author injection-hardened LLM prompts `app/prompts/triage_valence.txt` (receives `source_reliability`, FR-017; embed the verbatim `positive`/`irrelevant` definitions from implementation-notes §8.2 / spec FR-005) and `app/prompts/triage_lowconf_resolve.txt` (YES/NO).
- [x] T017 [US1] Implement the async LLM call path in `app/triage/llm.py` — provider from `build_llm_client`, `httpx.AsyncClient` + tenacity (`stop_after_attempt(3)`, never 4xx), structured JSON validated by Pydantic; map any post-retry failure to the fail-safe signal (depends T016).
- [x] T018 [US1] Implement the three-stage classify decision (`confidence ≥ settings.triage_confidence_threshold` → trust the model verdict; below → `llm.resolve_yes_no`; LLM failure → escalate=YES) extending `app/triage/classify.py`. Use the raw `confidence` field, NOT `is_adverse` (see implementation-notes §3) (depends T010, T017).
- [x] T019 [US1] Implement routing + idempotent upsert (bucket→status table; `INSERT ... ON CONFLICT (document_id,drug,reaction) DO NOTHING`) in `app/triage/routing.py` (depends T006).
- [x] T020 [US1] Implement the triage orchestration in `app/triage/service.py` as a **thin** coordinator that delegates each stage to its module (`prefilter`/`ner` → `classify` → `severity`/`llm` valence → `routing`) and dispatches `FindingClassified` inside the finding-write transaction for atomic audit (FR-011). Implement the FR-018 failure matrix exactly (implementation-notes §8.3): classifier/DB/config failure → **no finding**, emit `triage.operator_alert` ERROR (FR-019) with stage; LLM failure → finding via fail-safe (escalate / `positive`). Keep the file ≤ ~300 lines; push non-trivial logic into stage modules so US2/US3 edit their own files (depends T009, T015, T018, T019).
- [x] T021 [US1] Implement the per-document entrypoint `triage_document(...)` in `app/triage/runner.py` per the internal contract (returns `FindingOutcome[]`; structured logs bound with client_id + finding_id/document_id) (depends T020).
- [x] T022 [US1] Integrate `triage_document` into `app/embedding/runner.py` on the `DocumentIndexStatus.INDEXED` success path; triage failure logs + leaves the document in the "embedded, no finding" set without rolling back the embedding (depends T021).
- [x] T023 [US1] Implement the read endpoint `GET /clients/{id}/findings/{finding_id}` in `app/triage/routes.py` (client-scoped via `get_acting_client`; 404 cross-tenant) and register it in `app/main.py` (depends T008, T006).

**Checkpoint**: MVP — documents triage automatically into correct queues; state is queryable; decisions audited.

---

## Phase 4: User Story 2 - Drug Pre-Filter Prevents False Classifications (Priority: P2)

**Goal**: Documents that mention a watchlist drug only incidentally are filtered before classification,
with a logged reason.

**Independent Test**: Submit an incidental-mention document and a substantive-mention document; assert
the first is filtered (logged) and the second proceeds to a finding.

### Tests for User Story 2

- [x] T024 [P] [US2] Unit tests for the substantive-mention gate per implementation-notes §8.1 (incidental comparator with no same-sentence DISEASE → filtered; drug in title/summary OR co-occurring with a DISEASE in one sentence → pass) in `tests/unit/test_triage_prefilter.py`.

### Implementation for User Story 2

- [x] T025 [US2] Implement the substantive-mention pre-filter in `app/triage/prefilter.py` per the deterministic rule in implementation-notes §8.1 / spec FR-001 (normalized watchlist-drug CHEMICAL match over `title + "\n" + summary`; substantive = title/summary match OR same-sentence DISEASE co-occurrence; else incidental). Emit `triage.prefilter.filtered` (client_id, document_id, drug, reason) when filtered (depends T009).
- [x] T026 [US2] Wire the pre-filter into `app/triage/service.py` as a **single call-site insertion** ahead of classification so filtered documents produce no finding and short-circuit; keep all heuristic logic in `prefilter.py`, not `service.py` (depends T020, T025).

**Checkpoint**: US1 + US2 — incidental mentions no longer create spurious findings.

---

## Phase 5: User Story 3 - Per-Client Custom Severity Keywords (Priority: P3)

**Goal**: Per-client custom keywords escalate buckets for the owning client only, never downgrading.

**Independent Test**: Configure a keyword for client A; process the same finding text for A and B;
assert A escalates and B uses ICH defaults.

### Tests for User Story 3

- [x] T027 [P] [US3] Unit tests for the custom-keyword layer (escalate-only `max(rank)`; empty list → ICH defaults; no downgrade) and client isolation in `tests/unit/test_triage_custom_keywords.py`.

### Implementation for User Story 3

- [x] T028 [US3] Extend `app/triage/severity.py` with the custom-keyword layer (case-insensitive substring; `tier` ∈ {serious, life-threatening}; combine via `max(rank)` so it can only escalate) (depends T015).
- [x] T029 [US3] Pass the acting client's `custom_severity_keywords` (client-scoped) into severity bucketing. Load them via a small accessor (e.g. in `app/triage/severity.py` or a client-read helper) and keep the `service.py` change to passing the argument through — avoid growing `service.py` (depends T020, T028).

**Checkpoint**: US1–US3 — client-specific severity thresholds enforced without cross-client leakage.

---

## Phase 6: User Story 4 - Triage Bias Toward Escalation Is Measurable (Priority: P4)

**Goal**: A CI-gated golden-set eval proves recall ≥ 0.90 / precision ≥ 0.75 and an escalation-biased
failure direction; fail-safe behavior under LLM outage is verified.

**Independent Test**: Run the eval runner over the golden set; confirm both thresholds pass and the
escalation-direction check holds; inject an LLM fault and confirm escalate/positive defaults.

### Tests for User Story 4

- [x] T030 [P] [US4] Author the triage golden set `tests/data/triage_golden_set.jsonl` covering the six mandatory case categories (five buckets; regulatory floor; low-confidence→LLM; source_reliability absent; NO-classified regulatory alert → irrelevant; custom-keyword escalation) plus a planted-instruction injection case.
- [x] T031 [P] [US4] Fail-safe + failure-matrix tests (implementation-notes §8.3) in `tests/unit/test_triage_failsafe.py`: LLM outage → low-confidence escalates to expedited AND NO-finding defaults to `positive` (both logged); **classifier (`ModelserverError`) → no finding created + `triage.operator_alert` ERROR (stage=classify)**; **DB upsert/audit failure → transaction rolls back, no finding, `triage.operator_alert` (stage=persist)**.

### Implementation for User Story 4

- [x] T032 [US4] Implement the triage eval runner in `tests/integration/test_triage_eval.py` (compute precision/recall vs `eval_thresholds.yaml`; assert recall ≥ 0.90 AND precision ≥ 0.75 — either-below fails; assert false-negatives < false-positives for SC-003) (depends T030).
- [x] T033 [US4] Wire the triage eval gate into the CI `eval` job in `.github/workflows/ci.yml` (alongside the classifier/RAG gates; `lfs: true` already present); ensure regression blocks merge (depends T032).

**Checkpoint**: All user stories functional; safety bias proven by a committed number in CI.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Reliability backstop, observability, docs, quality gates.

- [x] T034 Implement the staleness sweep in `app/triage/sweep.py` (find `DocumentIndexStatus.INDEXED` documents with zero `findings` rows older than `settings.triage_staleness_max_age_minutes`; structured-log + operator signal) for SC-001.
- [x] T035 [P] Review per-stage structured logging (pre-filter / classify / bucket-or-valence / route) — each binds `client_id` + `finding_id`/`document_id`, never PII/secrets.
- [x] T036 [P] Update `docs/DECISIONS.md` (scispaCy reaction-extraction choice; LLM-ahead-of-guardrails sequenced deviation) and `docs/RUNBOOK.md` (scispaCy model download step).
- [x] T037 Run `uv run ruff check` AND `uv run black --check app worker tests` AND `uv run pytest --cov` — confirm 80% overall / 95%+ on the triage classifier path.
- [x] T038 Execute `specs/008-triage-routing/quickstart.md` scenarios 1–7 against the live stack and record results.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup — BLOCKS all user stories.
- **US1 (Phase 3)**: depends on Foundational. The MVP.
- **US2 (Phase 4)**: depends on Foundational + T020 (service) from US1.
- **US3 (Phase 5)**: depends on Foundational + T015/T020 from US1.
- **US4 (Phase 6)**: depends on the pipeline existing (US1); golden-set authoring (T030) can start once buckets are defined.
- **Polish (Phase 7)**: after the desired stories are complete.

### Story Independence Notes

- US1 is independently shippable (full happy-path triage + routing + read endpoint).
- US2 hardens the pre-filter US1 already invokes — testable on its own via incidental vs substantive docs.
- US3 adds only the custom-keyword layer — testable in isolation per client.
- US4 is the eval/CI gate — testable by running the golden set.

### Parallel Opportunities

- Setup: T001, T002 in parallel (T003 after).
- Foundational: T004, T006, T007, T008 in parallel; T005 (migration) before/independent of T006; T009, T010 in parallel after the package exists.
- US1 tests: T011, T012, T013 in parallel (write first, expect fail).
- US1 impl: T014 and T016 in parallel; the service chain T015→T018→T019→T020→T021→T022 is largely sequential (shared files / data flow).
- Cross-story: once Foundational is done, US2/US3/US4 authoring can proceed alongside US1 polish with care on `service.py`/`severity.py` (shared files — sequence those edits).

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1 → **STOP & VALIDATE** (quickstart scenarios 1 & 4) → demo.

### Incremental Delivery

US1 (MVP: routing + 5 buckets + floor) → US2 (pre-filter hardening) → US3 (custom keywords) →
US4 (eval gate in CI) → Polish (sweep, logging, docs, quickstart). Each adds value without breaking
prior stories.

---

## Notes

- `[P]` = different files, no incomplete-task dependency.
- `service.py` is a thin orchestrator (T020); US2/US3 add logic to `prefilter.py`/`severity.py`, touching `service.py` only via a single call-site/argument change. Still sequence the `service.py` and `severity.py` edits across stories rather than parallelizing them.
- Keep every file ≤ ~300 lines with a one-sentence module docstring; split if it grows.
- Conventional Commits, no Co-Authored-By trailer; commit after each task or logical group.
- The `confidence_threshold`/`staleness_max_age`/golden-set floors are starting values — tune against
  the golden set during US4 and re-commit if the eval justifies it (Constitution IV).
