# Quickstart: Triage & Routing (Spec 8)

Validation guide proving triage works end-to-end. Implementation detail lives in `tasks.md`;
data shapes in [data-model.md](./data-model.md); interfaces in [contracts/](./contracts/).

## Prerequisites

- Full stack up (this host): `docker compose up` + gitignored `docker-compose.override.yml`
  (ports 5433/6380), Vault secrets pointed at localhost — see `memory/host-integration-test-vault-repoint`.
- `uv sync` including the new `scispacy` dependency; download the model once:
  `uv run python -m spacy download en_ner_bc5cdr_md` (or the pinned wheel URL added in `pyproject.toml`).
- `uv run alembic upgrade head` → applies migration **0007** (creates `findings`, adds
  `clients.custom_severity_keywords`).
- A seeded client with a watchlist containing a known drug (e.g. via `scripts/seed_client.py`), and at
  least one embedded document (run the spec-6 index build so documents reach `INDEXED`).

## Scenario 1 — Happy path: five buckets route correctly (US1)

1. Seed five documents for the client, one per target bucket (life-threatening reaction; hospitalization
   reaction; mild reaction; beneficial-effect text; off-topic text).
2. Run the index build (triage fires per-document automatically on `INDEXED`).
3. Query each finding: `GET /clients/{id}/findings/{finding_id}`.

**Expected:** emergency→`pending_expedited`, urgent→`pending_expedited`, minor→`pending_batch`,
positive→`pending_batch`, irrelevant→`classified`. Each has an `audit_log` row
(`event_type=FindingClassified`) with bucket, confidence, and `resolution_path`.

## Scenario 2 — Drug pre-filter (US2)

1. Seed a document mentioning the watchlist drug only as an incidental comparator (no DISEASE entity
   tied to it).
2. Run triage.

**Expected:** no finding created; a `triage.prefilter.filtered` structured log line with the reason.
A second document substantively discussing the drug + a reaction does produce a finding.

## Scenario 3 — Custom severity keyword escalation (US3)

1. Set `clients.custom_severity_keywords = [{"keyword":"rhabdomyolysis","tier":"serious"}]` for client A
   only.
2. Triage a document whose reaction text contains "rhabdomyolysis" that would otherwise be `minor`,
   for client A and for client B (no keyword).

**Expected:** client A → `urgent`; client B → `minor`. Confirms client-scoped application (FR-012, SC-005).

## Scenario 4 — Regulatory-alert floor (US1 / FR-003)

1. Seed a `source_reliability='regulatory_alert'` document, YES-classified, with weak ICH keywords.

**Expected:** bucket `urgent` (floor), not `minor`.

## Scenario 5 — Fail-safe under LLM outage (US4 / SC-007)

1. Point the LLM at an unreachable endpoint (or inject a fault).
2. Triage (a) a low-confidence finding and (b) a NO-classified finding.

**Expected:** (a) escalates to an expedited bucket; (b) defaults to `positive`. Both log the failure
with `client_id`/`finding_id`/reason. No finding is dropped.

## Scenario 6 — Idempotency (FR-010)

1. Run triage twice over the same document.

**Expected:** finding count unchanged; assigned bucket not overwritten; second run logs the idempotent
(`created=false`) path.

## Scenario 7 — CI eval gate (US4 / FR-015)

```
uv run python -m tests.integration.test_triage_eval   # or the eval runner wired into ci.yml
```

**Expected:** prints precision + recall over `tests/data/triage_golden_set.jsonl`; passes only if
recall ≥ 0.90 AND precision ≥ 0.75; the golden set includes the six mandatory case categories
(spec Assumptions), including a planted-injection case whose outcome is unchanged.

## Teardown

`uv run alembic downgrade -1` reverts migration 0007 (drops `findings`, removes the column). Confirm a
clean down-migration as part of the spec's done criteria (repo convention).
