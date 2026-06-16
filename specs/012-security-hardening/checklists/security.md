# Security & Compliance Requirements Checklist: Security Hardening

**Purpose**: Validate that the spec's security requirements are complete, clear, testable, and consistent with the constitution before planning. Unit tests for the *requirements*, not the implementation.
**Created**: 2026-06-15
**Feature**: [spec.md](../spec.md)
**Depth**: Release-gate · **Audience**: Reviewer / security

## Guardrails layer — completeness & coverage

- [ ] CHK001 - Are ALL external/LLM-facing call paths enumerated as guarded, with none left implicit? [Coverage, Spec §FR-002]
- [ ] CHK002 - Is the boundary between "guarded path" and "not guarded" explicitly justified for each excluded path (e.g. search)? [Clarity, Spec §FR-002]
- [ ] CHK003 - Are requirements defined for BOTH input-side and output-side rail checks, with the output cases named? [Completeness, Spec §FR-002a]
- [ ] CHK004 - Is the platform-rail set (injection/jailbreak/topic-scope/cross-client) stated as exhaustive, and is PII's exclusion from the rail set unambiguous? [Clarity, Spec §FR-001]
- [ ] CHK005 - Are the rail-implementation constraints (local/heuristic, no per-call external LLM, torch-free) stated as testable requirements rather than aspirations? [Measurability, Spec §FR-001a]
- [ ] CHK006 - Is "tenant-invariant" defined precisely enough that a config that weakens a platform rail can be objectively identified and rejected? [Clarity, Spec §FR-003]
- [ ] CHK007 - Are the guardrails service auth + reachability requirements (service credential, interface) specified consistently with how other internal services authenticate? [Consistency, Spec §FR-007]

## Guardrails layer — failure modes & edge cases

- [ ] CHK008 - Are fail-safe behaviors defined for EACH guarded path separately (triage escalate, agent tool error→escalate, intake quarantine)? [Coverage, Spec §FR-006/FR-006a]
- [ ] CHK009 - Is the document-intake quarantine behavior specified completely (held out of indexing AND triage, audited, cycle continues for others, no re-scan obligation)? [Completeness, Spec §FR-006a]
- [ ] CHK010 - Is the requirement that a guardrails outage MUST NOT proceed unguarded stated for output-side checks too, not just input? [Gap, Spec §FR-002a/FR-006]
- [ ] CHK011 - Are requirements defined for what is recorded on a rail refusal (rail type + target context, no PII) so the audit entry is testable? [Measurability, Spec §FR-005]
- [ ] CHK012 - Is the slow (not just unreachable) guardrails case addressed, or is only the unreachable/error case specified? [Edge Case, Spec §Edge Cases]

## Redaction layer — completeness & boundary

- [ ] CHK013 - Is the egress-only redaction boundary unambiguous about what is NOT redacted (persisted report body, findings, chunks) vs what is? [Clarity, Spec §FR-009]
- [ ] CHK014 - Is "stored summary" defined precisely enough to distinguish a redacted operational summary from the un-redacted authored report? [Ambiguity, Spec §FR-009]
- [ ] CHK015 - Are ALL egress points enumerated (external LLM call, log, trace, derived summary) and is the uniform "all sources" rule (incl. config text) consistent across them? [Consistency, Spec §FR-009/FR-009a]
- [ ] CHK016 - Are the PII categories to redact enumerated concretely enough to build a golden set (names, initials, DOB, case/record numbers, addresses, contacts)? [Completeness, Spec §FR-009]
- [ ] CHK017 - Is the secret-pattern scope for redaction specified, or left undefined ("API-key/token patterns")? [Gap, Spec §FR-010]
- [ ] CHK018 - Is the ordering requirement (redact BEFORE guardrails and BEFORE the external LLM call) stated unambiguously for both triage and drafting paths? [Clarity, Spec §FR-012]
- [ ] CHK019 - Is the requirement that raw pre-redaction text is never logged stated as an absolute, testable invariant? [Measurability, Spec §FR-014]

## Redaction layer — signal preservation & gate

- [ ] CHK020 - Is "preserve the clinical signal" defined with a measurable criterion (no regression in triage recall / report grounding) rather than a vague adjective? [Measurability, Spec §FR-011/SC-004]
- [ ] CHK021 - Does the redaction CI-gate requirement specify both the leak condition (zero planted tokens survive at ANY egress point) AND the over-redaction guard (legitimate-content cases)? [Completeness, Spec §FR-013/§Edge Cases]
- [ ] CHK022 - Is it specified whether redaction applies to the retrieved RAG context passed to the drafting LLM, and how that reconciles with grounding/citation integrity? [Gap, Spec §FR-009/§Constitution II]

## Tenant isolation (RLS) — completeness & roles

- [ ] CHK023 - Is "all tables carrying client_id" resolvable to a concrete, enumerable table set (incl. join-only tables) so coverage is verifiable? [Measurability, Spec §FR-015]
- [ ] CHK024 - Is the users/auth-table exemption documented with its rationale and the compensating control (app-layer role guards)? [Traceability, Spec §FR-015]
- [ ] CHK025 - Are the role-aware policy requirements (client-user own-client; staff cross-client) consistent with the constitution's internal-operator exception and its four compensating controls? [Consistency, Spec §FR-016/§Constitution V]
- [ ] CHK026 - Is the default-deny requirement (no context ⇒ zero rows, never fail-open) stated unambiguously and separately from the populated-context behavior? [Clarity, Spec §FR-018]
- [ ] CHK027 - Are the two DB roles (least-privilege app role with FORCE RLS vs privileged BYPASSRLS migration/seed role) specified with which operations use which? [Completeness, Spec §FR-019/FR-019a]
- [ ] CHK028 - Is the per-transaction session-context requirement specified to NOT leak across pooled connections, with the pooling/statement-cache constraint stated testably? [Clarity, Spec §FR-017/FR-021]
- [ ] CHK029 - Is staff cross-client access under RLS required to preserve target-client audit attribution (compensating control (a))? [Coverage, Spec §FR-020/§Constitution V]

## Tenant isolation (RLS) — verification & edge cases

- [ ] CHK030 - Does the spec require an automated test of an intentionally-unfiltered query under both a client-user and a staff context? [Measurability, Spec §FR-022]
- [ ] CHK031 - Are write-path (INSERT/UPDATE into another client's scope) rejection requirements specified, not just read isolation? [Coverage, Spec §US3 scenario 1]
- [ ] CHK032 - Are requirements defined for migration/seed success under RLS (stack boots + migrates cleanly), and that the bypass is unreachable from request sessions? [Edge Case, Spec §FR-019/SC-009]

## Secrets, config & CI gating

- [ ] CHK033 - Is the new app-role credential explicitly required to be added to the required-secrets set AND the CI inline secret writer AND local tooling, consistent with the Vault-only-secrets principle? [Consistency, Spec §FR-019a/FR-027/§Constitution Security]
- [ ] CHK034 - Is the rule that runtime config lives in central settings (not CI-only threshold files) stated for the new guardrails URL / redaction toggles? [Clarity, Spec §FR-026]
- [ ] CHK035 - Are the new CI gates (redaction; guardrails red-team) required to declare thresholds in eval-thresholds config and run in the existing eval job, honoring checkout/service-host conventions? [Completeness, Spec §FR-028]
- [ ] CHK036 - Is startup-validation behavior specified if a newly-required secret (app-role) is missing — refuse to boot, consistent with the constitution's startup-validation rule? [Gap, Spec §FR-027/§Constitution Security]

## Observability & deviation closure

- [ ] CHK037 - Is the tracing re-enable requirement gated explicitly on redaction being in place, with the drafting-agent-trace no-PII condition stated as verifiable? [Clarity, Spec §FR-023/SC-007]
- [ ] CHK038 - Are both spec-8 deviations (LLM-before-redaction; guardrails-absent-from-triage) named individually with the specific replacing control for each? [Traceability, Spec §FR-025/SC-008]
- [ ] CHK039 - Is it specified that closing the deviations updates the constitution Complexity Tracking record, not just the spec? [Gap, Spec §SC-008]

## Threat model, acceptance criteria & cross-cutting

- [ ] CHK040 - Are the success criteria (SC-001..SC-009) each traceable to one or more FRs, with no SC lacking a backing requirement? [Traceability, Spec §Success Criteria]
- [ ] CHK041 - Is each P1 user story's "Independent Test" actually independent (no hidden dependency on another layer) as claimed? [Consistency, Spec §US1–US3]
- [ ] CHK042 - Is the threat model implicit-vs-explicit: are the assumed threats (poisoned documents, forgotten filter, pasted secrets, manipulated output) all mapped to a requirement? [Coverage, Gap]
- [ ] CHK043 - Are latency/performance expectations for the added redaction + guardrails hops stated or explicitly deferred, so the omission is intentional? [Non-Functional, Gap]
- [ ] CHK044 - Are terms used consistently across sections (e.g. "guarded call site" vs "guarded path"; "platform rail" vs "rail"; "session security context" vs "session context")? [Consistency]
- [ ] CHK045 - Is the out-of-scope boundary (tenant rails, Casbin, SSO/MFA, PgBouncer standup, right-to-erasure) free of conflict with any in-scope FR? [Conflict, Spec §Out of Scope]

## Notes

- Check items off as completed: `[x]`. Each item tests whether the requirement is *written well*, not whether code works.
- Known intentional gaps to confirm during `/speckit-plan` (not spec defects): CHK017 (secret-pattern set), CHK022 (RAG-context redaction vs grounding), CHK043 (latency budget) — all flagged plan-level in the clarify passes.
- ≥80% of items carry a traceability reference (Spec §, or [Gap]/[Ambiguity]/[Conflict]/[Assumption] marker).
