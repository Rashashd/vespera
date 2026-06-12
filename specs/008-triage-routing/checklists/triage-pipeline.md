# Triage Pipeline Requirements Checklist: Triage & Routing

**Purpose**: Formal release gate — validates requirement quality across all five risk areas (safety bias, data model lifecycle, service integration, eval gate, audit/compliance) before planning. Dual-purpose: author pre-planning self-review and PR reviewer gate.
**Created**: 2026-06-12
**Feature**: [spec.md](../spec.md)
**Depth**: Formal release gate
**Audience**: Author (pre-planning) + PR Reviewer

---

## Triage Pipeline Logic Requirements

- [x] CHK001 — Is the definition of "substantively mentions" a watchlist drug (FR-001) specified with measurable or testable criteria? [Clarity, Spec §FR-001 — deterministic rule: CHEMICAL match in title/summary OR same-sentence DISEASE co-occurrence; impl-notes §8.1]
- [x] CHK002 — Is the three-stage classifier pipeline in FR-002 described with all three stages, their entry conditions, and their exit paths explicitly stated? [Completeness, Spec §FR-002]
- [x] CHK003 — Is the ICH E2E seriousness keyword set referenced explicitly by name/document, or does the spec assume shared knowledge of its contents? [Completeness, Spec §FR-003 — six ICH seriousness criteria now enumerated; keyword list a spec-8 deliverable]
- [x] CHK004 — Is the source-reliability floor rule (regulatory_alert → minimum urgent) consistently stated in FR-003, the Severity Rule entity description, User Story 1 acceptance scenario 6, and the edge cases — with no contradictions between sections? [Consistency, Spec §FR-003, §Key Entities, §User Story 1]
- [x] CHK005 — Is the scope of valence assessment (`positive` vs `irrelevant`) defined with enough specificity that two implementers would converge? [Clarity, Spec §FR-005 — verbatim definitions + boundary question; impl-notes §8.2]
- [x] CHK006 — Are the conditions under which the model verdict is accepted without LLM resolution (confidence ≥ threshold) clearly derivable from FR-002, or only implied? [Clarity, Spec §FR-002]

---

## Safety Bias & Fail-Safe Requirements

- [x] CHK007 — Is the fail-safe escalation when the LLM is unavailable (FR-002, stage 3) stated as a mandatory MUST requirement, not merely described in an edge case note? [Completeness, Spec §FR-002]
- [x] CHK008 — Is the confidence threshold referenced as a committed, versioned value (`triage_confidence_threshold` in `Settings`; CI floors in `eval_thresholds.yaml`), rather than an undefined "low confidence" descriptor? [Clarity, Spec §FR-002, §Assumptions]
- [x] CHK009 — Is the valence-assessment fail-safe (default to `positive` on LLM failure, not `irrelevant`) stated as a MUST requirement in the FRs, or only in the edge cases section? [Completeness, Spec §FR-016]
- [x] CHK010 — Does SC-003 define the measurable direction of safety bias in a way that is objectively verifiable on the golden set (false negatives < false positives, with specific metric comparison)? [Measurability, Spec §SC-003]
- [x] CHK011 — Is the custom-keyword escalation-only constraint (FR-004 — keywords can never downgrade a bucket) stated unambiguously enough to produce a clear, isolated test case? [Clarity, Spec §FR-004]
- [x] CHK012 — Are all four fail-safe paths (classifier unavailable, LLM unavailable for uncertain findings, LLM unavailable for valence, custom keyword narrowing rejected) each covered by at least one explicit FR or documented edge case? [Coverage, Spec §FR-002, §FR-004, §FR-016, §Edge Cases]

---

## Finding Data Model & Lifecycle Requirements

- [x] CHK013 — Resolved by model correction: there is no pre-triage state on the finding. Triage creates the finding already in a terminal status, so no pre-triage status name is needed. [Clarity, Spec §FR-010, §Key Entities]
- [x] CHK014 — Is the ownership boundary between ingestion (spec 4 creates the row) and triage (spec 8 updates it) documented explicitly enough to prevent either spec from claiming ownership? [Completeness, Spec §FR-010, §Assumptions]
- [x] CHK015 — Are all allowed values for the `resolution_path` attribute (model / llm / escalated) enumerated in the Key Entities section with no ambiguity about what triggers each? [Completeness, Spec §Key Entities]
- [x] CHK016 — Are the terminal triage states enumerated explicitly so the idempotency rule in FR-010 is objectively testable? [Clarity, Spec §FR-010 — `pending_expedited`, `pending_batch`, `classified` enumerated; idempotency keyed on `(document_id, drug, reaction)`]
- [x] CHK017 — Are the Finding entity lifecycle state transitions fully consistent between the Key Entities description and the routing FRs (FR-006, FR-007, FR-008) — specifically, does FR-008 state the status assigned to irrelevant findings? [Consistency, Spec §FR-008 now assigns `classified`; Key Entities aligned]
- [x] CHK018 — Is the Alembic migration scope for spec 8 documented in the Assumptions with enough detail to confirm exactly what schema changes are expected? [Completeness, Spec §Assumptions — migration 0007 creates the `findings` table + `custom_severity_keywords` column]

---

## Service Integration & Failure Modes

- [x] CHK019 — Are failure-mode requirements defined independently for each external dependency (classifier, LLM, DB, config read)? [Completeness, Spec §FR-018 + failure matrix in impl-notes §8.3]
- [x] CHK020 — Is there an explicit requirement that modelserver and LLM calls within triage are subject to the project-wide tenacity retry policy (established in prior specs), or is this left as an assumption? [Completeness, Inherited from Engineering Standards]
- [x] CHK021 — Is the operator alert defined with enough specificity (channel, trigger, content) to be implementable? [Clarity, Spec §FR-019 — `triage.operator_alert` ERROR event; client_id/document_id/stage/reason; v1 = structured event, routing is spec 11; impl-notes §8.4]
- [x] CHK022 — Is the per-document automatic trigger mechanism (FR-009) described at a requirements level sufficient to produce a clear integration test between the embedding completion event and the triage invocation? [Clarity, Spec §FR-009]
- [x] CHK023 — Is the dependency on `source_reliability` being set on the document before triage runs (required for the regulatory alert floor) explicitly documented as a prerequisite? [Completeness, Spec §Assumptions]

---

## Eval Gate & Golden Set Requirements

- [x] CHK024 — Is the required composition of the triage golden set (minimum representation of all five buckets, including edge cases for regulatory alert floor and low-confidence LLM resolution) specified? [Completeness, Spec §Assumptions — six mandatory case categories enumerated]
- [x] CHK025 — Are the precision and recall threshold values for the triage CI gate stated in the spec (even as a floor expectation), or fully deferred to `eval_thresholds.yaml` with no guidance? [Clarity, Spec §SC-002, §FR-015 — recall ≥ 0.90, precision ≥ 0.75 committed]
- [x] CHK026 — Is the definition of a CI gate "regression" stated precisely enough to be unambiguous (e.g., either metric below threshold blocks merge, not just the average)? [Clarity, Spec §FR-015]
- [x] CHK027 — Does the golden set requirement explicitly include test cases for the source-reliability floor behavior (YES-classified regulatory alert with weak keyword match → `urgent`)? [Coverage, Spec §Assumptions — case category (2)]
- [x] CHK028 — Is the golden set storage location (`tests/`) and the party responsible for creating it (this spec's deliverables) unambiguous in the Assumptions? [Completeness, Spec §Assumptions]

---

## Audit, Compliance & Client Isolation Requirements

- [x] CHK029 — Does FR-011 enumerate all required audit log fields completely, and is each field's purpose clear enough that a compliance officer could use it for a regulatory submission? [Completeness, Spec §FR-011]
- [x] CHK030 — Is there a requirement that the triage audit record is written atomically with the finding status update — not as a separate, potentially-lost operation? [Completeness, Spec §FR-011]
- [x] CHK031 — Is SC-006 (compliance query returns full triage trail for any finding) stated as an objectively verifiable success criterion with a concrete query scenario? [Measurability, Spec §SC-006]
- [x] CHK032 — Is FR-012 (client isolation) stated with enough specificity to produce a clear, isolated test case that proves one client's custom keywords cannot influence another client's triage result? [Clarity, Spec §FR-012]
- [x] CHK033 — Are the structlog binding requirements for triage (bind `client_id` and `finding_id` on every log line per Engineering Standards) reflected in the spec or explicitly inherited from the constitution? [Completeness, Inherited from Engineering Standards]

---

## Acceptance Criteria Quality

- [x] CHK034 — Is SC-008 (5-minute latency for urgent/emergency findings) measurable end-to-end: are both the start time (ingestion timestamp) and the end point (`pending_expedited` status transition) defined? [Measurability, Spec §SC-008]
- [x] CHK035 — Is SC-001 objectively verifiable? [Clarity, Spec §SC-001 — reframed to "embedded, pre-filter-passing document without a finding", which is concretely queryable]
- [x] CHK036 — Are all five bucket types (irrelevant, positive, minor, urgent, emergency) each represented in at least one acceptance scenario with a Given/When/Then structure? [Coverage, Spec §User Story 1]
- [x] CHK037 — Is the staleness sweep threshold (the "maximum age" referenced in SC-001 and Edge Cases) defined or explicitly deferred to the plan with a rationale? [Clarity, Spec §Assumptions — now an explicit documented deferral]

---

## Scenario & Edge Case Coverage

- [x] CHK038 — Are requirements defined for the multi-drug scenario (one document mentions two watchlist drugs) — specifically how many findings are created and whether each is bucketed fully independently? [Completeness, Spec §Edge Cases]
- [x] CHK039 — Is the concurrent triage scenario (two jobs triaging findings for the same client simultaneously) addressed in requirements — either by a concurrency rule or an explicit note that ARQ job-level deduplication handles it? [Coverage, Spec §FR-010 idempotency]
- [x] CHK040 — Are requirements defined for the NO-classified regulatory alert case — does the spec address that the LLM remains the arbiter and receives source context without forcing a predetermined outcome? [Coverage, Spec §FR-017, §Edge Cases]
- [x] CHK041 — Is the empty custom-keyword scenario (client has no custom_severity_keywords configured) covered — does the spec confirm fallback to ICH defaults is complete and correct? [Coverage, Spec §Assumptions]
- [x] CHK042 — Are requirements defined for what happens to in-flight triage when the ingestion cycle for that client is cancelled or the client is suspended? [Coverage, Spec §Assumptions — deferred to spec 3]

---

## Non-Functional Requirements

- [x] CHK043 — Is document throughput (how many findings can be triaged per unit time) specified or explicitly deferred with a rationale? [Completeness, Spec §Assumptions — explicit documented deferral; SC-008 SLA is the binding constraint]
- [x] CHK044 — Are observability requirements beyond audit logging defined or explicitly deferred? [Completeness, Spec §Assumptions — explicit documented deferral to plan]

---

## Dependencies & Assumptions

- [x] CHK045 — Validated against the codebase: migrations 0001–0006 create NO `findings` table and NO `custom_severity_keywords` column. The earlier "ingestion creates finding rows" assumption was false and has been corrected — triage creates the finding; spec 8 ships migration 0007. [Assumption, Spec §Assumptions — verified, not just asserted]
- [x] CHK046 — Is the dependency on `source_reliability` being populated at ingestion time (spec 4) explicitly cross-referenced, so that if spec 4 changes its reliability tagging the impact on triage is visible? [Completeness, Spec §Assumptions]
- [x] CHK047 — Are the two new LLM prompts (valence classification and low-confidence resolution) listed as first-class deliverables of this spec, with their storage location (`app/prompts/`) and versioning ownership clear? [Completeness, Spec §Assumptions]

---

## Notes

- Check items off as completed: `[x]`
- Items marked `[Gap]` indicate requirements that appear to be missing from the spec and should be addressed before or during planning.
- Items marked `[Clarity]` indicate requirements present in the spec but potentially ambiguous — resolve before implementation begins.
- Items marked `[Consistency]` should be verified by cross-reading the referenced spec sections together.
- Mandatory gating items (Safety Bias, Eval Gate, Audit/Compliance categories) should be resolved before proceeding to `/speckit-plan`.
