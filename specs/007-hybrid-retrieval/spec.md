# Feature Specification: Hybrid RAG Retrieval & Multi-Source Corroboration

**Feature Branch**: `007-hybrid-retrieval`

**Created**: 2026-06-11

**Status**: Draft

**Input**: User description: "for spec 7 — read the brief and guide in final-project/project-files/ first, plus memory"

## Overview

Spec 6 built the **index** half of Pantera's RAG pipeline: every ingested document is parsed,
chunked, embedded with the medical sentence transformer, and stored in a per-client, hybrid-ready
chunk index (dense vectors + lexical full-text). This spec builds the **query** half: given a
question — a candidate adverse-event signal, a drug + reaction, a reviewer's lookup — return the most
relevant evidence passages from *one client's* corpus, ranked by combining semantic and lexical
search, reranked for precision, and **grouped by source document so the strength of independent
corroboration is visible**. Each returned passage carries the provenance and a stable anchor needed
to cite it.

This is the retrieval primitive that the later report-drafting and LangGraph agent specs depend on:
grounding ("every claim cites its source passage") and multi-source corroboration ("independently
reported in N sources: …") are only possible if retrieval reliably surfaces the right passages, every
qualifying source, and a way to point at the exact text. No report writing, severity rules, NER drug
tagging, or LLM answer generation happen here — this spec delivers the search-and-corroborate
capability and the eval gate that proves its quality with a number.

## Clarifications

### Session 2026-06-11

- Q: Reranker mechanism — cross-encoder→ONNX on the modelserver, LLM-rerank, or fusion-only? → A: Cross-encoder exported to ONNX, served by the existing modelserver (no-torch, single inference container; adds an offline-trained artifact + a `/rerank` endpoint + its own eval).
- Q: Committed RAG eval thresholds for the CI gate? → A: hit@5 ≥ 0.85, MRR ≥ 0.70, corroboration-count accuracy = 100% on corroboration cases.
- Q: Fusion method — RRF, weighted score blend, or decide in planning? → A: Defer to planning; pick by measuring both legs and the fused ranking on the golden set (spec stays mechanism-agnostic; RRF is the default candidate).
- Q: Which staff roles may call the staff-facing search endpoint? → A: Any authenticated staff with access to the target client — the per-request, server-validated `acting_client` guard with **no `require_admin`** (role breadth comes from omitting the admin gate). A suspended client is still **refused** (US1 scenario 4); this is the suspended-refusing variant, NOT Spec 6's suspended-allowing read variant.
- Q: Behavior when the query embedder version ≠ the chunks' stamped `embedder_version`? → A: Refuse the query with a clear error (fail-fast); the mismatch means the client's index needs a rebuild — never return passages scored against incomparable vectors.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Retrieve grounded evidence passages for a client (Priority: P1)

An analyst (or, later, the report drafter) has a query — e.g., *"hepatotoxicity associated with
DrugX"* — and a specific client. They need the passages from that client's indexed literature that
best answer it, each tied back to its source so any statement built on it can cite a real passage.

**Why this priority**: This is the spine. Without reliable, client-scoped, provenance-carrying
retrieval there is nothing to ground a report on and no corroboration to count. Every later RAG
capability is an enhancement on top of this. It is also the minimum that delivers value: an analyst
can already search a client's corpus and open the exact cited passages.

**Independent Test**: Seed one client's chunk index with documents covering a known topic, run a
query, and confirm the most relevant passages are returned — each with its source document, section,
reliability, and a resolvable anchor to the exact text — and that nothing from any other client
appears.

**Acceptance Scenarios**:

1. **Given** a client whose corpus contains passages about a drug/reaction, **When** an authorized
   staff user queries that client for the reaction, **Then** the system returns a bounded, ranked
   list of the most relevant passages, each with source title, source name, external id, publication
   date, source reliability, chunk type, section, and an anchor identifying the exact chunk.
2. **Given** two clients whose corpora both mention the same public drug, **When** a query runs for
   client A, **Then** every returned passage belongs to client A and none belongs to client B.
3. **Given** a client with no indexed chunks, **When** a query runs, **Then** the system returns an
   empty result set with corroboration count 0 and no error.
4. **Given** a suspended client, **When** a query is attempted for it, **Then** the request is
   refused (consistent with the index-trigger lifecycle), not served.

---

### User Story 2 - Hybrid retrieval finds what either method alone would miss (Priority: P2)

A reaction may be described in paraphrase (semantic match) or named by an exact term, drug code, or
rare abbreviation (lexical match). The analyst needs both kinds of evidence found in one ranked list.

**Why this priority**: This is Pantera's "one justified RAG improvement" (Brief §5-D). Dense search
alone misses exact rare tokens; lexical alone misses paraphrase. Fusing them is what makes retrieval
trustworthy for safety signals — and it must be *proven* to beat a single-method baseline with a
golden-set number, not asserted.

**Independent Test**: On the golden set, run dense-only, lexical-only, and fused retrieval; confirm
the fused ranking meets or beats the better single leg on hit@k and MRR; confirm a query that matches
only lexically (an exact rare term) and one that matches only semantically (paraphrase) both surface
the correct passage in the fused list.

**Acceptance Scenarios**:

1. **Given** a passage that matches a query only by an exact rare term, **When** the query runs,
   **Then** the fused result includes that passage even though dense search ranks it poorly.
2. **Given** a passage that matches a query only semantically (no shared keywords), **When** the
   query runs, **Then** the fused result includes that passage even though lexical search misses it.
3. **Given** the RAG golden set, **When** fused retrieval is scored, **Then** hit@k and MRR meet or
   exceed the dense-only baseline and the committed thresholds.

---

### User Story 3 - Multi-source corroboration is surfaced (Priority: P2)

When the same adverse event is reported by several independent papers, the analyst must see *all* of
them and how many there are — corroboration count is itself a safety signal, not a retrieval detail.

**Why this priority**: This is a constitutional requirement (Principle II) and a headline product
differentiator (Brief §3b, §6). Retrieval that returns only the single top hit would hide
corroborating evidence. It builds directly on US1 and is required before any report can state
"independently reported in N sources."

**Independent Test**: Seed a client with N distinct source documents that each report the same event,
run a query for that event, and confirm the result reports corroboration count = N and lists all N
sources with citation metadata — never a truncated subset.

**Acceptance Scenarios**:

1. **Given** N distinct source documents in a client's corpus that each describe the same adverse
   event, **When** a query for that event runs, **Then** the result groups passages by source
   document, reports a corroboration count of N, and lists all N sources (title, source, external id,
   date, reliability).
2. **Given** a single source document that contributes several passages to the result, **When**
   corroboration is computed, **Then** that document counts as exactly one source.
3. **Given** a corroboration result, **When** it is returned, **Then** every qualifying source is
   present — the list is never truncated to hide corroborating sources.

---

### User Story 4 - Reranking sharpens the top results (Priority: P3)

After fusion the analyst should see the *most* relevant passages first, so the top-K handed to a
reviewer or report drafter is precise.

**Why this priority**: Reranking measurably improves precision@k / MRR over fusion alone, but the
system is already usable without it (US1+US2 deliver ranked, fused results). It is an enhancement
proven by a number, with a documented fallback path.

**Independent Test**: On the golden set, compare fused-only vs fused+reranked ordering; confirm the
reranked top-K meets or exceeds fused-only on precision@k / MRR and the committed thresholds.

**Acceptance Scenarios**:

1. **Given** a fused candidate list, **When** reranking is applied, **Then** the returned top-K is
   reordered to put the most relevant passages first and the ordering is deterministic for a given
   corpus and query.
2. **Given** the golden set, **When** reranked retrieval is scored, **Then** precision@k / MRR meet
   or exceed fused-only and the committed thresholds.

---

### User Story 5 - Repeated queries are fast and cheap (Priority: P3)

Frequent or repeated lookups (the same drug/reaction queried across a cycle, a reviewer re-opening a
report) should not pay the embedding cost twice.

**Why this priority**: A latency/cost optimization, not a correctness requirement. Retrieval is
correct without it; the cache only makes repeated queries faster and reduces modelserver load.

**Independent Test**: Run the same query twice; confirm the second run serves the query embedding from
cache without a second embedder call; confirm that with the cache disabled or unavailable the query
still succeeds via a live embed.

**Acceptance Scenarios**:

1. **Given** a query that was run before, **When** it is run again with the same embedder version,
   **Then** its embedding is served from cache and the embedder is not called again.
2. **Given** the cache is unavailable, **When** a query runs, **Then** it still succeeds by embedding
   live (the cache is best-effort, never a hard dependency).
3. **Given** the embedder version has changed, **When** a previously cached query runs, **Then** the
   stale cached embedding is not used.

---

### Edge Cases

- **Embedder version mismatch**: the embedder version used to vectorize the query differs from the
  `embedder_version` stamped on the client's chunks → dense scores would be meaningless; the system
  MUST detect this and **refuse the query with a clear error** (index needs rebuild), never return
  silently-wrong results.
- **Modelserver unavailable / slow**: the embed call times out or errors → bounded timeout + retry;
  on exhaustion the query fails cleanly with a clear error, never hangs.
- **Redis cache down**: query embedding cache miss or outage → fall back to live embed; never fail.
- **Empty corpus / no matches**: return empty results, corroboration count 0, no error.
- **Fusion ties**: passages with identical fused rank → deterministic tie-break so eval numbers and
  cited orderings are reproducible.
- **Over-long query**: the embedder truncates beyond its token limit (a safety net inherited from the
  modelserver), recorded as a warning, not a failure.
- **Same paper from multiple sources**: Spec 6 indexed a single chosen payload per document, so one
  paper is one document → it counts once toward corroboration even if originally seen on several feeds.
- **Two clients, same public paper**: each client holds its own chunk rows (per-client embedding from
  Spec 6); retrieval stays strictly within the queried client.
- **Unknown / nonexistent client**: rejected by authorization, not served.

## Requirements *(mandatory)*

### Functional Requirements

**Core retrieval**

- **FR-001**: System MUST accept a natural-language query for a single named client and return a
  bounded, ranked list of the most relevant chunks from that client's indexed corpus.
- **FR-002**: Every retrieval MUST be scoped to exactly one client. Results MUST NEVER include chunks
  belonging to any other client, under any query or filter (Principle V — client-to-client isolation
  is absolute).
- **FR-003**: System MUST embed the query with the SAME medical embedder (the modelserver embed
  service) used to build the index, so query and chunk vectors are comparable.
- **FR-004**: System MUST verify that the embedder version used for the query matches the
  `embedder_version` stamped on the client's chunks. On mismatch the query MUST be **refused with a
  clear error** (fail-fast — the index needs a rebuild); the system MUST NEVER return passages scored
  against incomparable vectors.
- **FR-005**: System MUST perform dense semantic retrieval over the chunk vector index using cosine
  similarity on the L2-normalized 768-dim embeddings.
- **FR-006**: System MUST perform lexical retrieval over the stored chunk full-text index so exact
  terms (drug names, reaction terms, codes, rare abbreviations) match even when semantically diffuse.
- **FR-007**: System MUST fuse the dense and lexical result lists into a single ranking such that a
  passage strong in either leg can surface (hybrid retrieval).
- **FR-008**: System MUST rerank the fused top candidates to improve the precision of the final
  returned top-K, using a **cross-encoder exported to ONNX and served by the existing modelserver**
  (no separate reranker service; no torch in any serving container — Principle VI). The reranker
  artifact MUST be SHA-256-validated at modelserver startup like the other model artifacts.
- **FR-009**: The number of returned results (top-K) MUST be bounded with a sane default and be
  configurable per query within safe limits.
- **FR-010**: Fusion and reranking MUST be deterministic for a given corpus and query (stable
  tie-breaking), so eval numbers are reproducible and a cited passage is reproducibly retrievable.

**Provenance & anchoring (grounding substrate)**

- **FR-011**: Each returned result MUST carry its source provenance: source document title, source
  name, external id, publication date, `source_reliability`, `chunk_type`, and `section`.
- **FR-012**: Each returned result MUST carry a stable passage anchor (identifying the exact chunk and
  its position in its document) so a downstream report or reviewer UI can display and deep-link to the
  exact retrieved passage.

**Multi-source corroboration**

- **FR-013**: System MUST group retrieved passages by distinct source document; multiple passages from
  one document MUST count as a single source.
- **FR-014**: For a query, System MUST report a corroboration count equal to the number of distinct
  source documents in the result set, and MUST list every one of them with citation metadata
  (title, source, external id, date, reliability).
- **FR-015**: The corroboration source list MUST include ALL qualifying sources — it MUST NEVER be
  truncated in a way that hides corroborating evidence from the reviewer/drafter (Principle II).

**Query embedding cache**

- **FR-016**: System MUST cache query embeddings keyed by the normalized query text and the embedder
  version, so repeated queries avoid re-embedding.
- **FR-017**: Cached query embeddings MUST expire after a bounded time-to-live and MUST NOT be used
  when the embedder version differs from the one that produced them.
- **FR-018**: A cache miss or cache outage MUST NOT fail a query — the system MUST fall back to a live
  embed call. The cache is best-effort, never a hard dependency.

**Filtering**

- **FR-019**: System MUST support optional filters that constrain candidate passages on indexed
  attributes (chunk type, source reliability, publication-date range). Drug-entity filtering is OUT OF
  SCOPE for v1 because chunk drug tagging is not yet populated (deferred to the NER spec).

**Surface & authorization**

- **FR-020**: System MUST expose retrieval both as a reusable internal capability — the `retrieve()`
  function in `app/rag/service.py`, to be consumed by the later report-drafting and agent specs — and as
  a staff-facing HTTP endpoint `POST /clients/{client_id}/search` for a named target client.
  **Naming convention (fixed):** the HTTP path is `/search`; the internal capability and its Pydantic
  models are `retrieve()` / `RetrieveRequest` / `RetrieveResponse` — the endpoint is a thin wrapper over
  the capability (no behavioral difference).
- **FR-021**: Retrieval MUST require authorization for the named target client, recomputed from stored
  state on every request (Principle V control b). The staff-facing search endpoint is open to **any
  authenticated staff user with access to the target client** — the per-request, server-validated
  `acting_client` guard with **no `require_admin`** — but a **suspended client is refused** (the
  suspended-refusing variant, not Spec 6's suspended-allowing read variant). The action MUST be
  attributable to the staff actor and the target client; attribution is satisfied by `acting_client` +
  `client_id`-bound structured logging — this spec emits **no read-audit event** (read-access auditing
  is deferred to the report spec). API responses MUST be validated models, never raw stored records.

**Resilience, observability, safety**

- **FR-022**: All external calls (the embed service) MUST use bounded timeouts and exponential-backoff
  retry (max 3 attempts); 4xx responses MUST NOT be retried.
- **FR-023**: Retrieval logging MUST be structured and bind `client_id`, and MUST NOT leak PII or
  secrets — neither query text nor passage text may be logged in a way that exposes patient
  identifiers or pasted secrets (faithful storage with PII-free logs, consistent with the
  redaction-deferral decision from Spec 6).

**Evaluation gate (every decision backed by a number)**

- **FR-024**: A RAG retrieval golden set (~15 query→relevant-document cases, including corroboration
  cases) MUST be committed, with thresholds declared in `eval_thresholds.yaml`: **hit@5 ≥ 0.85,
  MRR ≥ 0.70, and corroboration-count accuracy = 100% on corroboration cases**. CI MUST fail when a
  committed retrieval threshold regresses (Principle IV).
- **FR-025**: The committed retrieval metrics MUST include hit@k and MRR for relevance and
  corroboration-count accuracy. Generation-grounding metrics (faithfulness, answer relevancy) are
  deferred to the grounded-report/agent spec, where LLM answer generation lives.
- **FR-026**: The shipped hybrid (+rerank) pipeline MUST be demonstrated on the golden set to meet or
  beat a dense-only baseline, defended with the comparison numbers (the "justified improvement").

### Key Entities *(include if feature involves data)*

- **Retrieval Query**: the request — query text, target client, optional filters (chunk type / source
  reliability / date range), and requested top-K. Validated at the boundary.
- **Retrieved Passage (result item)**: one chunk surfaced for a query, with its relevance score, final
  rank, source provenance (FR-011), and passage anchor (FR-012). Read-only projection of an existing
  Spec-6 `chunks` row plus its parent `documents` metadata — no new stored entity.
- **Corroboration Group**: the set of distinct source documents represented in a query's result, with
  the corroboration count and the per-source citation metadata (FR-013–FR-015). A computed view, not
  stored.
- **Query Embedding Cache Entry**: a transient mapping from (normalized query text + embedder version)
  to a query vector, with a bounded TTL. Lives in Redis; not durable.
- **RAG Golden Set**: committed evaluation fixtures — query → expected relevant documents (and
  expected corroboration counts) — used by the CI eval gate.
- **Consumed (unchanged) entities**: `chunks` (dense + lexical index, `embedder_version`,
  `source_reliability`, `chunk_type`, `section`), `documents` (title, source, external id, published
  date), `clients` (scope, suspended state) — all from Specs 4/6. This spec adds NO schema change to
  them.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the RAG golden set the shipped pipeline meets the committed retrieval thresholds —
  **hit@5 ≥ 0.85 and MRR ≥ 0.70** (committed in `eval_thresholds.yaml`); any regression below a
  committed value blocks merge.
- **SC-002**: Hybrid retrieval meets or beats dense-only retrieval on hit@5 and MRR on the golden set
  — the improvement is proven by the committed comparison numbers, not asserted.
- **SC-003**: For every golden-set corroboration case where N distinct sources report the same event,
  the result reports corroboration count = N and lists all N sources — corroboration-count accuracy is
  100% on those cases.
- **SC-004**: Across the isolation test suite, 100% of retrieval results belong to the queried client
  — zero cross-client leakage.
- **SC-005**: A repeated identical query (same embedder version) is served from the embedding cache
  with no second embedder call, while a cache outage still yields a correct result via live embed.
- **SC-006**: Median retrieval latency for a representative client corpus is under 1 second for the
  default top-K on a warm cache — an **observed target** (measured via the per-stage latency logs from
  FR-023's structured logging and spot-checked in quickstart), **not a CI-gated threshold** (consistent
  with the project's no-hard-latency-gate precedent).
- **SC-007**: A query against an empty corpus returns an empty result set with corroboration count 0
  and no error.
- **SC-008**: 100% of returned passages include a resolvable anchor to their exact source passage and
  complete citation metadata, so a reviewer can open every cited source.

## Assumptions

- **Substrate is reused, not rebuilt.** Retrieval reads Spec 6's existing `chunks` index (dense vector
  index for semantic search + full-text index for lexical search, both already created in migration
  0006). This spec is expected to require **no new migration**; it adds an eval golden-set fixture, an
  eval runner, and an `eval_thresholds.yaml` entry. Any incidental index tuning, if needed, is a
  planning decision.
- **Fusion method** (Clarified — deferred to planning): the exact fusion is decided in planning by
  measuring dense-only, lexical-only, and the fused ranking on the golden set; Reciprocal Rank Fusion
  (rank-based, no score normalization) is the default candidate. The spec requires *that* dense and
  lexical are fused and that hybrid beats a single-leg baseline by a number; it stays mechanism-agnostic.
- **Reranker mechanism** (Clarified — decided): a **cross-encoder exported to ONNX and served by the
  existing modelserver** (no-torch serving constraint, single inference container, no external-API
  dependency). This adds an offline-trained reranker artifact (notebook → ONNX), a modelserver
  `/rerank` endpoint, and SHA-256 startup validation of the new artifact. **No separate reranker
  service is introduced** (Constitution VI).
- **Query embedding cache** is Redis, keyed by normalized query text + embedder version, with a bounded
  TTL, and is strictly best-effort.
- **Eval thresholds** (Clarified — committed): hit@5 ≥ 0.85, MRR ≥ 0.70, corroboration-count
  accuracy = 100% on corroboration cases, declared in `eval_thresholds.yaml`. Faithfulness and
  answer-relevancy require generated answers and are deferred to the grounded-report/agent spec.
- **Drug filtering deferred.** `chunks.drug` is NULL until the NER spec (Spec 8), so drug-entity
  filtering is out of scope; filtering is supported on chunk type, source reliability, and date.
- **Read-access auditing deferred.** Per the Spec-4b backlog, logging *who viewed which client's data*
  is folded into the report spec. This spec requires server-validated acting-client authorization
  recomputed per request, but does not itself emit a read-audit domain event.
- **No report writing here.** Structured report drafting, grounded LLM summarization, severity rules,
  the LangGraph `retrieve` tool wrapper, and HITL are downstream specs that *consume* this retrieval
  primitive and its corroboration grouping.
- **No NeMo Guardrails dependency here.** The guardrails sidecar and prompt-injection defense on
  ingested-document content are a later security spec. Query text in this spec is internal staff input.
- **Authorization surface mirrors Spec 6** (Clarified — decided): the staff-facing query endpoint uses
  the per-request, server-validated `acting_client` guard with **no `require_admin`** (any staff role
  with access to the target client), and **refuses a suspended client** (the suspended-refusing
  variant — NOT Spec 6's suspended-allowing read variant used for run-status reads).
- **Watchlist deactivation does not hide already-indexed chunks at retrieval** (baked default):
  retrieval is client-scoped, not watchlist-scoped. Deactivating a watchlist stops *future*
  ingestion/indexing of its documents (Spec 6) but does not erase the client's right to its existing
  corpus; those chunks remain retrievable as cross-document context for the same client. A suspended
  *client*, by contrast, cannot be queried at all (FR-002 / US1 scenario 4).
- **Embedder/version contract.** The modelserver embed result already stamps a model-version
  (SHA-256); the chunk rows already persist that as `embedder_version`. Version comparison (FR-004,
  FR-017) uses that existing stamp; no new versioning scheme is introduced.
</content>
</invoke>
