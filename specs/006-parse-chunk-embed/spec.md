# Feature Specification: Parse, Chunk & Embed — RAG Index Build

**Feature Branch**: `006-parse-chunk-embed`

**Created**: 2026-06-10

**Status**: Draft

**Input**: User description: "Parse, chunk, and embed all ingested documents into the pgvector RAG index — parser router by source type, typed section-aware chunks, embeddings via the modelserver medical ONNX embedder, per-client scoping (spec 6 of the Pantera 13-spec build order). Owns the document parsing/chunking/embedding deferred from spec 4; produces the indexable substrate that spec 7 retrieval consumes."

## Overview

This is the **index-build half of RAG** (pipeline step 3). Spec 4 fetched literature and regulatory records and persisted them as **documents** (metadata) plus a retained **raw payload per source** — explicitly deferring parsing, chunking, and embedding to this spec. Spec 5 shipped the **modelserver** with a medical ONNX sentence embedder (768-dim, L2-normalized) and an async caller client.

This feature turns the stored corpus into a **searchable index**: it parses each document's raw payload by source type into typed, section-aware **chunks**, embeds every chunk via the modelserver's medical embedder (no external embedding API), and persists the chunks — each scoped to a client, linked to its document, carrying a dense vector for similarity search and a lexical search vector for full-text — so the later **retrieval** spec (7) can run hybrid search and the **triage**/**drafting** specs can act on grounded evidence.

It does **not** retrieve, rerank, aggregate corroboration, classify, or draft. Its responsibility ends when a document's chunks are durably stored and searchable.

## Clarifications

### Session 2026-06-10

- Q: How is the index build triggered in v1? → A: **Manual trigger endpoint only** (e.g. `POST /clients/{id}/index`), run in-process in the background. Ingestion does **not** auto-chain into indexing; the automatic ingest→index→triage cycle wiring stays in spec 11, mirroring spec 4's manual-trigger pattern.
- Q: Where is per-document index state stored? → A: In a **dedicated `document_index_state` table (1:1 with documents), owned by this spec** — not as columns on spec-4's `documents` table. This keeps the migration purely additive, isolates re-embedding churn (e.g., an embedder-version upgrade re-indexing the whole corpus) from the canonical `documents` table, and matches the established per-spec table-ownership pattern. A separate index-build-run record holds per-run counts.
- Q: What chunk sizing strategy does v1 use (within the embedder's 512-token window)? → A: **Section-aware splitting, target ~256 tokens per chunk, ~15% overlap, hard cap below 512 tokens.**
- Q: How is each chunk's `drug` field populated in v1? → A: **Left null in v1** (the column exists and is nullable). Provenance yields only the watchlist's whole drug set, not per-chunk truth; accurate per-chunk drug tagging waits for spec 8's scispaCy NER. Spec 7 may derive candidate drugs from the document↔watchlist link at query time if it needs a coarse filter.
- Q: For a document deduplicated across multiple sources (several `document_sources` payloads), which payload(s) are parsed? → A: **Parse only the single highest-reliability source's payload** (regulatory_alert > peer_reviewed > preprint > case_report), tie-broken by **richest content** (full text over abstract) then most-recent. One coherent chunk set per document — chunks are **never merged across a paper's sources**, preserving the one-paper-one-voice guarantee behind FR-009 and corroboration. (FR-024)
- Q: How are tokens counted for the ~256/512 chunk limits? → A: **Exactly, using the embedder's own tokenizer artifact/version**, reserving the special-token budget and splitting so every chunk is ≤512 tokens by construction; the modelserver truncation path MUST NOT be reached in normal operation (reaching it is an error, not a routine backstop). The loaded tokenizer version is **verified against the embedder model version at startup**, failing fast on mismatch, consistent with the platform's model-artifact validation. (FR-008, FR-025)
- Q: Are `errored` documents retried on a later run? → A: **By failure cause** — **transient** errors (modelserver/timeout/infra) leave the document eligible for retry on the next run; deterministic **parse failures are marked permanently failed**, skipped on re-runs and surfaced for inspection (no silent data loss, no infinite retry). (FR-011)
- Q: Should the `drug` column be indexed in v1 given it is always null? → A: **No** — keep the `drug` column (nullable) but do not create its index in v1; the index is added by spec 8 when the column is populated. (FR-015, FR-023)
- Q: How are concurrent index builds for the same client handled? → A: **At most one in-progress build per client** (mirroring spec-4's `running` ingestion-run guard); a trigger while one is active is a no-op that returns the in-flight run. A per-document idempotent write guard prevents duplicate chunks as defense-in-depth. (FR-026)
- Derived decisions (applied by default, not separately asked): (a) the index-build trigger requires a staff **`manager`/`admin`** via the `acting_client(client_id)` dependency — server-validated target client, audit-attributed; `reviewer` staff and client-users cannot trigger it (FR-027); (b) each document's chunks and its index-state transition to `indexed` commit in a **single transaction**, so a crash cannot leave a document marked indexed with a partial chunk set (FR-028).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Make a client's documents searchable (Priority: P1)

As the platform operating Pantera, once literature has been ingested for a client, the system must turn those raw documents into an embedded, searchable index so that downstream retrieval, triage, and report drafting have grounded evidence to work from. An operator initiates the index build for a client via a manual trigger (ingestion does not auto-start it in v1); every stored document that has not yet been indexed is parsed into chunks, each chunk is embedded by the medical embedder, and the chunks are persisted scoped to that client.

**Why this priority**: This is the spine of the spec — without embedded chunks there is no corpus for RAG. A single source type (e.g., PubMed) parsed, embedded, and stored already delivers a demonstrable, searchable index and unblocks spec 7. Everything else refines breadth, efficiency, and resilience.

**Independent Test**: Seed a client with one or more stored documents (from spec 4's fixtures), trigger the index build, and verify that each parseable document produces one or more chunks, each chunk has a 768-value embedding and a recorded embedder model version, and every chunk is scoped to that client.

**Acceptance Scenarios**:

1. **Given** a client with stored documents and no chunks, **When** the index build runs, **Then** each parseable document yields at least one persisted chunk, every chunk carries a 768-dimension embedding and the embedder's model version, and every chunk is linked to its document and scoped to the client.
2. **Given** a document that will (later) be classified irrelevant, **When** the index build runs, **Then** it is still parsed and embedded — irrelevant documents remain indexed as cross-document context (indexing is independent of classification).
3. **Given** the index build has completed for a client, **When** a downstream component queries that client's index, **Then** the chunks are available for similarity and full-text search and are attributed only to that client.

---

### User Story 2 - Faithful multi-format parsing into typed chunks (Priority: P2)

The corpus is heterogeneous — peer-reviewed JATS XML, full-text articles with tables and figures, structured FAERS case JSON, drug-label sections, and regulatory alert feeds. Each must be parsed by a source-appropriate parser into chunks that preserve its structure, so that retrieved evidence is meaningful and citable rather than garbled.

**Why this priority**: Domain-appropriate chunking is what makes retrieval and grounding trustworthy. It builds directly on US1's pipeline but broadens it from one source type to all of them, with correct chunk typing. P2 because US1 is already demonstrable on a single source type, but the full corpus value depends on this.

**Independent Test**: Run the parser router over one fixture per source type and verify each produces chunks of the correct type (`text` / `table` / `figure_caption` / `structured_data`), with section labels where applicable, tables serialized with their headers and never split mid-row, and figure captions preserved as discrete chunks.

**Acceptance Scenarios**:

1. **Given** a PubMed JATS document, **When** parsed, **Then** abstract/section prose becomes `text` chunks tagged with their section, and MeSH/metadata is captured.
2. **Given** a Europe PMC full-text article containing a table and a figure caption, **When** parsed, **Then** the table is serialized into a `table` chunk that repeats column headers per row (never split mid-row) and the caption becomes a single `figure_caption` chunk.
3. **Given** an openFDA FAERS case record, **When** parsed, **Then** it is serialized into a natural-language `structured_data` chunk (e.g., "Patient: <age>y <sex>. Drugs: …. Reactions: …. Outcome: …").
4. **Given** an openFDA drug label, **When** parsed, **Then** each label section becomes a chunk tagged with its section name.
5. **Given** a regulatory alert (FDA MedWatch / EMA / MHRA), **When** parsed, **Then** the alert summary becomes a chunk and every resulting chunk inherits `source_reliability: regulatory_alert`.
6. **Given** any parsed chunk, **When** it is persisted, **Then** it inherits its document's `source_reliability` tier.

---

### User Story 3 - Idempotent, incremental indexing (no double-embedding) (Priority: P2)

Index build runs repeatedly as new literature arrives. A document that is already indexed must never be parsed or embedded again, so cost stays bounded and one real paper is never represented by two sets of chunks (which would also distort downstream corroboration counts).

**Why this priority**: Embedding is the costly step and re-runs are the norm (manual now, scheduled in spec 11). Idempotency is the guardrail that makes re-runs safe. P2 because the index is demonstrable without it, but it is required before scheduled re-runs are sound.

**Independent Test**: Run the index build twice over an unchanged corpus and verify the second run creates zero new chunks and performs zero embedding calls; then add one new document and verify only that document is parsed and embedded on the next run.

**Acceptance Scenarios**:

1. **Given** a client whose documents are already indexed, **When** the index build runs again with no new documents, **Then** zero new chunks are created and zero embedding calls are made.
2. **Given** a client with both indexed and newly-ingested documents, **When** the index build runs, **Then** only the not-yet-indexed documents are parsed and embedded; existing chunks are untouched.
3. **Given** a document deduplicated across sources into a single document record (spec 4), **When** indexing runs, **Then** it is embedded exactly once (never once per contributing source).

---

### User Story 4 - Resilient, observable index build (Priority: P3)

Index build touches external inference (the modelserver) and parses messy real-world documents. A single malformed document or a transient embedder hiccup must not abort the whole run, and an operator must be able to see what was indexed, skipped, or errored.

**Why this priority**: Operability and fail-safety. The core value (US1–US3) is deliverable without rich observability, so this is P3 — but it is what makes the build trustworthy in production and debuggable when a source changes shape.

**Independent Test**: Include one unparseable document in a batch and verify it is skipped and recorded as errored while the rest of the batch indexes successfully; simulate a transient embedder failure and verify the call is retried (not on 4xx) and the run reports accurate per-document counts.

**Acceptance Scenarios**:

1. **Given** a document whose raw payload cannot be parsed, **When** the index build runs, **Then** that document is skipped and recorded as errored, and the remaining documents are still indexed (the run does not fail wholesale).
2. **Given** the modelserver returns a transient (5xx / timeout) error, **When** a chunk is embedded, **Then** the call is retried with backoff; a 4xx is never retried.
3. **Given** an index build has run, **When** an operator inspects its outcome, **Then** per-run counts (documents processed, chunks created, documents skipped/errored) and per-document index state are available.
4. **Given** the build is interrupted partway, **When** it is re-run, **Then** it resumes by indexing only the documents that were not completed (no duplicate or partial chunk sets for a completed document).

---

### User Story 5 - Hybrid-retrieval-ready index (Priority: P3)

The retrieval spec (7) performs hybrid search (dense similarity + lexical full-text) with reranking and corroboration. For that to be possible, this spec must store, per chunk, both a dense embedding and a lexical search vector, plus the metadata (drug, date, section, chunk type, reliability) and indexes those queries will filter and rank on.

**Why this priority**: It is forward-enabling substrate, not user-visible behavior on its own; spec 7 is what exercises it. P3 because US1–US3 already persist embeddings; this ensures the lexical leg and query-relevant metadata/indexes exist so spec 7 needs no schema rework.

**Independent Test**: After an index build, verify each chunk has a populated lexical search vector alongside its dense embedding, carries drug/date/section/chunk-type/reliability metadata, and that the metadata and vector indexes required for efficient hybrid query exist.

**Acceptance Scenarios**:

1. **Given** a persisted chunk, **When** inspected, **Then** it has both a dense embedding (for vector similarity) and a lexical full-text search vector derived from its text.
2. **Given** the index, **When** spec 7 issues a client-scoped hybrid query, **Then** the supporting indexes (client scoping, document link, chunk type, vector, full-text) exist so the query is efficient (the `drug` index is deferred to spec 8 with the column's population — FR-015).
3. **Given** this spec, **When** retrieval/reranking/corroboration behavior is sought, **Then** it is explicitly absent here (owned by spec 7) — this spec only builds the indexable substrate.

---

### Edge Cases

- **Document with no usable text** (only an identifier, or an empty/None summary and no parseable body): if the payload is structurally valid but yields no chunks, it is marked `indexed-empty` (done, will not be retried); only a payload that cannot be parsed is marked `errored-permanent` (FR-011). Either way the run does not crash.
- **Concurrent index-build triggers for the same client**: only one build runs; a second trigger received while one is active is a no-op returning the in-flight run (FR-026), and the per-document idempotent write guard ensures no duplicate chunks even if a race occurs.
- **Multi-source document**: a paper deduplicated across several sources is parsed from a single representative payload (highest reliability, then richest, then most-recent), never merged across sources (FR-024), so it produces exactly one chunk set.
- **Oversized section / very long document**: chunking MUST split content so every chunk fits the embedder's 512-token window; the spec MUST NOT rely on the modelserver's truncation safety net to silently drop text (truncation there is a last-resort warning, not the chunking strategy).
- **Single structural chunk exceeds the token cap** (a table row or a figure caption whose own serialized text is > the cap): the chunk MUST be hard-split at a token boundary (preferring a table-row boundary) as a last resort and the split logged; this is the only sanctioned in-spec split of a structural chunk and it still guarantees every emitted chunk is ≤512 tokens (FR-008), so the modelserver truncation path is never reached.
- **Table with no header row, or ragged rows**: serialized as best-effort `table` chunk without splitting a logical row across chunks; if wholly unparseable, recorded as `errored-permanent` for that document.
- **Embedder returns the wrong dimension** (not 768): the chunk MUST NOT be stored with a mismatched vector; the discrepancy MUST surface as an error rather than corrupt the index.
- **Client suspended or watchlist deactivated mid-build**: no new indexing is started for it; already-stored chunks are preserved (no destructive delete in this spec).
- **Document deleted / client erased** while indexing: chunks for a removed document/client must not be orphaned (cascade with the document); right-to-erasure of vectors is a later-spec concern but chunk storage MUST be erasable along with its document.
- **Modelserver unavailable for the whole run**: the run fails cleanly with retries exhausted; affected documents are marked `errored-transient` (eligible for retry) and the build is fully resumable later; no partial chunk set is left for a document that did not complete (FR-028).
- **Re-ingested document whose payload changed**: out of scope to re-embed on content change in v1 (documents are treated as immutable once stored); recorded as an assumption.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST parse each stored document's retained raw payload using a **parser router** that dispatches by source type, with a dedicated parser for each of the seven configured sources (PubMed, Europe PMC, openFDA FAERS, openFDA drug labels, FDA MedWatch, EMA, MHRA).
- **FR-002**: System MUST produce **typed chunks** with a `chunk_type` from `{text, table, figure_caption, structured_data}`, and MUST tag chunks with their **section** label where the source provides section structure.
- **FR-003**: System MUST chunk **section-aware**: prose is split along section boundaries; **tables** are serialized so column headers accompany each row and a logical row is never split across chunks; **figure captions** are preserved as discrete single chunks.
- **FR-004**: System MUST serialize **structured** records (openFDA FAERS cases) into natural-language `structured_data` chunks, and MUST split **drug-label** documents by section with the section name retained on each chunk.
- **FR-005**: System MUST embed every chunk via the **modelserver medical ONNX embedder** (768-dimension, L2-normalized) using the existing async caller client; it MUST NOT use any external embedding API.
- **FR-006**: System MUST embed **all** documents regardless of their eventual classification — documents that will later be classified irrelevant remain indexed as cross-document context.
- **FR-007**: System MUST persist each chunk with: `client_id` (tenant scope), a link to its `document_id`, the chunk text, `chunk_type`, section label, a `drug` reference and date where available, the inherited `source_reliability`, the dense embedding, a lexical full-text search vector derived from the text, and the **embedder model version** stamped on the chunk. In v1 the `drug` field is **nullable and left unpopulated** (see FR-023); the column exists so spec 8 can fill it accurately later.
- **FR-008**: System MUST ensure every chunk's text fits the embedder's **512-token** window by construction (chunking is this spec's responsibility); it MUST NOT depend on the modelserver's truncation safety net to fit content. Chunking is **section-aware** with a target of **~256 tokens per chunk**, **~15% overlap** between adjacent chunks, and a **hard cap below 512 tokens**; a section longer than the cap is sub-split, and structural chunks (whole `table` / `figure_caption`) are exempt from the overlap rule. A structural chunk whose **own** serialized text exceeds the cap MUST be hard-split at a token boundary (preferring a table-row boundary) as a last resort — logged — so the ≤512-token guarantee always holds. Token counts MUST be computed with the **embedder's own tokenizer** (see FR-025), reserving the special-token budget, so that no chunk can reach the modelserver's truncation path in normal operation; if truncation is ever reached it MUST be logged as an error, not treated as routine.
- **FR-009**: System MUST be **idempotent and incremental**: an already-indexed document MUST NOT be parsed or embedded again, re-runs MUST process only not-yet-indexed documents, and a document MUST be embedded **exactly once** even when it was deduplicated across multiple sources (spec 4). Re-running over an unchanged corpus MUST create zero new chunks and make zero embedding calls.
- **FR-010**: System MUST record an explicit **index state per document** — `not-indexed` / `indexed` / `indexed-empty` / `errored-transient` (retryable) / `errored-permanent` (do not retry) — plus the embedder model version used and the last error cause/attempt info (supporting FR-011), stored in a **dedicated `document_index_state` table (1:1 with documents) owned by this spec** — the existing spec-4 `documents` table MUST NOT be altered. System MUST also record **per-run counts** (documents processed, chunks created, documents skipped, documents errored) in a separate index-build-run record, so the build is observable and resumable.
- **FR-011**: System MUST be **resilient per document**: a failing document MUST be skipped and recorded without failing the whole run; the remaining documents MUST still be indexed. Failures MUST be **classified by cause**: a **transient** failure (modelserver/timeout/infrastructure) is recorded as `errored-transient` and leaves the document **eligible for retry** on a later run, while a deterministic **parse failure** is recorded as `errored-permanent` (**not retried** on re-runs, surfaced for inspection) — so re-runs neither lose recoverable documents nor loop forever on unfixable ones.
- **FR-012**: System MUST wrap modelserver calls with **exponential-backoff retries** (transient 5xx / timeout) and MUST NOT retry 4xx, consistent with the platform's external-call policy.
- **FR-013**: System MUST be **resumable**: an interrupted build MUST, on re-run, index only the documents that did not complete, never leaving a duplicate or partial chunk set for a document already marked indexed.
- **FR-014**: System MUST enforce **multi-tenant isolation**: every chunk carries `client_id`, all chunk reads/writes are client-scoped, and one client's chunk MUST NEVER be returned in another client's index context (constitution Principle V).
- **FR-015**: System MUST store, per chunk, **both** a dense embedding (vector similarity) and a lexical full-text search vector, and MUST create the indexes needed for efficient client-scoped hybrid query (at minimum: client scope, document link, chunk type, the vector index, and the full-text index). The `drug` **index is deferred to spec 8** (the column is null in v1 per FR-023, so indexing it now would serve no query). Apart from the drug index, spec 7 retrieval MUST require no schema rework.
- **FR-016**: System MUST fix the stored embedding dimension at **768** to match the embedder; a chunk whose embedding does not match the expected dimension MUST surface as an error and MUST NOT be persisted with a mismatched vector.
- **FR-017**: System MUST provide a way to **initiate the index build for a client** on demand (a **manual trigger endpoint**, e.g. `POST /clients/{id}/index`), executed in the background, mirroring spec 4's manual-trigger + in-process background pattern. Ingestion MUST NOT auto-chain into indexing in this spec, and there is no automatic post-ingestion trigger; the scheduled/cron cadence and the ingest→index→triage cycle wiring remain spec 11.
- **FR-018**: System MUST **not**, in this spec, perform retrieval, reranking, multi-source corroboration aggregation, classification/triage, or report drafting; its responsibility ends at producing durable, searchable chunks. (Retrieval/corroboration = spec 7; triage = spec 8; drafting = spec 9.)
- **FR-019**: System MUST keep logs and traces **PII-free**: no patient attributes (e.g., FAERS age/sex/country) and no secrets in any log line emitted during parsing/embedding. Active **Presidio redaction** of stored chunk text before consumption is owned by **spec 12**; this spec stores chunk text faithfully and logs without PII.
- **FR-020**: System MUST respect the **inactive-data lifecycle**: deactivating a watchlist or suspending a client MUST stop new indexing for it while preserving already-stored chunks; no destructive deletion of chunks occurs in this spec. Chunks MUST be deletable together with their parent document (cascade) so later right-to-erasure can purge them.
- **FR-021**: System MUST introduce the new stores via a single new **database migration** that enables the vector capability (pgvector) and creates the **chunk table**, the **`document_index_state` table**, the **index-build-run record table**, and their indexes — without altering any spec-4 table — with a working reversible downgrade.
- **FR-022**: System MUST treat a stored document as **immutable** for indexing purposes in v1: if a document's raw payload later changes, re-embedding on content change is **out of scope** (documented assumption); indexing keys off whether the document has been indexed, not on content versioning.
- **FR-023**: System MUST NOT attempt per-chunk **drug attribution** in v1: the `drug` field is left null. Provenance (the matching watchlist) identifies only the watchlist's whole drug set, not which drug a given chunk concerns, so storing it would imply false precision. Accurate per-chunk drug tagging (scispaCy NER / RxNorm) is owned by spec 8; spec 7 MAY derive candidate drugs from the document↔watchlist link at query time if it needs a coarse filter.
- **FR-024**: When a document was **deduplicated across multiple sources** (it has several `document_sources` payloads), the system MUST parse only **one representative payload** — the **highest-reliability** source (`regulatory_alert` > `peer_reviewed` > `preprint` > `case_report`), tie-broken by **richest content** (full text over abstract) then most-recent — and MUST NOT merge chunks across a document's sources. One paper therefore yields exactly one chunk set, preserving the one-paper-one-voice guarantee behind FR-009 and downstream corroboration counts.
- **FR-025**: The system MUST compute chunk token counts with the **embedder's own tokenizer artifact** (the same tokenizer the modelserver embedder uses), and MUST **verify that tokenizer's version against the embedder model version at startup**, refusing to proceed on mismatch — consistent with the platform's model-artifact SHA validation. This guarantees chunk boundaries match the embedder's true tokenization (see FR-008) so that no medical text is silently truncated (a grounding-integrity safeguard, Constitution II).
- **FR-026**: The system MUST allow **at most one in-progress index build per client**: a trigger received while a build is active MUST be a **no-op that returns the in-flight run** rather than starting a second concurrent build. Chunk persistence MUST additionally be **idempotent per document** (a re-attempt for the same document cannot create duplicate chunks) as defense-in-depth against races.
- **FR-027**: The index-build **trigger endpoint MUST require a staff `manager` or `admin`**, scoped through the `acting_client(client_id)` dependency so the target client is server-validated and audit-attributed; staff `reviewer`s and client-users MUST NOT be able to trigger an index build (Constitution V internal-operator compensating controls).
- **FR-028**: For each document, the system MUST commit the document's **chunks and its index-state transition to `indexed` in a single transaction**, so an interruption can never leave a document marked `indexed` with a partial chunk set — protecting the resumability guarantee in FR-013.

### Key Entities *(include if feature involves data)*

- **Chunk**: A typed, section-tagged fragment of a single document's text, the atomic unit of retrieval. Belongs to exactly one **client** (tenant scope) and one **document** (cascade-linked). Carries: chunk text; `chunk_type` ∈ {text, table, figure_caption, structured_data}; section label; a nullable `drug` field (unpopulated in v1 — see FR-023) and date where derivable; inherited `source_reliability`; a 768-dimension dense embedding; a lexical full-text search vector; the **embedder model version** that produced it; and an ordering position within its document. New in this spec.
- **Document index state**: A 1:1 per-document indicator of indexing progress (`not-indexed` / `indexed` / `indexed-empty` / `errored-transient` / `errored-permanent`) plus the embedder model version used and last error cause/attempt info, enabling idempotent, incremental, resumable, cause-aware builds (FR-010, FR-011). Stored in a **dedicated `document_index_state` table owned by this spec** (the spec-4 `documents` table is not altered); it answers "has this document been turned into chunks, with which embedder, and if not why". New in this spec.
- **Index build run**: A record of one index-build invocation for a client, capturing counts (documents processed, chunks created, documents skipped/errored) and outcome, for observability and resumability. A dedicated table paralleling spec 4's ingestion-run record pattern. New in this spec.
- **Parser router**: The dispatch component (not stored data) that maps a document's source type to the correct parser; conceptually central to FR-001 and the unit each source parser plugs into.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After an index build, **100%** of a client's stored, parseable documents have at least one embedded chunk available for search; unparseable documents are accounted for as errored (none silently lost).
- **SC-002**: A cross-client read of the index returns **0** chunks belonging to another client — client-to-client isolation is absolute.
- **SC-003**: Re-running the index build over an unchanged corpus creates **0** new chunks and makes **0** embedding calls (full idempotency); adding one new document causes exactly that one document to be parsed and embedded.
- **SC-004**: With one unparseable document in a batch, the run still completes and indexes **all remaining** documents, reporting accurate per-document skipped/errored counts (a single bad document never aborts the run).
- **SC-005**: For each of the seven source types, parsing a representative fixture yields chunks of the correct `chunk_type`; tables are never split mid-row and figure captions are preserved as discrete chunks (verified on a fixture set).
- **SC-006**: **100%** of stored chunks carry a recorded embedder model version and a 768-value embedding; no chunk is persisted with a mismatched embedding dimension.
- **SC-007**: Across an index build that processes de-identified FAERS attributes, **0** patient attributes and **0** secrets appear in any emitted log line.
- **SC-008**: Each stored chunk carries both a dense embedding and a non-empty lexical search vector, and the indexes required for client-scoped hybrid retrieval exist, so spec 7 can run hybrid search with no schema change.
- **SC-009**: A typical post-ingestion batch of documents for a client is fully indexed and made searchable within minutes of the build being triggered (supporting the platform's minutes-not-days promise), with the embedding step bounded by the documented batch size. *(Qualitative target, not a hard threshold.)*
- **SC-010**: Across a full index build, the number of modelserver **truncation events is 0** — chunk boundaries respect the embedder's own tokenizer (no medical text is silently dropped).
- **SC-011**: Triggering an index build **twice in quick succession** for one client results in exactly **one** executed build and **0** duplicate chunks.
- **SC-012**: After a transient embedder outage, **re-running** the build indexes the previously `errored-transient` documents (**0** recoverable documents permanently lost), while a document with an unparseable payload is marked `errored-permanent` and is **not** retried.
- **SC-013**: A non-`manager`/`admin` caller (staff `reviewer` or any client-user) attempting to trigger an index build is refused (**0** unauthorized builds executed).

## Assumptions

- **Trigger model mirrors spec 4** (clarified 2026-06-10): Index build is initiated only by an on-demand manual trigger endpoint and runs in-process in the background; ingestion does not auto-chain into it, and the scheduled/cron cadence plus ingest→index→triage cycle wiring are deferred to spec 11. (FR-017)
- **Redaction is spec 12**: Active Presidio PII/secret redaction of stored chunk text before downstream consumption is owned by spec 12, which interposes before the corpus is consumed; this spec stores chunk text faithfully and keeps PII out of logs, consistent with spec 4's stance. Retained FAERS payloads contain only de-identified attributes (age/sex/country), not direct identifiers.
- **Documents are immutable for indexing**: v1 keys idempotency off "has this document been indexed," not content versioning; re-embedding on a changed payload is out of scope (FR-022).
- **Embedder contract is fixed by spec 5**: 768-dimension, L2-normalized vectors, batch ≤128, 512-token truncation safety net, per-result model-version stamp, accessed via the existing `ModelserverClient` (chunked helpers handle the ≤128 batching). This spec additionally loads the embedder's **tokenizer artifact** to count tokens exactly (FR-025); the modelserver's truncation is a backstop/alarm, never the chunking strategy.
- **Chunking parameters are locked** (clarified 2026-06-10): section-aware splitting, target ~256 tokens per chunk, ~15% overlap, hard cap below 512 tokens; structural chunks (whole table / figure caption) are not overlapped. (FR-008)
- **PDF parsing is a stretch goal**: out of scope for v1 unless time permits; the parser router is designed to accept it later (consistent with the brief marking PyMuPDF as stretch).
- **Query-embedding cache is spec 7**: the Redis cache for query embeddings is a retrieval-side concern (spec 7), not part of index build.
- **No cross-client chunk sharing**: chunks are stored per client (mirroring spec 4's per-client document storage); a shared-embedding junction table is a documented future improvement, deferred until isolation guarantees are proven.

## Dependencies

- **Spec 4 (literature-ingestion)** — provides the `documents` records and the retained per-source `raw_payload` this spec parses; provides `source_reliability` tiers inherited by chunks.
- **Spec 5 (modelserver)** — provides the medical ONNX embedder and the `app/infra/modelserver_client.py` async caller (with chunked helpers). Only `modelserver_token` exists as a `Settings` field; the base URL is resolved by `ModelserverClient.from_settings()` from a built-in default (`modelserver_url` is **not** a `Settings` field and must not be referenced directly or added to `_REQUIRED_SECRETS`).
- **pgvector** — the vector capability must be enabled in the database (new migration) for dense embedding storage and similarity search.
- **Spec 7 (retrieval)** — the consumer of this spec's output; this spec must leave the index hybrid-retrieval-ready (FR-015) so spec 7 needs no schema rework.
- **Spec 12 (security hardening)** — owns Presidio redaction layered before corpus consumption (FR-019) and right-to-erasure of vectors.

## Out of Scope

- Hybrid retrieval, reranking, multi-source corroboration aggregation, citation extraction (spec 7).
- Classification / triage / severity bucketing (spec 8) and report drafting (spec 9).
- Active Presidio PII/secret redaction of stored chunk text (spec 12) and right-to-erasure of vectors (later spec).
- Scheduled/cron index-build cadence (spec 11).
- Query-embedding caching (spec 7).
- Re-indexing the existing corpus after an **embedder-version upgrade** (a re-embed campaign): the dedicated `document_index_state` table makes it possible later, but no v1 trigger performs it — idempotency keys off whether a document has been indexed, not which embedder version produced it (FR-022).
- PDF parsing (stretch), drug entity disambiguation / RxNorm normalization, contextual retrieval, and shared cross-client chunk embeddings (documented future improvements).
- Any frontend surface (document/index browsing UI) — this spec is backend/API only.
