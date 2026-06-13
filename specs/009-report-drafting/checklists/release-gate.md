# Release-Gate Requirements Quality Checklist: Report Drafting (Bounded Agent + HITL)

**Purpose**: Pre-implementation release gate. Validates that the *requirements themselves* (spec.md) are complete, clear, consistent, and measurable across the feature's highest-risk areas: compliance/safety, bounded-agent behavior, multi-tenant isolation, and the batch/HITL workflow. These are "unit tests for the English" — they test the spec, not the eventual code.
**Created**: 2026-06-13
**Feature**: [spec.md](../spec.md)
**Depth**: Release gate (thorough) · **Audience**: Reviewer / release approver

## Requirement Completeness

- [ ] CHK001 Is each structured report field defined (what "Causality", "Source reliability", "Study type", "Population", "Dose" must contain), not just named? [Completeness, Spec §FR-003]
- [ ] CHK002 Is the corroboration-count rule fully specified (counts *distinct source documents* vs distinct sources vs passages, and how duplicates are collapsed)? [Completeness, Spec §FR-007]
- [ ] CHK003 Are the emergency follow-up artifact's contents specified to the extent built here (template fields present, required cover-message elements)? [Completeness, Spec §FR-006]
- [ ] CHK004 Are the finding reporting-lifecycle states fully enumerated *with allowed transitions* (pending-batch → processing → reported/done; → discarded)? [Completeness, Spec §Key Entities, §FR-010]
- [ ] CHK005 Does the spec define *how* the SLA-deadline value is determined (window source / setting), not only that one "is set"? [Completeness, Spec §FR-005, §SC-007]
- [ ] CHK006 Are all report status values enumerated and each given a definition (drafted, under review, approved, rejected, discarded, ready-to-send, needs_manual_revision)? [Completeness, Spec §Key Entities]

## Requirement Clarity & Measurability

- [ ] CHK007 Is "within the cycle's drafting window (minutes, not hours)" quantified with a concrete threshold, or explicitly delegated to a named setting? [Clarity, Spec §SC-007]
- [x] CHK008 Is "usable evidence" / "cannot ground a claim" defined with an objective criterion a test can apply, rather than left to judgment? [Ambiguity, Spec §FR-004, §FR-025] — RESOLVED: FR-004 now defines grounded = ≥1 retrieved passage clearing the relevance threshold and supporting the fact.
- [ ] CHK009 Are the agent loop "iteration" and "token" caps given concrete values or explicitly located in settings (so they are testable)? [Clarity, Spec §FR-022, §Assumptions]
- [x] CHK010 Is the agent-tool-selection accuracy threshold a committed number (not "the committed threshold") and tied to a defined golden set size? [Measurability, Spec §SC-004] — RESOLVED: SC-004 now commits ≥0.85 (conservative starting bar) on a ≥15-example set (authoritative in eval_thresholds.yaml).
- [ ] CHK011 Is the claim-provenance granularity defined (per claim / per sentence / per field) so `drafted-grounded` vs `reviewer-attested` is objectively assignable? [Clarity, Spec §FR-017, §Clarifications]
- [ ] CHK012 Is the corroboration-accuracy metric (≥0.75) defined with its measurement method and reference set? [Measurability, Spec §SC-003]

## Requirement Consistency

- [ ] CHK013 Do report status values match across Key Entities, FR-014–019, FR-016, and the edge cases (no stray/undeclared states)? [Consistency, Spec §Key Entities, §FR-016]
- [ ] CHK014 Is "cycle" used consistently as *per-watchlist* (never per-client) everywhere after the batch-grain clarification? [Consistency, Spec §FR-011, §SC-008]
- [ ] CHK015 Is per-finding removal consistently disambiguated as drop-from-report vs discard-permanently (no bare "discard" that could mean either)? [Consistency, Spec §FR-018, §Edge Cases]
- [ ] CHK016 Do the escalation-routing statements agree across FR-025, FR-026, US4, and edge cases (operator-alert for agent-side failures vs `needs_manual_revision` for 4th rejection)? [Consistency, Spec §FR-026]
- [ ] CHK017 Is severity terminology consistent with the spec-8 buckets it consumes (urgent/emergency → expedited; minor/positive → batch; emergency = life-threatening)? [Consistency, Spec §FR-001, §FR-006]

## Acceptance Criteria & Success Metrics Quality

- [ ] CHK018 Are all success criteria (SC-001…SC-011) objectively measurable without implementation knowledge? [Measurability, Spec §Success Criteria]
- [ ] CHK019 Is each functional requirement traceable to at least one success criterion or acceptance scenario? [Traceability, Spec §FR / §SC]
- [x] CHK020 Does SC-001 correctly scope the grounding guarantee to *machine-drafted* claims after the reviewer-edit clarification (no contradiction with FR-017)? [Consistency, Spec §SC-001, §FR-017] — RESOLVED: SC-001 scopes to machine-drafted claims; FR-017 marks edits reviewer-attested. Consistent.
- [ ] CHK021 Are acceptance scenarios present for the drop-from-report (returns next cycle) vs discard-permanently (terminal) distinction? [Coverage, Spec §US3, §Clarifications]

## Scenario Coverage

- [ ] CHK022 Are requirements defined for the full primary expedited path (finding created → grounded draft → queued with SLA)? [Coverage, Spec §US1]
- [ ] CHK023 Are exception-flow requirements defined for each tool failure *and* LLM failure during drafting, with the resulting routing? [Coverage, Spec §FR-024, §Edge Cases]
- [ ] CHK024 Are recovery/escalation requirements stated distinctly for loop/token-cap exhaustion vs 4th-rejection (different destinations)? [Coverage, Spec §FR-016, §FR-025]
- [ ] CHK025 Are requirements defined for concurrent/duplicate reviewer actions on the same report (first-decision-wins)? [Coverage, Spec §Edge Cases]

## Edge Case Coverage

- [x] CHK026 Is idempotency specified for re-triggered drafting, *including* whether a finding whose report was discarded/rejected may be re-drafted (resurrect vs new)? [Edge Case, Spec §FR-030] — RESOLVED: FR-030 now states terminal (discarded/rejected) findings are not auto-resurrected; re-drafting is an explicit manual action.
- [ ] CHK027 Is the emptied-batch-during-review outcome specified (auto-discard, not approvable)? [Edge Case, Spec §FR-013a]
- [ ] CHK028 Is behavior defined when retrieval supports some candidate claims but not others (partial grounding)? [Edge Case, Spec §US1 scenario 2]
- [ ] CHK029 Is the single-source finding case specified (corroboration count = 1, still drafts)? [Edge Case, Spec §Edge Cases]

## Compliance & Safety Requirements

- [ ] CHK030 Is "no report finalized/eligible-to-send without a logged reviewer approval" stated unambiguously and bound to a specific audit event? [Completeness, Spec §FR-014, §FR-021, §SC-002]
- [ ] CHK031 Are audit-event requirements defined for *every* reviewer action, including per-finding drop and discard within a batch? [Coverage, Spec §FR-021, §SC-009]
- [ ] CHK032 Are PII/secret redaction requirements specified for logs, traces, and stored report metadata produced by this feature? [Completeness, Spec §FR-031]
- [ ] CHK033 Is the prompt-injection / untrusted-data requirement defined with a measurable guard (CI red-team golden-set case)? [Measurability, Spec §FR-027, §SC-010]
- [ ] CHK034 Is approval authority unambiguously limited to the `reviewer` role and documented as a deliberate separation-of-duties choice? [Clarity, Spec §FR-019, §Clarifications]

## Bounded Agent & Tool Requirements

- [ ] CHK035 Is the tool-error contract (returns structured error + retryability, never raises) specified as applying to all tools in the fixed set? [Completeness, Spec §FR-024]
- [ ] CHK036 Is the `score_severity` read/confirm-only constraint specified (no re-bucketing/override), preserving the single source of truth? [Consistency, Spec §FR-023, §Clarifications]
- [ ] CHK037 Are the fail-toward-human guarantees enumerated for *every* failure mode (no silent auto-approval, auto-send, or auto-discard)? [Coverage, Spec §FR-026, §SC-011]

## Multi-Tenant Isolation & Data Integrity

- [ ] CHK038 Are client-scoping requirements stated at *both* the retrieval and the persistence/reporting layers? [Completeness, Spec §FR-028]
- [x] CHK039 Is the corroboration/evidence scope defined (client-wide across watchlists vs originating-watchlist-only) so isolation and counts are unambiguous? [Ambiguity, Spec §FR-007, §FR-028] — RESOLVED: FR-002 now specifies client-wide retrieval scope (cross-watchlist within the client allowed; isolation at client boundary).
- [ ] CHK040 Are deferred boundaries and new dependencies documented as validated assumptions (delivery/frontend/scheduling/guardrails deferrals; biweekly cadence + watchlist-of-origin migration; spec-7 retrieval & spec-8 findings reuse)? [Assumption/Dependency, Spec §Assumptions, §FR-011b]

## Notes

- These items validate **requirement quality**, not implementation. An item "passes" when the spec answers it clearly, completely, and measurably — not when code does something.
- Check items off as resolved: `[x]`. For any item that fails, fix the spec (or record an explicit, justified deferral) before `/speckit-plan`.
- High-priority gates before implementation: CHK008, CHK010, CHK020, CHK026, CHK039 (each is an ambiguity/consistency item that would otherwise propagate into plan and tests).
