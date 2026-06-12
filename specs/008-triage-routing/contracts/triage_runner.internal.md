# Contract: Internal Per-Document Triage Entrypoint (FR-009)

Internal function contract (not an HTTP endpoint) invoked by `app/embedding/runner.py` after a
document reaches `DocumentIndexStatus.INDEXED`. Designed to be wrapped by an ARQ job in spec 11 with
no logic change.

## Signature

```python
async def triage_document(
    session_factory: Callable[[], AsyncSession],
    client_id: int,
    document_id: int,
    modelserver_client: ModelserverClient,
    llm_client: LLMClient,
) -> list[FindingOutcome]:
    ...
```

- `FindingOutcome` is an internal DTO (Pydantic), not an ORM object: `{drug, reaction, bucket,
  status, resolution_path, model_confidence, finding_id, created: bool}`.
- `created=False` indicates the idempotent path (finding already existed for that key).

## Behavior (ordered)

1. **Pre-filter (FR-001):** load the document text + the client's watchlist drug names; run BC5CDR NER.
   If no watchlist drug appears as a CHEMICAL entity → log `triage.prefilter.filtered` and return `[]`
   (no finding; document remains indexed for context).
2. **Entity pairing (D1):** for each matched drug × each DISEASE entity → a candidate `(drug, reaction)`.
   If a drug matched but no DISEASE entity → one candidate with `reaction="unspecified"`.
3. **Classify (FR-002):** call `/classify` per candidate finding text; apply `settings.triage_confidence_threshold` (use the raw `confidence`, not `is_adverse`).
   Below threshold → `llm.resolve_yes_no(...)`; LLM failure → escalate (treat YES).
4. **Bucket / valence:**
   - YES → `severity.bucket(text, source_reliability, custom_keywords)` (FR-003/004 + regulatory floor).
   - NO → `llm.valence(text, source_reliability)` → positive|irrelevant; LLM failure → `positive` (FR-016).
5. **Route + persist (FR-006/007/008/010):** map bucket→status; `INSERT ... ON CONFLICT
   (document_id, drug, reaction) DO NOTHING`. Within the same transaction, dispatch `FindingClassified`
   so the audit row is written atomically (FR-011).
6. Return the list of `FindingOutcome`.

## Guarantees

- **Idempotent** under retry/concurrency via the unique key (FR-010); a re-run never duplicates or
  overwrites an assigned bucket.
- **Client-scoped:** all reads (watchlist, custom keywords) and writes filter by `client_id` (FR-012).
- **Atomic audit:** finding insert + `FindingClassified` audit row share one transaction (FR-011).
- **Fail-safe (FR-018/FR-019, see implementation-notes §8.3):** classifier/DB/config failure → **no
  finding**, emit `triage.operator_alert` ERROR (stage=classify|persist|config), document stays in the
  "embedded, no finding" set for retry/sweep; LLM failure → finding created via fail-safe
  (escalate for resolution, `positive` for valence). Asymmetry: can't decide without classifier/DB →
  no finding; LLM is only a refinement → escalation-safe finding.
- **No PII/secret logging;** every line binds `client_id` + (`finding_id`|`document_id`).

## Caller integration

`app/embedding/runner.py::_process_document`, on the `INDEXED` success path, calls `triage_document(...)`
for that document. Failures in triage are logged and do not roll back the successful embedding (triage
is retried independently; the sweep is the backstop).
