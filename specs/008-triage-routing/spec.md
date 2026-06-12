# Feature Specification: Triage & Routing

**Feature Branch**: `008-triage-routing`

**Created**: 2026-06-12

**Status**: Draft

**Input**: User description: "spec 8"

## Clarifications

### Session 2026-06-12

- Q: When does triage fire relative to document embedding? → A: Per-document, automatically when each document completes embedding; no manual trigger; urgent/emergency findings route to the expedited queue without waiting for cycle end.
- Q: When is a finding row created — by ingestion or by triage? → A: Triage creates the finding row (no `findings` table exists yet; spec 4 created only `documents`/`document_sources`). Spec 8 owns a new migration creating `findings`. Uniqueness key is `(document_id, drug, reaction)` — each drug-reaction pair is one finding. Idempotency is enforced by that key, not by a pre-triage status guard. (Supersedes an earlier draft that assumed ingestion creates pre-triage finding rows.)
- Q: How is "uncertain" classifier confidence operationalized? → A: A fixed `triage_confidence_threshold` committed in application config (`Settings`); findings below threshold are forwarded to the LLM for YES/NO resolution before bucketing; LLM unavailability falls back to escalation. (The CI-gate precision/recall floors live in `eval_thresholds.yaml`; the runtime threshold does not, since nothing loads that file at runtime.)
- Q: When is `corroboration_sources` populated on a finding? → A: By the report drafting step (spec 9), not by triage; triage leaves it null.
- Q: Is there an explicit latency target for urgent/emergency findings reaching the expedited queue? → A: Yes — urgent/emergency findings must be in `pending_expedited` within 5 minutes of document ingestion.
- Q: Should `source_reliability: regulatory_alert` documents receive special treatment at severity bucketing? → A: Source-reliability floor — YES-classified regulatory alert findings are bucketed at minimum `urgent`; keyword rule may still escalate to `emergency` but MUST NOT result in `minor` regardless of keyword match strength.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Document Triaged and Routed to Correct Queue (Priority: P1)

A reviewer opens the approval queue and sees that each finding has already been assigned a severity bucket and is waiting in the right place — urgent and emergency findings are in the expedited queue ready for immediate drafting, while minor and positive findings are accumulating in the batch queue. Triage fires automatically for each document the moment it finishes embedding; no human action is required to start it, and urgent signals are available to the reviewer within minutes of ingestion.

**Why this priority**: Triage and routing is the decision gate that determines which findings generate immediate action versus batch consolidation. Without it, no downstream report drafting can proceed correctly.

**Independent Test**: Can be fully tested by ingesting a set of pre-classified test documents (covering all five buckets) and verifying that each finding ends up in the correct queue state with the correct bucket label, and that urgent/emergency findings reach `pending_expedited` within the defined time window.

**Acceptance Scenarios**:

1. **Given** a document that mentions a watchlist drug and describes a life-threatening adverse reaction, **When** triage runs automatically after embedding completes, **Then** the finding is assigned bucket `emergency`, status is set to `pending_expedited` within 5 minutes of ingestion, and the audit log records the decision with finding ID, client ID, bucket, confidence score, and resolution path.
2. **Given** a document that mentions a watchlist drug and describes a hospitalization-level adverse reaction, **When** triage runs, **Then** the finding is assigned bucket `urgent` and routed to the expedited queue within 5 minutes of ingestion.
3. **Given** a document that mentions a watchlist drug and describes a mild, non-serious adverse reaction, **When** triage runs, **Then** the finding is assigned bucket `minor` and status is set to `pending_batch`.
4. **Given** a document where the model returns NO adverse event but the finding describes a beneficial drug effect, **When** valence assessment runs, **Then** the finding is assigned bucket `positive` and status is set to `pending_batch`.
5. **Given** a document where the model returns NO adverse event and valence assessment determines it is medically irrelevant, **When** triage completes, **Then** the finding is assigned bucket `irrelevant`, excluded from both queues, and remains indexed for cross-document context.
6. **Given** a YES-classified document sourced from a regulatory feed (FDA MedWatch, EMA, or MHRA) whose text contains no strong ICH keyword matches, **When** severity bucketing runs, **Then** the finding is bucketed `urgent` via the source-reliability floor rather than `minor`.

---

### User Story 2 - Drug Pre-Filter Prevents False Classifications (Priority: P2)

A platform admin monitors processing costs and observes that documents fetched by broad search terms that only mention a watchlist drug in passing (e.g., as a comparison drug in an unrelated study) are not consuming classification resources.

**Why this priority**: Preventing spurious classification of documents that do not substantively mention a watchlist drug directly reduces false-positive findings in the reviewer queue and avoids unnecessary processing load.

**Independent Test**: Can be tested by submitting a document that mentions a watchlist drug only incidentally (e.g., as a control in an unrelated trial) and confirming it is filtered before classification, with a structured log entry explaining the filter decision.

**Acceptance Scenarios**:

1. **Given** a document that mentions a watchlist drug only incidentally in a comparison table with no substantive clinical context, **When** the pre-filter runs, **Then** the document is filtered before classification and logged as filtered with the reason.
2. **Given** a document that substantively discusses a watchlist drug as the primary subject of adverse-event data, **When** the pre-filter runs, **Then** the document passes through and proceeds to the classifier.

---

### User Story 3 - Per-Client Custom Severity Keywords Applied at Bucketing (Priority: P3)

A pharma client's safety team flags that their specific drug carries a known increased risk for a particular reaction that is not captured by default ICH criteria. The platform admin adds a custom severity keyword for that client. Afterwards, findings containing that term are correctly bucketed as `urgent` rather than `minor`.

**Why this priority**: Custom severity keywords are a contractual commitment to clients that their organization-specific safety thresholds are respected. Default ICH criteria alone may miss client-defined serious signals.

**Independent Test**: Can be tested by configuring a custom keyword for a specific test client, then processing a document containing that keyword, and verifying the bucket assigned matches the configured override — without affecting other clients.

**Acceptance Scenarios**:

1. **Given** a client with custom keyword "rhabdomyolysis" configured at the `urgent` tier, **When** a YES-classified finding's text contains that term, **Then** the finding is bucketed as `urgent` even if it would otherwise qualify as `minor` under default ICH criteria.
2. **Given** two clients where only one has the custom keyword configured, **When** the same finding text is processed for each client, **Then** the client with the keyword gets the elevated bucket and the other gets the default ICH bucket.

---

### User Story 4 - Triage Bias Toward Escalation Is Measurable (Priority: P4)

A safety officer reviewing the system's evaluation report confirms that when the classifier produces borderline results, the triage pipeline forwards uncertain findings to the LLM for resolution rather than blindly escalating them — reducing false-alarm noise while preserving the safety guarantee. When the LLM is also unavailable, the system still errs toward escalation. This behavior is proven with a committed number against a golden set.

**Why this priority**: Pharmacovigilance regulations require that missed serious adverse events are treated as a more costly error than false escalations. The safety bias must be intentional, proven, and CI-gated — not accidental.

**Independent Test**: Can be fully tested by running the triage golden set evaluation, confirming that precision and recall meet committed thresholds in `eval_thresholds.yaml`, and verifying the failure direction is toward escalation (false negatives are rarer than false positives).

**Acceptance Scenarios**:

1. **Given** the triage golden set (covering all five buckets with known labels), **When** the CI eval gate runs, **Then** precision and recall both meet or exceed the committed thresholds in `eval_thresholds.yaml` and the results are reported in the CI log.
2. **Given** a borderline finding where the model confidence is below the committed threshold, **When** triage processes it, **Then** the finding is forwarded to the LLM for YES/NO resolution; if the LLM is also unavailable, the system escalates the finding rather than suppressing it.

---

### Edge Cases

- What happens when the classifier returns a confidence score below the committed threshold? → The finding is forwarded to the LLM for YES/NO resolution before bucketing; if the LLM is also unavailable, the system escalates rather than suppresses.
- What happens when the LLM valence call fails for a NO finding? → System defaults to `positive` (escalation-safe) rather than `irrelevant`, and logs the failure.
- What happens when a document mentions multiple watchlist drugs with conflicting severity signals? → Each drug-reaction pair is treated as an independent finding; each is bucketed independently.
- What happens when per-client custom keywords overlap with default ICH criteria? → Custom keywords extend the default set; they never narrow it. A keyword that would cause a downgrade is ignored.
- What happens when a document passes the pre-filter but the classifier is unreachable? → No finding is created (a decision can't be made safely without the classifier); the triage attempt fails and is retried (never silently dropped). A `triage.operator_alert` ERROR event is emitted (FR-019) — note this is a structured-log alert, not an `audit_log` row, because no finding exists to audit. The document remains in the "embedded but no finding" set until a retry succeeds.
- What happens when the same document is submitted for triage twice (duplicate ingestion or retry)? → The second run is idempotent via the `(document_id, drug, reaction)` key; an existing finding is found rather than duplicated, and an already-assigned terminal bucket is not overwritten.
- What happens when triage does not fire for a document (e.g., the trigger event is lost)? → Documents that were embedded and passed the pre-filter but produced no finding beyond a maximum age are surfaced by a monitoring sweep; no document silently stays untriaged indefinitely.
- What happens when a YES-classified regulatory alert finding has no strong ICH keyword match (e.g., a short bureaucratic alert with no explicit seriousness terms)? → The source-reliability floor applies; the finding is bucketed `urgent` regardless of keyword match strength.
- What happens when a NO-classified regulatory alert is genuinely about something irrelevant to the client's drug (e.g., a packaging labelling update)? → LLM valence runs with the document's `source_reliability` as context; the LLM can still classify the finding as `irrelevant` if the content is genuinely out of scope. Auto-assigning `positive` is not correct here — the LLM remains the arbiter.
- What happens when a document has no `source_reliability` field set (e.g., ingestion failed to tag it)? → Triage treats the document as non-regulatory; the source-reliability floor (FR-003) does not apply and the LLM valence prompt receives no source context override.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST verify that each candidate document substantively mentions a watchlist drug for the relevant client before invoking the classification step. **Substantive mention is defined deterministically**: a normalized watchlist drug value matches a `CHEMICAL` entity (exact normalized equality OR the watchlist value is a whole-token substring of the entity), AND that matched mention either (a) occurs in the document title or summary/abstract text, OR (b) co-occurs with at least one `DISEASE` entity in the same sentence (i.e., it forms a candidate drug-reaction pair). A drug matched only once, only outside the title/summary, with no same-sentence `DISEASE`, is **incidental** and the document is filtered (no finding). NER runs over `title + "\n" + summary`.
- **FR-002**: System MUST classify each candidate finding using a three-stage pipeline: (1) trained model produces YES/NO verdict with confidence score; (2) if confidence is below the committed `triage_confidence_threshold` (application config), the finding is forwarded to the LLM for a second YES/NO determination; (3) if the LLM is also unavailable, the finding is escalated as the fail-safe default.
- **FR-003**: For YES-classified findings (by model or LLM resolution), System MUST assign a severity bucket (`emergency`, `urgent`, or `minor`) based on ICH E2E seriousness criteria applied to the finding text — the seriousness criteria being death; life-threatening; hospitalization or its prolongation; persistent or significant disability/incapacity; congenital anomaly/birth defect; or other medically important condition. Bucket comparison reuses the existing ordered `SeverityLevel` enum (`app/clients/enums.py`: non-serious < serious < life-threatening). For findings sourced from `regulatory_alert` documents (FDA MedWatch, EMA, MHRA), the minimum bucket is `urgent`; the keyword rule may still escalate to `emergency` but MUST NOT result in `minor` regardless of keyword match strength.
- **FR-004**: Per-client custom severity keywords MUST extend the default ICH criteria; a custom keyword MUST NOT narrow or override a higher-severity default assignment.
- **FR-005**: For NO-classified findings (by model or LLM resolution), System MUST assess valence (`positive` or `irrelevant`). **Definitions (used verbatim in the valence prompt so implementers and the LLM converge):** `positive` = the text describes a **beneficial or favorable outcome attributable to the watchlist drug** (e.g., efficacy, symptom improvement, successful treatment, good tolerability). `irrelevant` = the drug is mentioned but there is **no adverse event and no beneficial-outcome signal about it** (e.g., comparator/control arm, methods or pharmacokinetics description with no outcome, packaging/administrative note, or unrelated context). The decision boundary is "is there a beneficial drug→outcome signal?": yes → `positive`; no meaningful drug-outcome signal → `irrelevant`.
- **FR-006**: Findings bucketed as `urgent` or `emergency` MUST be routed to the expedited queue with status `pending_expedited`.
- **FR-007**: Findings bucketed as `minor` or `positive` MUST be accumulated in the batch queue with status `pending_batch`.
- **FR-008**: Findings bucketed as `irrelevant` MUST be assigned the terminal status `classified` (not routed to any queue); the underlying document and its chunks remain indexed and available as cross-document context.
- **FR-009**: Triage MUST fire automatically per-document as soon as a document's embedding is complete; urgent and emergency findings MUST NOT wait for other documents in the same cycle to finish embedding before being routed.
- **FR-010**: Triage creates each finding row (no finding exists before triage runs). Findings are uniquely keyed by `(document_id, drug, reaction)`; a triage re-run for a document that already produced a finding for a given drug-reaction pair MUST be idempotent — it MUST find the existing finding by that key and MUST NOT create a duplicate or overwrite an already-assigned terminal bucket. The terminal triage statuses are `pending_expedited`, `pending_batch`, and `classified`.
- **FR-011**: Every triage decision MUST be recorded in the audit log with finding ID, client ID, assigned bucket, confidence score, resolution path (model / llm / escalated), and routing outcome. The audit record MUST be written atomically with the finding status update in the same database transaction; a status update without a corresponding audit record is not permitted.
- **FR-012**: Triage decisions MUST be client-scoped; a finding for one client MUST NOT be influenced by another client's custom keywords or severity configuration.
- **FR-013**: The system MUST provide an endpoint for querying the current triage state (bucket and status) of a finding by finding ID.
- **FR-014**: Triage MUST NOT populate `corroboration_sources` on a finding; that field is left null at triage time and is the responsibility of the report drafting step (spec 9).
- **FR-015**: A triage golden set evaluation MUST be integrated into CI, reporting precision and recall against thresholds committed in `eval_thresholds.yaml`. The committed starting floors are **recall ≥ 0.90** and **precision ≥ 0.75** (asymmetric by design — a missed serious event is the costlier error). If *either* metric falls below its floor, merge is blocked (not the average of the two).
- **FR-016**: When LLM valence assessment is unavailable or fails for a NO-classified finding, the system MUST default to bucket `positive` rather than `irrelevant`, and MUST log the failure with finding ID, client ID, and the reason for the fallback.
- **FR-017**: The LLM valence assessment prompt MUST receive the document's `source_reliability` as context for all documents, enabling the LLM to weigh source authority when assessing borderline NO-classified findings without forcing a predetermined outcome.
- **FR-018**: Triage MUST handle each external-dependency failure with a defined, distinct behavior (after the standard tenacity retries are exhausted):
  - **Classifier (modelserver `/classify`) unreachable/errors** → **no finding is created**; the triage attempt fails and the document remains in the "embedded, no finding" set for retry. A decision cannot be made safely without the classifier, so the document is never silently dropped and never force-bucketed.
  - **LLM unreachable/errors** → a finding **IS** created via the fail-safe path (low-confidence resolution → escalate = expedited per FR-002; valence → `positive` per FR-016). The LLM is only a refinement, and escalation is the safe direction.
  - **Database error during finding upsert or audit write** → the whole transaction rolls back (a finding is never persisted without its audit row, per FR-011); the document remains untriaged for retry.
  - **Watchlist/client config read failure** → treated as a transient triage failure (no finding; retry), same class as a database error.
- **FR-019**: When triage cannot make a decision due to a classifier or database/config failure (FR-018 cases that produce no finding), the system MUST emit a distinct operator-alert structured-log event named `triage.operator_alert` at ERROR level carrying `client_id`, `document_id`, `stage` (`classify` | `persist` | `config`), and a non-PII `reason`. In v1 this structured event IS the operator alert; downstream routing of the event to a notification channel (n8n/paging) is owned by spec 11. The staleness sweep (SC-001) is the aggregate backstop.

### Key Entities *(include if feature involves data)*

- **Finding**: Represents a candidate adverse event (one drug-reaction pair) associated with a watchlist drug for a specific client. **Created by triage** (this spec ships the `findings` table in migration 0007); it does not exist before triage runs. Uniquely keyed by `(document_id, drug, reaction)`. The finding is born with its terminal bucket and status already assigned — there is no intermediate pre-triage state on the finding itself. Key attributes: `bucket` (irrelevant / positive / minor / urgent / emergency), `status` (terminal: pending_expedited / pending_batch / classified), `model_confidence` (0–1 float), `resolution_path` (model / llm / escalated), `corroboration_sources` (null at triage time; populated by spec 9).
- **Severity Rule**: The compound rule applied to YES-classified findings. Consists of three layers applied in order: (1) default ICH E2E seriousness keyword set, (2) per-client `custom_severity_keywords` extensions, (3) source-reliability floor — `regulatory_alert` sources enforce a minimum bucket of `urgent`. Bucket assignment is deterministic given the rule set, the finding text, and the document's source reliability.
- **Triage Pipeline**: The ordered processing sequence per document: pre-filter → three-stage classify (model → LLM if confidence below threshold → escalate if LLM unavailable) → severity bucket or valence assess → route. Fires automatically per-document on embedding completion. Each stage produces a structured log entry and contributes to the final audit record.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every embedded document that passes the drug pre-filter produces at least one finding within the processing cycle. When a watchlist drug is matched but no reaction entity can be extracted, the document still produces one finding with a sentinel reaction (`"unspecified"`) rather than being dropped — this is how "no extractable drug-reaction pair" is recorded. No embedded, pre-filter-passing document is left without a corresponding triage outcome at cycle end; a staleness sweep surfaces any document that was embedded but never produced a finding beyond a maximum age.
- **SC-002**: Triage precision and recall on the golden set meet or exceed the committed floors (recall ≥ 0.90, precision ≥ 0.75) in `eval_thresholds.yaml`; the CI gate reports both numbers and blocks merge if either falls below its floor.
- **SC-003**: The triage system demonstrates a measurable bias toward escalation on the golden set — false negatives (missed serious events) are fewer than false positives (over-escalated minor events).
- **SC-004**: Documents that do not substantively mention a watchlist drug are filtered before reaching the classification step, as confirmed by structured log evidence in test runs.
- **SC-005**: Per-client custom severity keywords correctly change bucket assignments for the target client without affecting other clients, verified by an isolated test per client configuration.
- **SC-006**: All triage decisions are traceable in the audit log; a compliance query for any finding returns the bucket, confidence score, resolution path, and routing outcome with no gaps.
- **SC-007**: When the LLM is unavailable, both fail-safe paths produce the escalation-safe outcome: uncertain-confidence findings escalate to the expedited bucket, and NO-classified findings default to `positive` rather than `irrelevant` — both confirmed by injecting an LLM service fault in tests (FR-002, FR-016).
- **SC-008**: Urgent and emergency findings are available in the expedited queue within 5 minutes of document ingestion, measured from ingestion timestamp to `pending_expedited` status transition.

## Assumptions

- Documents have already been parsed, chunked, and indexed by the time triage runs (spec 6 complete).
- The trained adverse-event classifier ONNX artifact is available via the modelserver `POST /classify` endpoint (spec 5 complete).
- No `findings` table exists prior to this spec — verified against migrations 0001–0006, which created `documents`, `document_sources`, `chunks`, and ingestion-run tables but no findings. **Spec 8 owns a new migration (0007) creating the `findings` table** with columns `client_id`, `document_id`, `drug`, `reaction`, `bucket`, `status`, `model_confidence`, `resolution_path` (model / llm / escalated), and `corroboration_sources` (nullable), plus a unique constraint on `(document_id, drug, reaction)` and indexes on `client_id`, `status`, and `bucket`.
- No `custom_severity_keywords` column exists today (verified against `app/clients/models.py`); custom severity keywords were deferred to spec 8 per the project backlog. **Spec 8 adds the `custom_severity_keywords` column** (per-client, JSON, keyword→tier) in the same migration 0007 and enforces it at bucketing time.
- Spec 8 ships the concrete ICH E2E seriousness keyword list as a versioned application artifact under `app/` (application code, not config), reusing the existing ordered `SeverityLevel` enum (`app/clients/enums.py`) for tier comparison.
- Watchlist items (drug names) are already stored per client and are available for the pre-filter step (spec 3 complete).
- `corroboration_sources` is out of scope for this spec; triage leaves it null. The report drafting step (spec 9) is responsible for populating it.
- The low-confidence `triage_confidence_threshold` is committed in application config (`Settings`, `app/core/config.py`) as part of this spec's deliverables; only the CI-gate precision/recall floors live in `eval_thresholds.yaml` (nothing loads that file at runtime).
- The triage golden set is created as part of this spec's deliverables and committed under `tests/`. It MUST include at least one labeled case for each of: (1) all five buckets (irrelevant / positive / minor / urgent / emergency); (2) the regulatory-alert severity floor (YES + regulatory source + weak keyword → `urgent`); (3) low-confidence → LLM resolution; (4) `source_reliability` absent (treated as non-regulatory); (5) a NO-classified regulatory alert the LLM arbitrates to `irrelevant`; (6) a custom-keyword escalation (client keyword lifts `minor` → `urgent`). These six behaviors are the ones this spec introduces and are the highest silent-regression risk for the CI gate.
- The LLM adapter (Anthropic/OpenAI) is already wired in the application lifespan (established in prior specs); this spec adds both the valence classification prompt and the low-confidence resolution prompt.
- Severity keyword matching operates on the full finding text and is case-insensitive; no fuzzy matching is required in v1.
- PDF-source documents are considered out of scope for the triage pre-filter in v1 (stretch goal from spec 6); plain-text and XML-sourced findings are in scope.
- The `source_reliability` field is set on each document by the ingestion step (spec 4) before triage runs; triage depends on this value for the regulatory alert severity floor (FR-003) and the LLM valence context (FR-017). If `source_reliability` is absent, triage treats the document as non-regulatory.
- If a client's `custom_severity_keywords` list is empty or not configured, severity bucketing falls back entirely to default ICH E2E seriousness criteria with no custom extensions.
- Handling of in-flight triage when a client is suspended mid-cycle is out of scope for spec 8; client lifecycle is owned by spec 3. Triage processes documents using the client configuration active at processing time.
- **Deferred to the plan (documented, not omitted):** the staleness-sweep maximum-age threshold, the per-stage structured-log schema, and any triage queue-depth/observability metrics are implementation-level decisions for `/speckit-plan`, not spec-level requirements.
- **Deferred — throughput:** no explicit documents-per-minute throughput target is set at the spec level; the SC-008 5-minute expedited-latency SLA is the binding performance constraint, and at the expected corpus scale (tens to low hundreds of documents per cycle) per-document async processing satisfies it without a separate throughput requirement.
