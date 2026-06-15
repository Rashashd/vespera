# Release-Gate Checklist: Durable ARQ Job Orchestration & Cron Scheduling

**Purpose**: Validate the **quality** of the requirements in `spec.md` (completeness, clarity,
consistency, measurability, coverage) before `/speckit-plan`. These are "unit tests for the spec's
English" — they test whether the requirements are well-written, not whether code works.
**Created**: 2026-06-15
**Feature**: [spec.md](../spec.md)
**Depth**: Full release-gate (all domains) · **Audience**: Reviewer (pre-plan)

## Requirement Completeness

- [ ] CHK001 - Are durable-execution requirements defined for **every** existing background-work call site (ingestion, index build, triage, expedited draft, reviewer redraft, batch consolidation)? [Completeness, Spec §FR-001]
- [ ] CHK002 - Is the set of pipeline **stages composing a cycle** enumerated completely and in order? [Completeness, Spec §FR-014]
- [ ] CHK003 - Are the `watchlist_cycles` record's required fields (status, current stage, timestamps, run links, client/watchlist) fully enumerated? [Completeness, Spec §FR-016, Key Entities]
- [ ] CHK004 - Are the dead-letter record's required fields (job type, target client, input digest, failure reason, attempt count, timestamps) fully enumerated? [Completeness, Spec §FR-009]
- [ ] CHK005 - Are requirements defined for the worker's startup secret-loading and dependency validation (refuse-to-boot conditions)? [Completeness, Spec §FR-022]
- [x] CHK006 - Is the behavior specified when the **broker is unavailable at enqueue time on the web/API side** (not just worker startup)? [Gap] → resolved: Spec §FR-002a
- [x] CHK007 - Are requirements defined for a **cap on concurrent expedited-draft fan-out** per cycle? [Gap] → resolved: Spec §FR-015c
- [x] CHK008 - Is **dead-letter record retention** (how long failures are kept / when purged) specified? [Gap] → resolved: Spec §FR-009a
- [ ] CHK009 - Are the enumerated values for cycle `status` (`in_progress`/`completed`/`failed`) and `current_stage` fully defined? [Completeness, Spec §FR-016]
- [ ] CHK010 - Are requirements defined for **empty-cycle** outcomes (due watchlist yields no new documents) including how completion is still recorded? [Coverage, Spec Edge Cases]

## Requirement Clarity

- [ ] CHK011 - Is the **transient vs. permanent** failure boundary defined precisely enough to classify any failure deterministically (not just by example)? [Ambiguity, Spec §FR-007, §FR-008]
- [x] CHK012 - Is the graceful-shutdown **"bounded grace period"** quantified or given a definite source, rather than left as an unquantified adjective? [Clarity, Spec §FR-012] → resolved: configurable, default = max per-job timeout
- [ ] CHK013 - Is **"inline mode MUST NOT be enabled in production"** backed by a defined, checkable notion of "production configuration"? [Clarity/Measurability, Spec §FR-003, §SC-008]
- [x] CHK014 - Is the budget **period boundary** (e.g., UTC calendar month reset) stated in the spec rather than assumed from prior code? [Clarity, Spec §FR-019b] → resolved: Spec §FR-019b (UTC calendar month)
- [ ] CHK015 - Is **"over its budget cap"** defined unambiguously (the `exceeded`/≥100% state, not `warning`)? [Clarity, Spec §FR-019b]
- [ ] CHK016 - Is the **idempotency "logical work key"** for each job type (run / finding+revision / report / watchlist-cycle) explicitly defined? [Clarity, Spec §FR-005]
- [ ] CHK017 - Is **"operator alerting"** (preserved under `pause`/`critical_only`) defined or traced to an existing mechanism, not left vague? [Clarity, Spec §FR-019b]
- [ ] CHK018 - Is the meaning of **"resume the failed stage"** for a partially-completed stage made unambiguous (what idempotency guarantees on partial progress)? [Clarity, Spec §FR-018b]

## Requirement Consistency

- [ ] CHK019 - Are the job **lifecycle states** (enqueued/started/completed/retried/dead-lettered) used consistently between the observability and dead-letter requirements? [Consistency, Spec §FR-020, §FR-009]
- [ ] CHK020 - Do the fields the dashboard **surfaces** (FR-021) match the fields the dead-letter record **stores** (FR-009)? [Consistency, Spec §FR-021, §FR-009]
- [ ] CHK021 - Is the single-in-flight guard described consistently as **per-(client, watchlist)** everywhere it appears (no lingering "per client" text)? [Consistency, Spec §FR-006, §FR-014a]
- [ ] CHK022 - Is the **HITL-untouched** invariant consistent with the automated-drafting requirements (automation drafts/consolidates but never sends/approves)? [Consistency, Spec §FR-024, §FR-014]
- [ ] CHK023 - Are the eval-gate thresholds stated identically in the Clarifications, FR-025, and SC-011? [Consistency, Spec §FR-025, §SC-011]
- [ ] CHK024 - Is "due-ness advances only on `completed`" consistent across the catch-up, failed-cycle-exclusion, and cycle-state requirements? [Consistency, Spec §FR-015b, §FR-016, §FR-018a]

## Acceptance Criteria Quality (Measurability)

- [ ] CHK025 - Are all eval-gate metrics (`precision`/`recall = 1.0`, `duplicate_rate = 0`, `loss_rate = 0`, `transient_retry_recovery = 1.0`, `inline_vs_durable_parity = 1.0`) objectively measurable as written? [Measurability, Spec §SC-011, §FR-025]
- [ ] CHK026 - Can **"no in-flight job is lost or marked falsely complete"** on shutdown be objectively verified? [Measurability, Spec §SC-005, §FR-012]
- [ ] CHK027 - Is the due-selection golden set defined with enough structure (fixtures of watchlists × cadence × last-cycle × clock → expected set) to be scored? [Measurability, Spec §SC-011]
- [ ] CHK028 - Is **inline-vs-durable parity** defined as a verifiable equality of persisted outcomes for identical inputs? [Measurability, Spec §FR-004, §SC-008]
- [ ] CHK029 - Is the budget-policy success criterion (SC-012) measurable for each policy value **and** for the never-suppress-serious-finding guarantee? [Measurability, Spec §SC-012]

## Scenario Coverage

- [ ] CHK030 - Are **primary** flow requirements complete for an automated end-to-end cycle (due → ingest → index → triage → expedited → consolidate)? [Coverage, Spec §FR-014]
- [ ] CHK031 - Are **exception** flow requirements complete for a stage dead-lettering mid-cycle (mark failed, record, exclude from auto-scheduling)? [Coverage, Spec §FR-018, §FR-018a]
- [ ] CHK032 - Are **recovery** flow requirements complete for operator resume/restart/abandon of a failed cycle? [Coverage, Spec §FR-018b]
- [ ] CHK033 - Are **restart/crash** recovery requirements complete (queued or in-progress job completes after restart, exactly once)? [Coverage, Spec §FR-002, §SC-001]
- [ ] CHK034 - Are requirements defined for the interaction between a **manual trigger and an in-progress automated cycle** for the same watchlist? [Coverage, Spec §FR-006, §FR-019]
- [ ] CHK035 - Are the three budget policies (`continue`/`critical_only`/`pause`) each covered with explicit cycle behavior over budget? [Coverage, Spec §FR-019b]

## Edge Case Coverage

- [ ] CHK036 - Are requirements defined for **extended-downtime catch-up** (overdue by many intervals → exactly one coalesced cycle)? [Edge Case, Spec §FR-015b]
- [ ] CHK037 - Are requirements defined for a **suspended client** (excluded from auto-scheduling; resume on reactivation)? [Edge Case, Spec §FR-013]
- [ ] CHK038 - Are requirements defined for **duplicate/overlapping scheduler ticks** not creating concurrent cycles? [Edge Case, Spec §FR-017, §SC-006]
- [ ] CHK039 - Are requirements defined for a **cadence change mid-cycle** (affects next due time, does not abort in-flight)? [Edge Case, Spec Edge Cases]
- [ ] CHK040 - Are requirements defined for a job that **exceeds the shutdown grace window** (left re-runnable, never marked complete)? [Edge Case, Spec §FR-012]

## Non-Functional Requirements

- [ ] CHK041 - Are **PII/secret exclusion** requirements specified for logs, dead-letter records (incl. the input digest), and audit entries? [Completeness, Spec §FR-011, §FR-020, §SC-009]
- [ ] CHK042 - Are **secure broker transport (TLS) + configurable (non-hardcoded) broker** requirements specified? [Completeness, Spec §FR-023]
- [ ] CHK043 - Are **structured-logging** requirements (bound client/run/finding identifiers) specified for all job lifecycle transitions? [Completeness, Spec §FR-020]
- [ ] CHK044 - Is the Constitution-III safety constraint (never cost-suppress a serious adverse-event report) expressed as a binding requirement, not just narrative? [Completeness, Spec §FR-019b, §SC-012]

## Dependencies & Assumptions

- [ ] CHK045 - Is the dependency on the **prior index-build schema change** (add `watchlist_id`; per-(client,watchlist) constraint; watchlist-scoped doc selection) documented as an explicit, scoped exception with migration impact? [Assumption/Dependency, Spec Assumptions, §FR-014a]
- [ ] CHK046 - Are the reused platform dependencies (audit log, domain-event dispatcher, watermarks, cost/observability tables, admin dashboard, secrets source, broker) enumerated? [Dependency, Spec Assumptions]
- [ ] CHK047 - Is the assumption that **per-source watermarks** make catch-up coalescing correct stated and validated? [Assumption, Spec §FR-015b]
- [ ] CHK048 - Are the **deferred / forward-dependency** items (active budget notification → spec 13; budget-policy UI control → spec 10; sent/delivered statuses; job-management UI) recorded as out-of-scope rather than silently omitted? [Assumption, Spec Out of Scope]

## Ambiguities & Conflicts

- [x] CHK049 - Is the **scheduler topology** (singleton vs. multiple worker replicas running cron) either specified or explicitly deferred to planning with rationale? [Ambiguity/Gap] → resolved: Spec §Deferred to Planning
- [x] CHK050 - Are **worker concurrency limits** (max parallel jobs/cycles, per-stage job timeout) either specified or explicitly deferred to planning? [Gap] → resolved: Spec §Deferred to Planning
- [ ] CHK051 - Is there any residual conflict between "manual triggers remain available" (FR-019) and the failed-cycle "excluded from auto-scheduling" rule (FR-018a) — i.e., is it clear manual still works on a failed cycle? [Conflict-check, Spec §FR-019, §FR-018a]
- [ ] CHK052 - Is the relationship between **expedited-draft independence** (no join) and **cycle `completed`** unambiguous when an expedited draft later fails? [Ambiguity, Spec §FR-015a]

## Notes

- Items marked `[Gap]` / `[Ambiguity]` / `[Conflict-check]` flag where the spec may need a sentence added
  before planning; the rest confirm existing requirements are well-formed. Resolve or consciously accept
  each before `/speckit-plan`.
- CHK006, CHK007, CHK008, CHK012, CHK049, CHK050 are the most likely to need a spec edit or an explicit
  "deferred to plan" note; several (topology, concurrency, timeouts) were already acknowledged as
  plan-level during clarification and can be marked accepted-deferred rather than added to the spec.
