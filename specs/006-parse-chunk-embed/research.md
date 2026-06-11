# Research & Decisions: Parse, Chunk & Embed — RAG Index Build

Phase 0 output. Resolves the plan-level items deferred by `/speckit-clarify` plus the technology
choices in Technical Context. Format per decision: **Decision / Rationale / Alternatives considered**.

---

## D1 — pgvector index type for the dense embedding

**Decision**: Store the embedding as `Vector(768)` (via the `pgvector` SQLAlchemy type) and create an
**HNSW** index using **`vector_cosine_ops`** (`m=16`, `ef_construction=64` defaults). Embeddings are
L2-normalized by the embedder, so cosine and inner-product rank identically; cosine ops are the
clearest choice for Spec 7.

**Rationale**: HNSW gives high recall **without** the IVFFlat requirement to size `lists` to row
count and to (re)build after the table is populated — important here because a client's index starts
empty and grows incrementally per FR-009, exactly the regime where IVFFlat recall is poor until
trained. pgvector ≥0.5 (present in `pgvector/pgvector:pg16`) supports HNSW; 768 dims is well within
HNSW's 2000-dim limit. Build/insert cost is acceptable at Pantera's moderate per-client scale.

**Alternatives considered**: *IVFFlat* — lower memory, but needs `lists` tuning and a populated table
to train, and degrades on an incrementally-built index. *No ANN index (exact scan)* — fine at tiny
scale and simplest, but FR-015 requires the index and Spec 7 expects sub-linear search; an exact
scan would need rework later. *HNSW upgrade left to Spec 7* — rejected: FR-015 says leave the index
hybrid-ready now so Spec 7 needs no schema rework.

## D2 — `client_id` on the two new bookkeeping tables

**Decision**: Denormalize **`client_id` onto both** `document_index_state` and `index_build_runs`
(not only on `chunks`). All Spec-3/4 tables already carry `client_id`.

**Rationale**: Enables direct client-scoped queries and counts without joining back through
`documents`, matches the established per-table tenant-scoping pattern (and the future RLS direction in
the backlog), and keeps isolation invariants uniform (FR-014). Cost is one indexed `bigint` column.

**Alternatives considered**: Derive client via the `documents`/run join only — rejected: extra joins
on every scoped read and inconsistent with every other table in the schema.

## D3 — `chunk.date` provenance

**Decision**: `chunk.date` is **inherited from `documents.published_at`** (nullable). It is metadata
for Spec-7 recency filtering, not re-parsed from chunk content in v1.

**Rationale**: Deterministic, free, and consistent across a document's chunks. Per-chunk date
extraction has no v1 consumer and would invite the same false-precision problem as per-chunk `drug`
(FR-023).

**Alternatives considered**: Parse dates from chunk text (rejected — no consumer, ambiguous);
leave null (rejected — `published_at` is already available and useful to Spec 7).

## D4 — Lexical search vector (`tsvector`)

**Decision**: Store a `tsvector` column computed as **`to_tsvector('english', text)`** as a Postgres
**stored generated column**, indexed with **GIN**. The chunk's plain `text` remains stored separately
for display/citation.

**Rationale**: A generated column guarantees the lexical vector always matches the stored text (no
drift, no app-side maintenance), and `english` is the right config for predominantly English
biomedical prose. GIN is the standard full-text index. This is the lexical leg Spec 7's hybrid
retrieval fuses with the dense leg (FR-015).

**Alternatives considered**: Compute `tsvector` in the app at insert (rejected — drift risk, more
code); language `simple` (rejected — loses stemming, weaker recall); defer to Spec 7 (rejected —
FR-015 requires the substrate now).

## D5 — Chunk ordering

**Decision**: Each chunk carries an integer **`ordinal`** assigned sequentially in parse order within
its document (0-based), part of the persisted contract (FR-007). Unique per `(document_id, ordinal)`.

**Rationale**: Gives Spec 7 a deterministic way to present/merge adjacent passages and makes chunk
sets reproducible. Trivial to assign during parsing.

**Alternatives considered**: Rely on insertion `id` order (rejected — not stable across re-index or
parallel inserts); omit ordering (rejected — entity already specifies it; Spec 7 benefits).

## D6 — Exact token counting + tokenizer/version verification (FR-008/FR-025)

**Decision**: The chunker counts tokens with the **embedder's own `tokenizer.json`**, loaded once via
the `tokenizers` library from a configured path (`settings.embedder_tokenizer_path`, default the
committed `modelserver/models/tokenizer.json`). It reserves a small **special-token budget** (read
from/aligned to the embedder's `max_tokens`=512) and splits so every chunk is ≤ `512 − reserve`. At
build **startup**, the runner calls the modelserver `GET /ready`, reads
`ready_json["models"]["embedder"]["sha256"]`, and verifies it equals a pinned
`settings.embedder_model_version` (**sha256 is the pinned/compared field**); on mismatch it
**refuses to run** the build (fail-fast), consistent with the platform's model-artifact-validation
discipline.

**Rationale**: Counting with the real tokenizer makes the 512 boundary exact, so the modelserver
truncation path is never hit in normal operation — protecting grounding (Constitution II): a citation
can never point at text the embedder silently dropped. Loading only the tokenizer (a tiny CPU-only
artifact) does not bloat the app and does not pull torch. Startup verification turns a silent
tokenizer/embedder drift into a loud boot-time failure.

**Alternatives considered**: *Heuristic `chars/4` + margin* — simpler and decoupled, but accepts rare
silent truncation, which is unacceptable for grounding in this domain (decided against during
clarify). *Reactive re-split on truncation warning* — extra round-trips, reactive. *Ship the whole
embedder model into the app* — violates the lean-app/modelserver boundary; only the tokenizer is
needed.

## D7 — Embedding storage type & embedder model-version stamp

**Decision**: Use the `pgvector` package's SQLAlchemy `Vector(768)` type for the column. Each chunk
stores `embedder_version` = `result["model_version"]["sha256"]` from the **per-result** dict the
modelserver returns on `/embed` (`embed_chunked` returns `list[dict]`; each item is
`{"embedding": [...], "model_version": {"name","version","sha256"}}` — dict access, not attributes).

**Rationale**: Native pgvector storage enables ANN search (D1). Stamping the embedder version per
chunk (from the authoritative response, not a hard-coded constant) makes a future re-embed campaign
(on embedder upgrade) selectable and auditable, and satisfies FR-007/FR-016.

**Alternatives considered**: Store embeddings as `float[]`/JSON (rejected — no ANN search);
hard-code the version (rejected — drifts from what actually produced the vector).

## D8 — Representative-source selection for multi-source documents (FR-024)

**Decision**: When a `documents` row has multiple `document_sources`, select **one** payload to parse:
order by **reliability tier** (`regulatory_alert` > `peer_reviewed` > `preprint` > `case_report`,
reusing `SourceReliability.rank`), break ties by **richness** (prefer a full-text source over an
abstract-only one — heuristic: larger serialized `raw_payload`/longer body), then by **most-recent
`fetched_at`**. Never merge chunks across a document's sources.

**Rationale**: Keeps one paper = one chunk set, preserving corroboration honesty (FR-009) and the
dedup guarantee from Spec 4, while still picking the most authoritative-and-richest available text.

**Alternatives considered**: Parse-all-and-merge (rejected — near-duplicate chunks corrupt
retrieval/corroboration); richness-first ignoring tier (rejected — could demote a regulatory alert
below a chatty case report). *Per-source richness signal*: a precise "is full text" flag isn't stored
by Spec 4, so richness is approximated by payload/body length; the source identity (e.g. `europepmc`
full-text vs `pubmed` abstract) is the primary practical signal — implementers read the Spec-4
adapters to confirm each payload's shape (see D9).

## D9 — Parsing the stored raw payloads (per-source shape)

**Decision**: Each parser consumes `document_sources.raw_payload` (JSONB) for its source. The
parser implementations MUST be written against the **actual shape each Spec-4 adapter stored** (read
`app/ingestion/adapters/*.py`): PubMed (E-utilities) JATS is parsed with **`lxml`**; Europe PMC
full-text JATS with `lxml` (sections + tables + figure captions); openFDA FAERS and drug-label
payloads are JSON dicts parsed with stdlib; MedWatch/EMA/MHRA alert payloads are the normalized
feed dicts → a single summary chunk. Where a payload stores XML as a string field, parse that field
with `lxml`; where it is already structured JSON, walk the dict.

**Rationale**: Spec 4 retained the raw payload precisely so Spec 6 can parse it; matching each
adapter's stored shape is the only way to parse faithfully. `lxml` is the Guide-sanctioned JATS
parser.

**Alternatives considered**: `xmltodict` (viable, but `lxml` gives precise section/table/caption
XPath control); a single generic parser (rejected — sources differ structurally; FR-001 mandates a
router with per-source parsers).

## D10 — Concurrency control: one in-flight build per client (FR-026)

**Decision**: Enforce a single active build per client by creating the `index_build_runs` row with a
`running` status and a **partial unique index** on `(client_id) WHERE status='running'`; a trigger
that violates it returns the existing in-flight run (HTTP 202 with that run) instead of starting a
second. As defense-in-depth, chunk insertion is **idempotent per document** via a unique constraint
on `(document_id, ordinal)` and the per-document atomic commit (D11) — so even a race cannot create
duplicate chunks.

**Rationale**: Mirrors Spec 4's `running` ingestion-run guard, is race-safe at the DB level (the
write-path-race-safety pattern already used in the project), and needs no external lock. Suits the
moderate scale; no need for per-document leasing.

**Alternatives considered**: Per-document compare-and-set leasing for parallel workers (rejected —
unnecessary complexity at this scale); no control (rejected — duplicate-chunk corruption).

## D11 — Per-document atomicity & resumability (FR-013/FR-028)

**Decision**: Process documents **one at a time**; for each, write all its chunks **and** flip its
`document_index_state` to `indexed` (or `indexed-empty`) inside **one transaction**. A crash leaves
that document `not-indexed`/`errored-transient` (never half-`indexed`), so a re-run reprocesses only
incomplete documents. Embedding (the network call) happens **before** opening the write transaction;
the transaction only persists already-obtained vectors, keeping it short.

**Rationale**: Atomic chunk+state commit makes "indexed ⇒ complete chunk set" an invariant, which is
exactly what resumability and idempotency rely on. Embedding outside the transaction avoids holding a
DB transaction open across a network round-trip.

**Alternatives considered**: Bulk-commit the whole run at the end (rejected — a late crash loses all
progress, defeating resumability); embed inside the transaction (rejected — long-held transaction
across network I/O).

## D12 — Trigger surface, auth, and execution model (FR-017/FR-027)

**Decision**: `POST /clients/{client_id}/index` returns **202** with an `IndexBuildRunOut`; it
requires a staff **manager/admin** (`require_admin`) and `acting_client(client_id)` for
server-validated, audit-attributed target-client scoping, and runs the build via FastAPI
`BackgroundTasks`. The session is managed explicitly so the run row commits **before**
`background_tasks.add_task` (the documented BG-task/session-timing pattern). Reads:
`GET /clients/{client_id}/index-runs` (list) and `GET /clients/{client_id}/index-runs/{run_id}`
(detail) use `acting_client_read`. A domain event (`IndexBuildTriggered`) is dispatched for the audit
log. No auto-chain from ingestion; cron is Spec 11.

**Rationale**: Exactly mirrors Spec 4's ingestion trigger (route shape, role guard, background
execution, event dispatch), minimizing novelty and matching reviewer expectations. `require_admin`
already means manager-or-admin.

**Alternatives considered**: Auto-chain after ingestion (rejected during clarify — Spec 11 owns
cycle wiring); ARQ-only trigger now (rejected — ARQ scheduling is Spec 11; BackgroundTasks matches
Spec 4 and is demonstrable today; the runner is already ARQ-ready via `session_factory`).

---

## Resolved unknowns

All Technical Context items are decided; **no `NEEDS CLARIFICATION` remain**. New runtime deps:
`pgvector`, `lxml`, `tokenizers`. New settings: `embedder_tokenizer_path`, `embedder_model_version`
(the pinned embedder **sha256**, compared to `/ready models.embedder.sha256`), and (optional) chunking
knobs (`chunk_target_tokens=256`, `chunk_overlap_ratio=0.15`, `chunk_max_tokens=512`) with
`extra="forbid"`-compatible defaults. The modelserver base URL is **not** a setting — the client
resolves it via `ModelserverClient.from_settings()` (default `http://modelserver:8001`); only
`modelserver_token` is a `Settings` field. No `eval_thresholds.yaml` change
(the RAG golden-set gate is Spec 7). No Spec-4 table altered; migration `0006` is purely additive.
