# Contract: Embedder Usage & Version Verification

How the runner consumes the Spec-5 modelserver embedder (FR-005, FR-008, FR-016, FR-025, D6/D7).

## Calling the embedder
- Construct the client **only** via `ModelserverClient.from_settings(settings)` (it resolves the base
  URL from a built-in default — `modelserver_url` is **not** a `Settings` field; only `modelserver_token`
  is). Do **not** reference `settings.modelserver_url` and do **not** add it to `_REQUIRED_SECRETS`.
- Use `ModelserverClient.embed_chunked(texts)` — it splits into ≤128-item batches and preserves input
  order (Spec 5).
- Wrapped in the project's tenacity policy: retry transient 5xx/timeout, **never retry 4xx**
  (FR-012). A 4xx or exhausted retry marks the affected document `errored_transient` for infra/5xx
  /timeout, or surfaces a contract error.
- `embed_chunked` returns a **`list[dict]`** (NOT objects — `modelserver_client.py` returns
  `resp["results"]`), each item shaped `{"embedding": [768 floats, L2-normalized], "model_version":
  {"name", "version", "sha256"}}`. Use **dict access**, not attributes. There is **no** `dim` or
  `max_tokens` on `model_version`. Persist `result["model_version"]["sha256"]` as
  `chunk.embedder_version` (sha256 is 64 chars → exactly `String(64)`).

## Dimension guard (FR-016)
- Assert each returned embedding has length **768**; on mismatch, do **not** persist — raise so the
  document is recorded errored (never corrupt the index).

## Token counting & truncation avoidance (FR-008 / FR-025)
- The **chunker** sizes chunks with the embedder's **own tokenizer** (`tokenizers` lib, loaded from
  `settings.embedder_tokenizer_path`, default `modelserver/models/tokenizer.json`), reserving the
  special-token budget so every chunk is ≤ `max_tokens(512) − reserve`.
- The modelserver truncation path MUST NOT be reached in normal operation; if a truncation warning is
  ever observed it is logged as an **error**, not treated as routine.

## Startup version verification (FR-025)
- Before a build runs, call modelserver `GET /ready`, read `ready_json["models"]["embedder"]["sha256"]`,
  and verify it equals the pinned `settings.embedder_model_version`. **Pin sha256** as the compared
  field (the same sha256 persisted as `chunk.embedder_version`) so the verify, the stamp, and the
  artifact identity are one value. On mismatch → **refuse to run the build** (fail-fast), consistent
  with the platform's model-artifact-validation discipline. The error is surfaced on the run
  (`failed`) and logged.

## Determinism
- The embedder is deterministic (Spec 5); the same chunk text yields the same vector, so re-running a
  build over unchanged documents is a true no-op (FR-009) — and is additionally guarded by skipping
  already-`indexed` documents before any embed call (0 embed calls on a clean re-run, SC-003).
