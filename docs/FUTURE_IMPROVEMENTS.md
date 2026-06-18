# Future Improvements

The MVP (13 spec-kit specs) is complete. This consolidates the enhancements that were
**intentionally scoped out** — the canonical backlog from the project brief (§9), the
"stretch" items from the build guide, and items deferred during implementation. Each notes
where it came from and, where useful, why it was deferred and a rough approach.

> A few items the brief listed as "future" were **delivered** by later specs (client portal,
> full RLS, SFTP delivery, the operator/account-management console) — see the bottom section.

---

## Authentication & access control

- **Real password-reset flow + functional "Remember me".** Today the login shows a
  "Forgot password?" → "contact your administrator" hint; there is no reset router/email, and
  "Remember me" is cosmetic (the JWT TTL is fixed). *Approach:* mount the fastapi-users
  reset/verify routers, add an email provider, build a `/reset-password` page; issue a
  longer-lived token when "remember me" is checked. *(deferred this build)*
- **Refresh tokens** *(spec 4b).* Short-lived access token + long-lived refresh token so staff
  sessions feel continuous while access tokens rotate. v1 uses a single ~8h access token.
- **Client-user sub-roles** *(spec 4b).* Finer roles within a client, beyond the
  severity/watchlist visibility scope.
- **Multiple report recipients per client** *(spec 4b).* Several regular/urgent recipient
  addresses per client rather than one each.
- **Verified-domain allow-listing for report emails** *(spec 4b).* Restrict recipient
  addresses to a client's verified domains (anti-exfiltration hardening).
- **External policy engine (Casbin), conditional** *(spec 4b).* Only if authorization outgrows
  the fixed 4-role model (per-object ACLs, customer-configurable policies, role delegation).
  Until then plain role guards are simpler.

## Signal detection & RAG quality

- **Drug entity disambiguation** *(brief).* scispaCy `en_ner_bc5cdr_md` + RxNorm CUI so
  "Aspirin", "ASA", "acetylsalicylic acid" map to one canonical ID — improves recall,
  precision, and dedup at once. (`canonical_drug_id` is already reserved in the schema.)
- **Finding consolidation / signal deduplication** *(brief).* Cluster findings with the same
  drug + reaction across a cycle into one signal entry rather than separate findings.
- **Global cross-client corroboration / source dedup** *(spec 9).* v1 stores a source once per
  client but duplicates it across clients (to preserve strict client isolation). A global
  layer (likely GraphRAG-based) would store an identical source once across all clients.
- **GraphRAG / LightRAG** *(brief).* Knowledge-graph layer over the corpus for multi-hop,
  cross-document signal detection. LightRAG preferred for incremental updates.
- **Contextual retrieval** *(brief).* LLM-generated context sentence prepended to each chunk
  before embedding, to improve retrieval precision.
- **Comparative context** *(brief).* Inject the previous-cycle signal summary into the batch
  executive summary so reviewers see trend/delta.
- **Citation tracking** *(brief).* Europe PMC forward-citations API — fetch papers recently
  citing a key safety paper.
- **Confidence calibration** *(brief / spec 5).* Platt / temperature scaling in the offline
  training notebook so classifier scores are probabilities.

## Ingestion

- **PDF document parsing** *(guide, stretch).* PyMuPDF text extraction for sources only
  available as PDF; note table-accuracy limitations vs structured XML.
- **Multi-modal figure extraction** *(brief).* Vision LLM for chart images (dose-response
  curves, Kaplan-Meier plots) inside PDFs.

## Reports & delivery

- **Inline numbered citations in the *delivered* report.** The reviewer console already renders
  numbered, clickable `[n]` references → chunk drawer; the delivered artifact and agent prose
  don't yet embed inline markers. *Approach:* have the draft agent emit `[n]` markers tied to
  source order, render them as anchors in `app/delivery/rendering.py`; batch drafts are
  templated, so update consolidation too. *(deferred this build)*
- **PDF report generation + blob storage** *(brief).* Formatted PDF per approved report stored
  in MinIO/S3 with signed URLs. The v1 renderer ships self-contained HTML, structured so an
  HTML→PDF step is a drop-in.
- **E2B(R3) export** *(brief).* International standard format for regulatory-authority
  submission (FDA, EMA, PMDA).
- **Journal/author follow-up form** *(spec 4b).* The follow-up trigger emails an empty
  structured form to the journal/author, which is completed and returned to the client.

## Cost, observability & audit

- **Month-over-month cost history.** The Costs page shows the current billing window only (the
  `/usage` API returns no per-period series). *Approach:* add per-period cost aggregation in the
  backend, then surface trends / the all-months matrix. *(deferred this build)*
- **Signal timeline visualization** *(brief).* Adverse-event frequency chart per drug across
  cycles in the admin console.
- **Admin-configurable budget *warning* threshold** *(spec 3).* The warning level is fixed at
  80% in v1. (The over-budget *policy* — continue / critical-only / pause — is already
  configurable per watchlist.)
- **Cross-client read/access audit log** *(spec 4b).* Log *who viewed which client's data*, not
  just writes — most valuable now that finished reports exist.

## Infrastructure & operations

- **GPU / torch-served models** *(spec 5).* Faster/stronger classifier + embedder when a GPU is
  available; the v1 modelserver is deliberately CPU / no-torch / ONNX, <500 MB.
- **Shared chunk embeddings** *(brief).* A `client_documents` junction table so each paper is
  embedded once regardless of how many clients share the same drug.
- **Production-grade Vault** *(brief).* Upgrade from dev mode to a single-node Vault deployment
  (file storage backend, TLS, AppRole auth); the `hvac` client code does not change.
- **Frontend CI job.** CI runs secret-scan, backend test, and the eval gate but has **no
  frontend job** — the SPA is verified locally only. *Approach:* add a job running
  `npm ci → build → vitest → eslint`. *(found this build)*
- **Git LFS strategy for model artifacts.** ONNX models live in Git LFS; CI re-fetching them
  exhausts the free monthly budget and can break checkout. *Approach:* LFS data pack, or move
  models to release assets / an external store fetched only by the eval job. *(found this build)*
- **GxP validation** *(brief).* IQ/OQ/PQ qualification for regulated pharmacovigilance use.

## Engineering / internal tech debt

- **Rename `app/embedding/` → `app/indexing/`** *(deferred refactor).* The package holds the
  whole parse→chunk→embed→index pipeline, not just embedding; `indexing` pairs cleanly with
  `rag/`. Kept for now because a top-level rename is a wide import-rewrite. Do as an isolated
  mechanical PR if ever.
- **Watch `app/domain/events.py`** *(deferred refactor).* A flat catalog of all domain events;
  cohesive as-is. Split into per-domain modules only when it passes ~400 lines.

## Considered & deliberately not taken (design decisions)

- **Reports two-pane master/detail.** The design prototype showed list + detail side-by-side;
  we chose separate pages so long reports aren't cramped in a half-width pane. A responsive
  two-pane for very wide screens could be revisited.
- **Delivery-status placeholders.** Overview/Dashboard show Sent/Delivered/Failed as `0`
  placeholders until delivery data is real; they light up automatically once it is.

---

## Delivered since the brief was written (no longer "future")

The brief's §9 listed these as future; later specs shipped them:

- **Client portal** + **full Postgres RLS** — specs 10 and 12 (migration 0011).
- **SFTP delivery** — spec 13 (n8n native SFTP node).
- **Operator / account-management console** — the agency console plus spec 13's staff &
  client-user account-creation screens.
