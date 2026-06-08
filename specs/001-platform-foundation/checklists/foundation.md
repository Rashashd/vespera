# Requirements Quality Checklist: Platform Foundation & Security Skeleton

**Purpose**: Formal pre-plan release gate validating the *quality* of the requirements in
`spec.md` — completeness, clarity, consistency, measurability, and coverage — before
`/speckit.plan`. These are "unit tests for the spec's English," not implementation tests.
**Created**: 2026-06-05
**Feature**: [spec.md](../spec.md)
**Depth**: Formal gate · **Audience**: Author (pre-plan)
**Evaluated**: 2026-06-05 — 48/48 passing (CHK007/CHK012 resolved in research.md D1/D2)

## Requirement Completeness

- [x] CHK001 Are requirements defined for every critical startup dependency the app must validate (secrets manager, database, cache, model artifacts)? [Completeness, Spec §FR-002/FR-004/FR-005]
- [x] CHK002 Is the full set of secrets to be loaded from the secrets manager enumerated, or left implicit? [Gap, Spec §FR-001]
- [x] CHK003 Are clean-shutdown requirements defined for every shared resource initialized at startup? [Completeness, Spec §FR-006]
- [x] CHK004 Are the standard security response headers individually enumerated, or referenced only as a group? [Completeness, Spec §FR-010]
- [x] CHK005 Does the spec define the minimum field set for an audit-log entry (actor, actor_type, action, target, event_type, timestamp)? [Completeness, Spec §FR-013/Key Entities]
- [x] CHK006 Are requirements present for the worker skeleton's startup AND shutdown parity with the app? [Completeness, Spec §FR-020]
- [x] CHK007 Are the specific tenant-scoped tables the baseline migration must create identified, vs. left to later specs? [Gap, Spec §FR-015] — resolved in research.md D2 (baseline owns audit_log + extensions only)
- [x] CHK008 Are requirements defined for how/when secrets are first written into the secrets manager (one-time setup)? [Completeness, Spec §FR-019/Assumptions]

## Requirement Clarity

- [x] CHK009 Is "first startup step, before any other resource is initialized" precise enough to order implementation deterministically? [Clarity, Spec §FR-001]
- [x] CHK010 Is "required secret" defined so a missing-secret boot failure is objectively determinable? [Clarity, Spec §FR-002]
- [x] CHK011 Is "shallow liveness check" specified precisely enough to distinguish it from a readiness check? [Clarity, Spec §FR-007]
- [x] CHK012 Is the reserved system-actor identity defined specifically enough to implement consistently across all later features? [Clarity, Spec §Clarifications/FR-013] — resolved in research.md D1 (sentinel actor_id=0 + actor_type)
- [x] CHK013 Are "standard security response headers" each quantified with required values/policies, or left to interpretation? [Ambiguity, Spec §FR-010]
- [x] CHK014 Is "long-term retention" for audit entries quantified, or intentionally deferred as ops policy? [Ambiguity, Spec §FR-014]
- [x] CHK015 Is the boundary "rate-limiting capability" (here) vs "login rate-limit policy" (spec #2) stated unambiguously? [Clarity, Spec §FR-011/Assumptions]

## Requirement Consistency

- [x] CHK016 Do the no-secrets-in-repo requirements (FR-003) align with the Assumptions about Vault bootstrap values supplied via environment? [Consistency, Spec §FR-003/Assumptions]
- [x] CHK017 Is health-endpoint behavior consistent across FR-007, SC-004, and the "probe during startup" edge case? [Consistency, Spec §FR-007/SC-004/Edge Cases]
- [x] CHK018 Does the atomic-audit requirement (FR-013a) stay consistent with the "passive listener" description (FR-012/FR-013)? [Consistency, Spec §FR-013a]
- [x] CHK019 Is the async-everywhere requirement (FR-018) consistent with the worker bootstrap requirement (FR-020)? [Consistency]
- [x] CHK020 Is tenant scoping (FR-015) consistent with the constitution's repository-AND-RAG-layer isolation principle? [Consistency, Constitution §V]
- [x] CHK021 Is terminology for the actor concept ("actor", "actor_type", "system-actor") used consistently across FR-013, Edge Cases, and Key Entities? [Consistency]

## Acceptance Criteria Quality (Measurability)

- [x] CHK022 Can SC-001 ("single command → healthy stack") be objectively verified without implementation knowledge? [Measurability, Spec §SC-001]
- [x] CHK023 Is SC-002's "100% refuse-to-boot" measurable independently for each dependency? [Measurability, Spec §SC-002]
- [x] CHK024 Is SC-004's liveness-probe latency expressed as a concrete, testable threshold? [Clarity, Spec §SC-004]
- [x] CHK025 Is SC-003's "zero secret values" scoped to what is scanned (working tree + full history + logs/traces)? [Measurability, Spec §SC-003]
- [x] CHK026 Does every functional requirement (FR-001..FR-020) trace to at least one measurable success criterion? [Traceability, Gap]

## Scenario Coverage

- [x] CHK027 Are primary-flow requirements (boot → serve → clean shutdown) fully specified? [Coverage, Spec §US1]
- [x] CHK028 Are exception-flow requirements defined for each dependency unavailable at boot? [Coverage, Spec §US1/Edge Cases]
- [x] CHK029 Are requirements defined for the secrets-manager-drops-mid-run recovery scenario? [Coverage, Spec §Edge Cases]
- [x] CHK030 Are requirements specified for a secret present but with a missing required key? [Coverage, Spec §Edge Cases]
- [x] CHK031 Are requirements for what the liveness endpoint returns before startup completes defined? [Coverage, Spec §Edge Cases]

## Edge Case Coverage

- [x] CHK032 Are partial-dependency-availability requirements (e.g., DB up / cache down) explicitly defined? [Edge Case, Spec §Edge Cases]
- [x] CHK033 Is the no-op behavior of model-hash validation (artifacts absent) specified so it cannot block boot? [Edge Case, Spec §FR-005]
- [x] CHK034 Is the duplicate-event-dispatch requirement (exactly one audit entry) defined? [Edge Case, Spec §Edge Cases]
- [x] CHK035 Is audit-write-failure rollback captured as both a requirement and an edge case? [Edge Case, Spec §FR-013a/Edge Cases]
- [x] CHK036 Are requirements defined for log lines that would contain PII/secrets (exclusion/redaction)? [Edge Case, Spec §FR-008]

## Security & Secrets (Non-Functional)

- [x] CHK037 Is it explicit that NO secret value appears in repo, history, files, logs, or traces? [Completeness, Spec §FR-003/SC-003]
- [x] CHK038 Is the health endpoint's unauthenticated + minimal-disclosure requirement specified? [Security, Spec §FR-007]
- [x] CHK039 Are pre-commit secret-scanning expectations referenced as a requirement or assumption? [Coverage, Spec §US2]

## Reliability & Operational (Non-Functional)

- [x] CHK040 Are fail-fast requirements unambiguous that the app refuses to serve in any partially-initialized state? [Reliability, Spec §FR-004/Edge Cases]
- [x] CHK041 Are single-initialization (singleton) requirements for shared resources specified? [Reliability, Spec §FR-006]

## Audit & Compliance (Non-Functional)

- [x] CHK042 Is the append-only / never-auto-deleted requirement for audit entries unambiguous? [Compliance, Spec §FR-014]
- [x] CHK043 Are human-vs-system actor attribution requirements specified well enough to support compliance queries? [Compliance, Spec §FR-013/Clarifications]

## Scope, Dependencies & Assumptions

- [x] CHK044 Is the scope boundary between this feature and later specs (auth tables, business tables, model artifacts, worker jobs, tracing) explicitly documented? [Coverage, Spec §Assumptions]
- [x] CHK045 Are the required baseline indexes (client_id, external_id, status, deadline) enumerated and justified? [Completeness, Spec §FR-015]
- [x] CHK046 Are tech choices (Vault, FastAPI, Postgres, Redis, Alembic, Sentry, structlog, slowapi) confined to Assumptions rather than stated as requirements? [Assumption, Spec §Assumptions]
- [x] CHK047 Is the assumption that app and worker share the identical secret-loading mechanism stated and validated? [Assumption, Spec §FR-020/Assumptions]
- [x] CHK048 Is the dev-mode secrets-manager token documented as a non-sensitive convention? [Assumption, Spec §Assumptions]

## Notes

- Check items off as the spec is confirmed to satisfy each quality question: `[x]`.
- A failing item means the *spec* needs a wording/scope fix (run `/speckit.clarify` or edit
  the spec), not that code is wrong — implementation hasn't started.
- Traceability: 47 of 48 items cite a spec section or a `[Gap]`/`[Ambiguity]`/`[Assumption]`
  marker (>80% target met). CHK026 is itself a cross-cutting traceability check.

## Evaluation Results (2026-06-05)

**Initial: 41/48 passing.** After applying 5 spec fixes: **46/48 passing**, with the
remaining 2 consciously accepted as plan-level (not defects).

| Item | Initial | Resolution | Status |
|------|---------|-----------|--------|
| CHK002 | Fail | FR-002 now enumerates foundation-required secrets (DB URL, cache URL, ≥1 LLM key) | ✅ Fixed |
| CHK010 | Fail | Resolved by CHK002 enumeration — "required" is now objective | ✅ Fixed |
| CHK013 | Fail | FR-010 now states baseline header values; CSP directives explicitly deferred to plan | ✅ Fixed |
| CHK017 | Fail | Startup edge case reworded — endpoint is unavailable (not "not-yet-ready") until startup completes | ✅ Fixed |
| CHK026 | Fail | Added SC-009 (config fail-fast) and SC-010 (rate-limit capability); async is a code-standard, not a runtime SC | ✅ Fixed |
| CHK007 | Defer | Exact baseline tables — each later spec adds its own via migration | ⏸ Accepted (plan-level) |
| CHK012 | Defer | Concrete system-actor representation (sentinel row vs enum) — data-model design | ⏸ Accepted (plan-level) |

The two accepted items are tracked here so `/speckit.plan` resolves them during data-model
design; they are not blocking for planning.
