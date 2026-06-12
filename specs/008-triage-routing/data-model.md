# Data Model: Triage & Routing (Spec 8)

Migration **0007** (`0007_findings_and_custom_keywords.py`), revises down to `0006_chunks_index_state`.
Two changes: create `findings`; add `clients.custom_severity_keywords`.

---

## New table: `findings`

One row per `(document_id, drug, reaction)` candidate adverse event, created by triage.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BigInteger PK | autoincrement |
| `client_id` | BigInteger, NOT NULL | tenant scope (Principle V); indexed |
| `document_id` | BigInteger, FK → `documents.id` ON DELETE CASCADE, NOT NULL | source document |
| `drug` | String(512), NOT NULL | normalized watchlist drug (CHEMICAL entity) |
| `reaction` | String(512), NOT NULL | normalized reaction term (DISEASE entity); `"unspecified"` sentinel when none extracted |
| `bucket` | String(16), NOT NULL | CHECK `IN ('irrelevant','positive','minor','urgent','emergency')` |
| `status` | String(20), NOT NULL | CHECK `IN ('pending_expedited','pending_batch','classified')` |
| `model_confidence` | Numeric(5,4), nullable | raw classifier confidence (null when LLM-resolved/escalated) |
| `resolution_path` | String(12), NOT NULL | CHECK `IN ('model','llm','escalated')` |
| `corroboration_sources` | JSONB, nullable | **null at triage time**; populated by spec 9 (FR-014) |
| `created_at` | DateTime(tz), server_default now() | |
| `updated_at` | DateTime(tz), server_default now(), onupdate now() | |

**Constraints / indexes**
- `UNIQUE (document_id, drug, reaction)` — name `ux_findings_doc_drug_reaction`; the idempotency key
  (FR-010), enforced via `INSERT ... ON CONFLICT DO NOTHING`.
- `Index ix_findings_client_id (client_id)`
- `Index ix_findings_status (status)` — expedited/batch queue scans
- `Index ix_findings_client_bucket (client_id, bucket)` — per-client triage reporting

**Lifecycle:** created already-terminal. `bucket`+`status` are set at insert; no pre-triage state on the
row. Spec 9 later mutates only `corroboration_sources` (and downstream report linkage).

**Bucket → status invariant** (enforced in `routing.py`, mirrored by acceptance tests):

| bucket | status |
|--------|--------|
| `emergency`, `urgent` | `pending_expedited` |
| `minor`, `positive` | `pending_batch` |
| `irrelevant` | `classified` |

---

## Altered table: `clients`

Add one column (additive, no backfill needed):

| Column | Type | Notes |
|--------|------|-------|
| `custom_severity_keywords` | JSONB, NOT NULL, server_default `'[]'` | array of `{keyword: str, tier: 'serious'|'life-threatening'}` |

Validation (application layer, `app/clients` write path is not changed by this spec — read-only here):
each `tier` ∈ `SeverityLevel` minus `non-serious`; matching is case-insensitive substring over finding
text; empty array ⇒ ICH defaults only (FR-004).

---

## Enums (`app/triage/enums.py`)

StrEnums mirrored by the CHECK constraints above (the spec-3 pattern: `String`+CHECK in DB, `StrEnum`
in code):

- `Bucket`: `IRRELEVANT, POSITIVE, MINOR, URGENT, EMERGENCY`
- `FindingStatus`: `PENDING_EXPEDITED, PENDING_BATCH, CLASSIFIED`
- `ResolutionPath`: `MODEL, LLM, ESCALATED`

Reused (not redefined): `SeverityLevel` from `app/clients/enums.py` for tier ranking.

---

## Domain events (`app/domain/events.py`)

Extend the existing placeholder `FindingClassified` (currently `finding_id, bucket, confidence`) to
carry the audit fields FR-011 requires, so the existing auto-registered `audit_log_handler` writes a
complete, atomic record within the finding-write transaction:

```text
FindingClassified(DomainEvent):
  finding_id: int
  bucket: str
  confidence: float
  resolution_path: str        # new — model | llm | escalated
  routing_outcome: str        # new — the status assigned (pending_expedited | pending_batch | classified)
  # client_id / actor_id / actor_type inherited from DomainEvent
```

The handler already targets `finding:{finding_id}` (verified in `app/audit/handler.py`) and dispatch
runs inside the caller's transaction — satisfying FR-011 atomicity with no handler change.

---

## Config placement (runtime vs CI) — IMPORTANT

Nothing in the app loads `eval_thresholds.yaml` at runtime (it is read only by the CI eval script).
So runtime knobs live in `Settings` (`app/core/config.py`), and only the CI-gate floors live in the yaml.

**Runtime — add to `Settings`:**

```python
modelserver_url: str = "http://modelserver:8001"   # was only a getattr fallback before
triage_confidence_threshold: float = 0.70           # below → LLM resolution (FR-002)
triage_staleness_max_age_minutes: int = 30          # SC-001 sweep
triage_llm_max_tokens: int = 256                    # cap on valence/resolution LLM calls
```

**CI gate only — add to `eval_thresholds.yaml`:**

```yaml
triage:
  recall_min: 0.90      # FR-015 floor (fails-safe asymmetry)
  precision_min: 0.75   # FR-015 floor
```
