# Contract: `ModelserverClient.rerank()` / `rerank_chunked()`

Additions to `app/infra/modelserver_client.py`. Mirror the existing `classify`/`embed` methods exactly
(httpx via the shared factory, `X-Service-Token` header, tenacity retry on 5xx/timeout, **never** on
4xx).

## Methods

```python
async def rerank(self, query: str, passages: list[str]) -> list[dict]:
    """POST /rerank; returns result dicts in input order. Empty passages → []."""

async def rerank_chunked(self, query: str, passages: list[str]) -> list[dict]:
    """Split passages into ≤128 batches (same query each), concatenate results in order."""
```

- Returns `resp["results"]` — each `{ "score": float, "model_version": {"name","version","sha256"} }`.
- `rerank([], …)` / empty passages → `[]` (no HTTP call).
- Uses the existing `_post_with_retry` → on non-2xx after retries raises `ModelserverError`
  (surfaced by the route as `502`); on 4xx no retry.
- Must be used inside `async with ModelserverClient.from_settings(settings) as c:` (the client asserts
  `_http` is set), exactly like the Spec-6 runner.

## Caller usage (in `app/rag/service.py`)

1. Build candidate passages = `[c.text for c in fused_candidates]`.
2. `scores = await client.rerank_chunked(query, passages)` (one call; ≤ 50 fused candidates → one batch).
3. Zip scores back to candidates **by index** (input order preserved), sort by `score` desc with
   `chunk.id` tie-break, take `top_k`.
4. `embedder_version` for the FR-004 check comes from the embedder stamp, not the reranker stamp.

## Testability seam (required for the in-process CI eval — C1)

CI runs only `vault postgres redis` (no modelserver container), so the integration/eval tests drive the
modelserver **ASGI app in-process**. Add a minimal, production-safe seam to `ModelserverClient`:

- Extend `__init__` with `transport: httpx.BaseTransport | None = None`; in `__aenter__`, if `transport`
  is set, build the httpx client with `httpx.AsyncClient(transport=transport, base_url=self._base_url)`
  instead of `build_http_client()` (production passes `None` → unchanged networking).
- Tests construct: `from modelserver.main import create_app; ms_app = create_app()` (set env
  `MODELSERVER_TOKEN` so its lifespan boots; `MODEL_DIR` defaults to `modelserver/models`), then
  `ModelserverClient(base_url="http://modelserver", token=<same token>, transport=httpx.ASGITransport(app=ms_app))`.
  The modelserver app must be entered via its lifespan (use `httpx.ASGITransport` with lifespan or
  `LifespanManager`) so artifacts load and `app.state.ready` is `True`.
- Guard these tests with `skipif(find_spec("onnxruntime") is None)` (Spec-6 pattern).
</content>
