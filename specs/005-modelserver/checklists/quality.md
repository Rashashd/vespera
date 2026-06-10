# Requirements Quality Checklist: Modelserver — Adverse-Event Classifier & Medical Embedder

**Purpose**: Validate that the modelserver requirements are complete, clear, consistent, and measurable before planning ("unit tests for the spec").
**Created**: 2026-06-09
**Verified**: 2026-06-10 (re-confirmed against final spec.md + research.md D1–D16)
**Feature**: [spec.md](../spec.md)
**Depth**: Standard · **Audience**: Reviewer (pre-`/speckit-plan`) · **Focus**: inference/data contract + non-functional integrity (performance, security, artifact/eval correctness)

## Requirement Completeness

- [x] CHK001 - Are requirements defined for BOTH served capabilities (classification AND embedding) with no implied third capability left unspecified? [Completeness, Spec §FR-001/FR-002]
- [x] CHK002 - Is the full request/response shape for classification documented (raw confidence, decision, default cutoff, model-version id)? [Completeness, Spec §FR-001/FR-005b]
- [x] CHK003 - Is the full request/response shape for embedding documented (768-dim vector, model-version id)? [Completeness, Spec §FR-002/FR-005b]
- [x] CHK004 - Are startup-integrity requirements specified for every served artifact (hash present, validated, refusal on mismatch/absence)? [Completeness, Spec §FR-010, §US4]
- [x] CHK005 - Are model-card content requirements enumerated (task, pinned dataset, comparison metric, shipped choice, rationale, SHA-256)? [Completeness, Spec §FR-011]
- [x] CHK006 - Are health/readiness requirements distinguished from liveness (started vs ready-to-serve)? [Completeness, Spec §FR-017]
- [x] CHK007 - Are observability requirements specified for both operational logs and latency/throughput metrics? [Completeness, Spec §FR-020/FR-021]
- [x] CHK008 - Is the secrets/credential acquisition path at startup specified rather than assumed? [Completeness, Spec §FR-016]
- [x] CHK009 - Are requirements present for what is explicitly OUT of scope (no parsing/severity/drafting/LLM)? [Completeness, Spec §FR-006]

## Requirement Clarity

- [x] CHK010 - Is the classifier confidence range explicitly bounded ([0,1]) and the default decision cutoff (0.5) stated numerically? [Clarity, Spec §FR-001]
- [x] CHK011 - Is the embedding dimension stated as an exact constant (768) rather than "a documented dimension"? [Clarity, Spec §FR-002]
- [x] CHK012 - Is the maximum batch size stated as an exact number (128) with defined over-limit behavior? [Clarity, Spec §FR-003/FR-005]
- [x] CHK013 - Are the latency targets expressed as a measurable percentile and split per operation (classifier p95 <50ms, embedder p95 <150ms)? [Clarity, Spec §FR-021]
- [x] CHK014 - Is "lean container" quantified (target ~500 MB) rather than left subjective? [Clarity, Spec §FR-009]
- [x] CHK015 - Is "model-version identifier" defined concretely (artifact SHA-256 and/or version tag) so callers know what to persist? [Clarity, Spec §FR-005b]
- [x] CHK016 - Is "deterministic inference" defined precisely (identical input → identical decision/confidence/vector)? [Clarity, Spec §FR-004]
- [x] CHK017 - Is the boundary between "over-large request" (reject) and "over-long single text" (truncate) unambiguously distinguished? [Clarity, Spec §FR-005/FR-005a]

## Requirement Consistency

- [x] CHK018 - Do the no-torch/ONNX-only and ~500 MB requirements stay consistent with the per-operation latency targets (i.e., targets are achievable on the mandated runtime)? [Consistency, Spec §FR-008/FR-009/FR-021]
- [x] CHK019 - Is the batch cap of 128 consistent everywhere it appears (FR-003, FR-005, Clarifications)? [Consistency, Spec §FR-003/FR-005]
- [x] CHK020 - Are the Success Criteria (SC-001..SC-009) each traceable to at least one functional requirement without contradiction? [Consistency, Spec §SC / §FR]
- [x] CHK021 - Is the "modelserver returns YES/NO but caller owns the cutoff" rule consistent between FR-001 and the Classification-result entity and US1? [Consistency, Spec §FR-001, §Key Entities, §US1]
- [x] CHK022 - Does the GPU/torch "future improvement" note stay consistent with the binding no-torch requirement (clearly marked out-of-scope, amendment-gated)? [Consistency, Spec §FR-008, §Assumptions]

## Acceptance Criteria Quality (Measurability)

- [x] CHK023 - Can the classifier quality gate be objectively measured (macro-F1 ≥ 0.80 on a named held-out set)? [Measurability, Spec §FR-013/SC-003]
- [x] CHK024 - Are the performance SLOs stated so they can be objectively verified from emitted metrics? [Measurability, Spec §FR-021/SC-009]
- [x] CHK025 - Is the integrity behavior measurable as a binary outcome (refuses to boot 100% on altered/absent artifact)? [Measurability, Spec §SC-005]
- [x] CHK026 - Is the auth requirement measurable (100% of credential-less requests rejected)? [Measurability, Spec §SC-006]
- [x] CHK027 - Is the redaction/no-leak requirement stated as a verifiable outcome (no PII/secret in logs during a representative run)? [Measurability, Spec §SC-008]
- [x] CHK028 - Does each User Story include an Independent Test that is objectively checkable? [Measurability, Spec §US1–US5]

## Scenario Coverage

- [x] CHK029 - Are requirements defined for the primary flow (valid single/batch inference returning ordered results)? [Coverage, Spec §FR-003, §US1/US2]
- [x] CHK030 - Are exception-flow requirements defined (empty/malformed input, over-large request, missing/invalid credential)? [Coverage, Spec §FR-005/FR-015]
- [x] CHK031 - Are recovery/startup-failure requirements defined (refuse boot on hash mismatch or partial artifacts)? [Coverage, Spec §FR-010, §Edge Cases]
- [x] CHK032 - Are concurrency requirements defined (correctness + determinism under simultaneous load)? [Coverage, Spec §FR-018, §Edge Cases]
- [x] CHK033 - Is the model-upgrade scenario covered (new artifact version → callers can detect/refresh stale results)? [Coverage, Spec §FR-005b]

## Edge Case Coverage

- [x] CHK034 - Is cold-start behavior specified (requests must not serve before models loaded; readiness distinct)? [Edge Case, Spec §Edge Cases/FR-017]
- [x] CHK035 - Is over-long single-text behavior specified (truncate-to-max with a logged warning, not crash/drop)? [Edge Case, Spec §FR-005a]
- [x] CHK036 - Is out-of-domain / unsupported-language input behavior specified (returns YES/NO, never errors on valid text)? [Edge Case, Spec §Edge Cases]
- [x] CHK037 - Is credential rotation/expiry behavior specified (rejected when expired, accepted on valid replacement, no code change)? [Edge Case, Spec §Edge Cases]
- [x] CHK038 - Is the empty-batch case specified (returns empty result without error)? [Edge Case, Spec §US2]

## Non-Functional Requirements

- [x] CHK039 - Are security requirements complete for the service boundary (service-credential auth, secrets from store, no secrets on disk/in image)? [Non-Functional/Security, Spec §FR-015/FR-016]
- [x] CHK040 - Are reliability/availability expectations addressed or explicitly excluded (no uptime SLO is stated — is that intentional)? [Non-Functional/Gap, Spec §FR-017–FR-019]
  > **Resolved — research D14**: No formal uptime SLO is an intentional capstone scope decision. The service is stateless and restartable; resilience is delegated to callers via timeout + bounded retry (FR-019/D13). Documented in research.md D14.
- [x] CHK041 - Are resilient-call expectations on the caller side specified (timeout + bounded retry, no retry on 4xx)? [Non-Functional, Spec §FR-019]

## Dependencies & Assumptions

- [x] CHK042 - Is the dependency on a pinned labeled dataset (version/hash) documented so eval numbers are reproducible? [Assumption, Spec §Assumptions/FR-011]
- [x] CHK043 - Is the downstream contract with Spec 6 (callers send model-sized chunks; store model-version with vectors; 768-dim storage) documented? [Dependency, Spec §FR-002/FR-005a/FR-005b]
- [x] CHK044 - Is the separate-container justification (no-torch constraint) recorded and consistent with the constitution? [Assumption, Spec §Assumptions]
- [x] CHK045 - Is the assumption that exactly one classifier ships (others compared only) stated unambiguously? [Assumption, Spec §FR-012/§Assumptions]

## Ambiguities & Conflicts

- [x] CHK046 - Is the model's maximum input length left undefined an acceptable deferral, or does it need a stated bound for testing truncation? [Ambiguity, Spec §FR-005a]
  > **Resolved — research D12**: Max input fixed at **512 tokens** (BERT-family standard), recorded in `manifest.json` (`max_tokens`) and used as the truncation boundary in D8. Truncation tests assert at this exact boundary.
- [x] CHK047 - Is the transport/protocol intentionally deferred to planning without creating contract ambiguity for callers? [Ambiguity/Gap, Spec §FR-019]
  > **Resolved — research D7**: HTTP/JSON REST (FastAPI), matching the rest of the platform. Endpoints: `POST /classify`, `POST /embed`, `GET /health` (liveness), `GET /ready` (readiness with versions). No ambiguity for callers.
- [x] CHK048 - Is it unambiguous whether the model-version identifier is per-result or per-response (and whether classifier and embedder versions are reported separately)? [Ambiguity, Spec §FR-005b]
  > **Resolved — research D9**: Per-result version stamp on every response item. Classifier and embedder artifact versions are **reported separately** (distinct `sha256` + human `version` tag). Top-level response echoes the relevant version once for convenience.
- [x] CHK049 - Is a requirement & acceptance-criteria ID scheme established and used consistently (FR-/SC-/US-)? [Traceability]

## Notes

- All 49 items verified against `spec.md` (final, post-clarify×2) and `research.md` (D1–D16) on 2026-06-10.
- Four items that were flagged as intentional deferrals at checklist creation (CHK040, CHK046, CHK047, CHK048) are each resolved by an explicit research decision — annotated inline above with the decision ID.
- Items marked incomplete require spec updates before `/speckit-clarify` or `/speckit-plan`.
- **Intentional constraint references**: The spec names a few hard architectural constraints
  (no-torch / ONNX-only serving, ~500 MB image, SHA-256 startup validation, service-credential
  auth, secrets from the platform store). These are non-negotiable platform constraints fixed by
  the project constitution (Principle VI and the Security & Secrets section), not free
  implementation choices, so they are stated as requirements rather than deferred to planning.
- **Open value for clarify**: the committed macro-F1 threshold is recorded as an assumption
  with a reasonable default (≥ 0.80); the exact figure is best confirmed via `/speckit-clarify`
  or finalized in planning once the shipped model's number is known.
