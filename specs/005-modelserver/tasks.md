---
description: "Task list for Modelserver (Spec 5) implementation"
---

# Tasks: Modelserver — Adverse-Event Classifier & Medical Embedder

**Input**: Design documents from `specs/005-modelserver/`

**Prerequisites**: plan.md, spec.md, research.md (D1–D16), data-model.md, contracts/

**Tests**: INCLUDED — the constitution mandates testing gates (classifier-path ≥95%, overall ≥80%)
and the spec defines acceptance scenarios + the macro-F1 eval gate.

**Organization**: Grouped by user story (US1–US5 from spec.md) for independent implementation/testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US5; Setup/Foundational/Polish carry no story label
- Exact file paths included

## Path notes
- New lean serving container under `modelserver/`; offline training under `notebooks/`; caller client
  under `app/infra/`; eval gate at repo root + `modelserver/eval/`; tests under `tests/`.
- The modelserver is **stateless — no DB, no Alembic migration**.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project scaffolding and the lean-container build plumbing.

- [X] T001 Create the `modelserver/` package skeleton (`modelserver/__init__.py`, `inference/__init__.py`, `models/`, `eval/` dirs) each file opening with a one-sentence module docstring, per plan.md structure
- [X] T002 Add two `uv` dependency groups to `pyproject.toml`: a SELF-CONTAINED `modelserver` group enumerating the full serving set (fastapi, uvicorn, onnxruntime, numpy, tokenizers, pydantic, pydantic-settings, structlog, hvac, secure; + scikit-learn only if a classical classifier ships) and a `training` group (offline: torch, transformers, optimum[onnxruntime], datasets, scikit-learn, skl2onnx, evaluate, jupyter); keep both OUT of `[project].dependencies` (D1)
- [X] T003 [P] Create `modelserver/Dockerfile` — lean image installing ONLY the `modelserver` group AND excluding the app's own deps via `uv sync --only-group modelserver --no-install-project`, copying `modelserver/` + artifacts, running uvicorn; verify no torch and image < 500 MB (D1/FR-009)
- [X] T004 [P] Add a `modelserver` service to `docker-compose.yml` (build `modelserver/Dockerfile`, `VAULT_ADDR`/`VAULT_TOKEN` env only, exposed port, `depends_on: vault`)
- [X] T005 [P] Extend coverage/lint config in `pyproject.toml` to include `modelserver` in `[tool.coverage.run].source` and ensure ruff/black target `modelserver`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The serving app skeleton, secrets, auth mechanism, manifest, tokenization, schemas, and
test fixtures that EVERY user story needs.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T006 [P] Implement `modelserver/config.py` — pydantic-settings (`extra="forbid"`): `vault_addr`, `vault_token`, `model_dir`, `max_batch=128`, `max_tokens=512`; no `os.getenv` outside this file
- [X] T007 [P] Implement `modelserver/startup.py` — `load_secret()` fetching `modelserver_token` from Vault via `hvac` (refuse boot if empty), mirroring `app/core/startup.py` pattern (D5)
- [X] T008 [P] Implement structlog JSON logging setup for the modelserver binding `operation`/`batch_size`/`latency_ms`/`model_version`; never log payloads/PII/secrets (D16/FR-020)
- [X] T009 [P] Implement `modelserver/manifest.py` — load/parse `models/manifest.json`, expose per-artifact model-version identifiers (name/version/sha256/dim/max_tokens) per `contracts/model-manifest.md` (D4/D9)
- [X] T010 [P] Implement `modelserver/inference/tokenize.py` — load `tokenizer.json` via `tokenizers` (no torch), tokenize with `truncation=True, max_length=512`, emit `input_truncated` warning (counts only) when pre-truncation length > 512 (D8/D12/FR-005a)
- [X] T011 [P] Implement `modelserver/auth.py` — `X-Service-Token` FastAPI dependency, `hmac.compare_digest` constant-time check → missing `401`, invalid `403` (D5/FR-015)
- [X] T012 [P] Implement `modelserver/schemas.py` — base request (`texts: list[str]`, `min_length=0, max_length=128`) and version-stamped result models per `contracts/classify.md`/`embed.md` (FR-003/FR-005b)
- [X] T013 Implement `modelserver/main.py` — FastAPI app factory + lifespan (load token, then call the artifact-load+validate hook, register artifacts via manifest, wire logging), `secure` security headers, router registration (depends on T006–T012). The lifespan MUST invoke the integrity-validation entry point whose strict refuse-boot logic is implemented/strengthened in T031 (US4) — leave the call site in place here so US4 only fills in enforcement, with no missed wiring (F5)
- [X] T014 [P] Add tiny committed test fixture artifacts under `tests/fixtures/modelserver/` (a minimal ONNX/joblib classifier, a minimal embedder + `tokenizer.json`, and a `manifest.json` with their real SHA-256s) so service tests need no large download/network

**Checkpoint**: The modelserver app boots against fixtures; secrets, auth, manifest, tokenization in place.

---

## Phase 3: User Story 1 — Classify a finding as adverse/not-adverse (Priority: P1) 🎯 MVP

**Goal**: `POST /classify` returns raw confidence ∈ [0,1] + YES/NO at the 0.5 default cutoff, batched
and deterministic, version-stamped.

**Independent Test**: Send a known-positive and known-negative passage (with a valid token) → YES/NO
with confidence; same input twice → identical output; batch preserves order.

### Tests for User Story 1

- [X] T015 [P] [US1] Contract/integration test `tests/integration/test_classify_contract.py` — batch order, confidence∈[0,1], `is_adverse` at cutoff 0.5, determinism, per-result `model_version` (uses fixture model)

### Implementation for User Story 1

- [X] T016 [P] [US1] Implement `modelserver/inference/classifier.py` — load classifier session (onnxruntime/joblib, CPU provider, deterministic), `predict(texts) -> [(confidence, is_adverse≥0.5)]` (D2/D6/FR-001/FR-004)
- [X] T017 [US1] Implement `POST /classify` in `modelserver/routes.py` — validate (≤128), tokenize+truncate, run classifier, stamp classifier `model_version`, return ordered results; `503` until ready (depends on T016)
- [X] T018 [US1] Add classify request/response Pydantic schemas to `modelserver/schemas.py` and structured logging for the operation (no payloads)

**Checkpoint**: US1 fully functional and testable on its own (MVP).

---

## Phase 4: User Story 2 — Produce medical embeddings (Priority: P2)

**Goal**: `POST /embed` returns deterministic 768-dim L2-normalized vectors, batched, version-stamped.

**Independent Test**: Embed a chunk → 768 floats; same chunk twice → identical; two similar passages
closer (cosine) than to an unrelated one; empty list → `[]`.

### Tests for User Story 2

- [X] T019 [P] [US2] Contract/integration test `tests/integration/test_embed_contract.py` — 768-dim, determinism, batch order, empty-batch `[]`, semantic-sanity cosine check, per-result `model_version`

### Implementation for User Story 2

- [X] T020 [P] [US2] Implement `modelserver/inference/embedder.py` — onnxruntime session + mean-pool + L2-normalize → 768-dim numpy vector; deterministic (D3/D6/FR-002)
- [X] T021 [US2] Implement `POST /embed` in `modelserver/routes.py` — validate (≤128), tokenize+truncate, run embedder, stamp embedder `model_version`, ordered results (depends on T020)
- [X] T022 [US2] Add embed request/response schemas to `modelserver/schemas.py` and operation logging

**Checkpoint**: US1 and US2 both work independently.

---

## Phase 5: User Story 3 — Choose the shipped classifier with committed comparison (Priority: P2)

**Goal**: Offline-trained, compared (macro-F1), one shipped, documented; real artifacts + manifest +
model card + DECISIONS entry + held-out eval set produced.

**Independent Test**: `MODEL_CARD.md` documents task/dataset(pinned)/3-way comparison/choice/SHA-256;
served artifact hashes match the manifest; comparison reproducible from the notebook.

### Implementation for User Story 3

- [X] T023 [US3] Create `notebooks/01_train_export_modelserver.ipynb` — train 3 candidates (classical / PubMedBERT→ONNX / LLM zero-shot) on a pinned ADE Corpus v2 split, score macro-F1 on the SAME held-out set, record all numbers (D2/FR-012)
- [X] T024 [US3] Export the shipped classifier and the BiomedBERT embedder to `modelserver/models/` (`classifier.*`, `embedder.onnx` 768-dim, `tokenizer.json`; quantize embedder to keep image lean) (D3/D15)
- [X] T025 [P] [US3] Write `modelserver/models/manifest.json` with real SHA-256/version/dim(768)/max_tokens(512) for each artifact (D4)
- [X] T026 [P] [US3] Write `modelserver/models/MODEL_CARD.md` — task, pinned dataset version/hash, 3-way macro-F1 comparison, shipped choice + rationale, per-artifact SHA-256, output shape (FR-011)
- [X] T027 [P] [US3] Add the classifier-selection rationale + comparison numbers to `DECISIONS.md` (Principle IV)
- [X] T028 [P] [US3] Commit the held-out `modelserver/eval/eval_set.jsonl` (text + label; disjoint from training) for the eval gate

**Checkpoint**: Real, defended artifacts shipped; manifest/card/decisions reproducible.

---

## Phase 6: User Story 4 — Refuse compromised/missing models; authenticate callers (Priority: P2)

**Goal**: Startup SHA-256 validation refuses boot on mismatch/absence/partial; liveness vs readiness
separated; every request authenticated; rotation handled.

**Independent Test**: Tamper/remove an artifact → refuses to boot; clean start → `/ready` 200 + versions;
request without/with-bad token → 401/403; `/health` answers without inference.

### Tests for User Story 4

- [X] T029 [P] [US4] Integration test `tests/integration/test_auth_and_health.py` — missing token→401, invalid→403, `/health` no-inference 200, `/ready` 503 before load then 200 with versions
- [X] T030 [P] [US4] Unit test `tests/unit/test_manifest_hashing.py` — SHA-256 compute/compare; refuse-boot on mismatch, on absence, and on partial (only one artifact) (Edge Cases)

### Implementation for User Story 4

- [X] T031 [US4] Implement strict startup artifact validation in `modelserver/startup.py` — compute each file's SHA-256, compare to manifest, raise → refuse boot on mismatch/absence/partial (D4/FR-010/US4)
- [X] T032 [US4] Implement `GET /health` (liveness, no auth, no inference) and `GET /ready` (200 only after artifacts validated, else 503; includes model versions AND rolling per-operation p50/p95 latency + throughput counters) in `modelserver/routes.py` per `contracts/health-info.md`, satisfying the FR-021 "exposed as observable metrics" requirement at the endpoint level (in addition to the `latency_ms` log binding from T008) (D7/D11/FR-017/FR-021)
- [X] T033 [US4] Gate `/classify` and `/embed` behind readiness (`503` until validated) and enforce the `X-Service-Token` dependency on both; confirm credential-rotation behavior (valid replacement accepted, no code change) (FR-015/Edge Cases)

**Checkpoint**: Integrity + auth + health guarantees demonstrable.

---

## Phase 7: User Story 5 — Block merges that regress classifier quality (Priority: P3)

**Goal**: Committed threshold + eval script + CI job fail the build below macro-F1 0.80.

**Independent Test**: Run the eval against the shipped model → passes ≥0.80; a degraded model / raised
bound → CI fails.

### Implementation for User Story 5

- [X] T034 [US5] Create repo-root `eval_thresholds.yaml` with `classifier: {metric: macro_f1, min: 0.80}` (FR-013/SC-003)
- [X] T035 [US5] Implement `modelserver/eval/run_eval.py` — load the shipped classifier (onnxruntime/joblib, no torch/network), score macro-F1 on `eval/eval_set.jsonl`, print it, exit non-zero if below the threshold (D10/FR-014)
- [X] T036 [US5] Update `.github/workflows/ci.yml` — add `"modelserver_token": "ci-test-token"` to the inline Vault secret writer; add a new `eval` job that installs only the `modelserver` uv group and runs `run_eval.py` (D5/D10)
- [X] T037 [P] [US5] Unit test `tests/unit/test_eval_gate.py` — `run_eval.py` passes at/above threshold and exits non-zero below (use a tiny known-scoring fixture)

**Checkpoint**: Eval gate live; regressions blocked in CI.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Caller contract (FR-019), batch/truncation tests, concurrency (FR-018) + no-PII-log (SC-008) verification, SLO benchmark, docs, coverage.

- [X] T038 [P] Implement `app/infra/modelserver_client.py` — async `httpx` client (reuse `app/infra/http.py`), `X-Service-Token` header, `tenacity` timeout + retry (never on 4xx), typed returns, optional ≤128 chunk helper, per `contracts/modelserver-client.md` (FR-019/D13)
- [X] T039 [P] Unit test `tests/unit/test_modelserver_client.py` — token header sent, timeout, retry-NOT-on-4xx, batch chunking (stub transport)
- [X] T040 [P] Unit test `tests/unit/test_truncation.py` and `tests/unit/test_version_stamp.py` — >512 tokens truncates+warns, ≤512 untouched; every result carries the correct per-artifact version
- [X] T041 [P] Integration test `tests/integration/test_batch_limits.py` — >128 items→422, cold-start readiness, over-long truncation path end-to-end
- [X] T042 [P] Implement `modelserver/eval/bench.py` — report classifier/embedder p95 + batch throughput (FR-021/SC-009; not CI-gated, D11)
- [X] T043 [P] Add RUNBOOK/quickstart notes: image-size check (<500 MB), Git LFS guidance for large artifacts, how to rotate `modelserver_token` (D15)
- [X] T044 Verify coverage gates (classifier path ≥95%, overall ≥80%) and run `specs/005-modelserver/quickstart.md` end-to-end on the live stack
- [X] T045 [P] Integration test `tests/integration/test_concurrency.py` — issue many concurrent `/classify` and `/embed` requests and assert per-input correctness + determinism under load (FR-018; closes analysis F2)
- [X] T046 [P] Test `tests/integration/test_no_pii_logs.py` — capture modelserver logs across a representative run and assert request texts, embeddings, and the service token never appear, and that only `/classify`,`/embed`,`/health`,`/ready` are exposed (SC-008/FR-020 + FR-006 surface check; closes analysis F3/F6)

---

## Dependencies & Execution Order

### Phase dependencies
- **Setup (P1)**: no deps — start immediately.
- **Foundational (P2)**: depends on Setup — **blocks all user stories**.
- **User Stories (P3–P7)**: depend on Foundational.
  - US1 (P1) and US2 (P2) are independent (each testable on fixture artifacts).
  - US3 (P2) produces real artifacts; **US5 (P3) depends on US3** (eval needs the shipped model + eval set).
  - US4 (P2) depends only on Foundational (uses fixtures or real artifacts).
- **Polish (P8)**: after the desired stories; T038/T039 (caller client) need US1/US2 contracts stable.

### Story dependency notes
- US5 → requires US3 (shipped classifier + `eval_set.jsonl`).
- US1/US2/US4 → independently testable after Foundational using committed fixtures (T014).

### Parallel opportunities
- Setup: T003/T004/T005 in parallel.
- Foundational: T006–T012 + T014 are mostly independent files ([P]); T013 (`main.py`) depends on them.
- US1 vs US2 vs US4 can proceed in parallel after Foundational (different files).
- US3 doc tasks T025/T026/T027/T028 in parallel after T023/T024.
- Polish: T038–T043 largely parallel.

---

## Parallel Example: Foundational

```bash
# After Setup, launch the independent foundational modules together:
Task: "modelserver/config.py (T006)"
Task: "modelserver/startup.py token load (T007)"
Task: "structlog logging setup (T008)"
Task: "modelserver/manifest.py (T009)"
Task: "modelserver/inference/tokenize.py (T010)"
Task: "modelserver/auth.py (T011)"
Task: "modelserver/schemas.py (T012)"
Task: "fixture artifacts (T014)"
# Then T013 main.py wires them together.
```

---

## Implementation Strategy

### MVP first (US1 only)
1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1 (classify) → **STOP & validate** classify
on fixtures → demo the cheap adverse-event gate.

### Incremental delivery
Foundational → US1 (classify MVP) → US2 (embeddings, unblocks Spec 6) → US3 (real defended model) →
US4 (integrity/auth/health) → US5 (eval gate in CI) → Polish (caller client, benchmark, docs).

### Notes
- Tests-first within each story where practical (constitution testing gates).
- Commit after each task or logical group; Conventional Commits; PRs < 400 lines (split: foundational,
  US1+US2 serving, US3 training/export, US4 integrity, US5 eval+CI, polish).
- Keep torch out of the serving image; gate image size; never log payloads/PII/secrets.
