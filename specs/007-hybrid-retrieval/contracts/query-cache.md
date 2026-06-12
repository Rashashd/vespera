# Contract: Query-embedding cache + embedder-version safety

Internal contract for `app/rag/query_embed.py`. Provides the query vector for retrieval, served from a
best-effort Redis cache, and enforces the FR-004 version guard.

## `normalize_query(query: str) -> str`

Unicode NFKC → `strip()` → `lower()` → collapse internal whitespace to single spaces. Deterministic.

## Cache key

`rag:qemb:{embedder_sha256}:{sha256_hex(normalize_query(query))}` (D7). The embedder sha256 segment
auto-invalidates the cache on a model upgrade (FR-017) — no stale vector survives a version change.

## `get_query_embedding(redis, client, settings, query) -> (vector, embedder_version)`

1. `key = cache_key(embedder_sha, query)`.
2. **GET** `key` → on hit: JSON-decode to `list[float]` (768), return it (no embed call). On any Redis
   exception: log `rag.cache.unavailable` (warning) and continue (FR-018).
3. On miss: `result = await client.embed([query])` → `vector = result[0]["embedding"]`,
   `embedder_sha = result[0]["model_version"]["sha256"]`.
4. **SET** `key` `json(vector)` `EX settings.query_embedding_cache_ttl` (best-effort; failure ignored).
5. Return `(vector, embedder_sha)`.

The current `embedder_sha` comes from the `/embed` result's `model_version.sha256` (**NOT** a `/ready`
call). It is **memoized on `app.state.embedder_sha`** after the first embed, optionally seeded from the
OPTIONAL, empty-by-default `settings.embedder_model_version` pin (declared in `Settings` but not loaded
in `startup.py`). On a cold memo the first query skips the cache lookup, embeds, then memoizes + stores;
subsequent queries build the key from the memoized sha. US1's version guard uses the same embed-result
sha directly. **The api never calls the modelserver at startup.**

## Embedder-version guard — `assert_index_version(session, client_id, embedder_sha) ` (FR-004 / D8)

```sql
SELECT DISTINCT embedder_version FROM chunks WHERE client_id = :cid;
```

- Empty set (no chunks) → OK (caller returns an empty result; not a mismatch).
- Set == `{embedder_sha}` → OK.
- Otherwise → raise `EmbedderVersionMismatch` → route returns **409 `EMBEDDER_VERSION_MISMATCH`**
  ("client index was built with a different embedder version; rebuild required"). Never score against
  incomparable vectors.

## Guarantees

- A cache outage NEVER fails a query (FR-018) — only removes the speed-up.
- No raw query text is logged; only `query_hash` (the sha256 prefix) (FR-023).
- TTL-bounded entries (default 3600 s) prevent unbounded growth (FR-016/017).
</content>
