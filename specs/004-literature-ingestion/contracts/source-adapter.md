# Contract: Source Adapter (internal interface)

**Feature**: 004-literature-ingestion. This is the **internal** contract every source adapter
implements so `runner.run_ingestion()` can treat all six sources uniformly (FR-003). It is not an
HTTP API. Defined in `app/ingestion/adapters/__init__.py`.

## `RawRecord` (normalized adapter output)

A frozen dataclass — the common shape an adapter produces per external record (FR-004). The runner,
not the adapter, computes the normalized dedup id and persists.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `source` | `SourceName` | yes | which adapter produced it |
| `source_external_id` | `str` | yes | id as the source reports it (raw PMID / PMCID / alert id) |
| `doi` | `str \| None` | no | when the source exposes one (feeds id precedence, D4) |
| `pmid` | `str \| None` | no | when available |
| `title` | `str \| None` | no | optional |
| `summary` | `str \| None` | no | abstract/summary if present |
| `published_at` | `datetime \| None` | no | publication/alert date (drives watermark, D9) |
| `origin_url` | `str \| None` | no | |
| `raw_payload` | `dict` | yes | faithful raw record (JSON-serializable) for spec-6 parsing |

A record from which the runner can derive **no** identifier (no doi/pmid and no
`source_external_id`) is counted as **errored**, never stored (FR-006/FR-014).

## `SourceAdapter` (Protocol)

```python
class SourceAdapter(Protocol):
    name: SourceName
    reliability: SourceReliability  # this source's tier (FR-005)

    async def fetch(
        self,
        query: WatchlistQuery,     # drugs / keywords / valid-mesh terms for the run
        since: datetime | None,    # watermark; None ⇒ caller passes the initial-lookback start
        cap: int,                  # per-source result cap (D9)
    ) -> list[RawRecord]: ...
```

**Obligations**:
- **Async only**, using the shared `httpx.AsyncClient`; every outbound call wrapped in the shared
  `tenacity` retry helper (3 attempts, exponential backoff, retry timeouts/5xx, **never 4xx**) and
  bounded by a per-source `asyncio.Semaphore` (D6, Constitution).
- Use **only the watchlist fields it understands** (FR-002): MeSH-aware (`pubmed`, `europepmc`) use
  valid MeSH terms (+ drugs/keywords) and rely on **PubMed-native MeSH expansion** (no expansion
  engine here, FR-010); `openfda_*`, `fda_medwatch`, `ema`, `mhra` use drug name + keywords.
- Respect the source's usage limits (politeness/backoff); accept a missing optional API key by
  degrading to keyless limits (D7).
- Return at most `cap` records; **raise** on a hard failure — the runner converts an adapter
  exception into a per-source `failed` outcome with the error captured, **without aborting other
  sources** (FR-012). Returning `[]` is a valid empty success (FR-015).
- **Never** advance any watermark or write to the DB — persistence and dedup are the runner's job.

## `WatchlistQuery`

A small read-only value object the runner builds once per run from the watchlist: `drugs: list[str]`,
`keywords: list[str]`, `mesh_terms: list[str]` (only `valid`/`unvalidated` terms, never `invalid`).

## Registry

`ENABLED_ADAPTERS: list[SourceAdapter]` — the configured sources the runner fans out over
(`asyncio.gather`). EMA/MHRA are added last (schedule-risk sequencing) but, once present, require no
change to `RawRecord`, the runner, or the document shape (FR-003).

## Testing

Each adapter has recorded fixtures under `tests/fixtures/<source>/`; unit tests assert
`fetch()` (with a stubbed HTTP transport) yields the expected `RawRecord`s. The runner is tested
with **fake adapters** implementing this Protocol — no live network (D16).
