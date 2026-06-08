"""MHRA adapter: drug safety update feed → regulatory_alert RawRecord (sequenced last)."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from app.infra.http import build_http_client, get_source_semaphore, with_retry
from app.ingestion.adapters import ENABLED_ADAPTERS, RawRecord, WatchlistQuery
from app.ingestion.enums import SourceName, SourceReliability

_log = structlog.get_logger(__name__)
_SEARCH_URL = "https://www.gov.uk/drug-safety-update.json"


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse YYYY-MM-DD date from MHRA; return None on failure."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(date_str[:10], fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _parse_response(data: dict) -> list[RawRecord]:
    """Parse MHRA drug safety update JSON response into regulatory_alert RawRecords."""
    results = data.get("results", [])
    records: list[RawRecord] = []
    for item in results:
        ext_id = item.get("id", "").strip()
        if not ext_id:
            continue
        title = item.get("title", "").strip() or None
        url = item.get("url", "").strip() or None
        published_at = _parse_date(item.get("publishedDate"))
        records.append(
            RawRecord(
                source=SourceName.MHRA,
                source_external_id=ext_id,
                title=title,
                published_at=published_at,
                origin_url=url,
                raw_payload={
                    "id": ext_id,
                    "title": title,
                    "publishedDate": item.get("publishedDate"),
                },
            )
        )
    return records


class MHRAAdapter:
    """MHRA drug safety update adapter (regulatory_alert tier, sequenced last)."""

    name = SourceName.MHRA
    reliability = SourceReliability.REGULATORY_ALERT

    def __init__(self) -> None:
        self._semaphore = get_source_semaphore(SourceName.MHRA.value)

    async def fetch(
        self,
        query: WatchlistQuery,
        since: datetime | None,
        cap: int,
    ) -> list[RawRecord]:
        """Fetch MHRA drug safety updates matching the query."""
        async with self._semaphore:
            return await self._fetch(query, since, cap)

    async def _fetch(
        self, query: WatchlistQuery, since: datetime | None, cap: int
    ) -> list[RawRecord]:
        terms = query.drugs + query.keywords
        if not terms:
            return []

        @with_retry
        async def _get(client, params):
            resp = await client.get(_SEARCH_URL, params=params)
            if resp.status_code == 404:
                return {"results": []}
            resp.raise_for_status()
            return resp.json()

        all_records: list[RawRecord] = []
        async with build_http_client() as http:
            for term in terms[:5]:
                params: dict = {"keywords": term, "count": str(cap)}
                data = await _get(http, params)
                all_records.extend(_parse_response(data))

        if since:
            all_records = [
                r for r in all_records if r.published_at is None or r.published_at >= since
            ]

        seen: set[str] = set()
        deduped: list[RawRecord] = []
        for r in all_records:
            if r.source_external_id not in seen:
                seen.add(r.source_external_id)
                deduped.append(r)

        return deduped[:cap]


# Sequenced last per spec schedule-risk plan.
ENABLED_ADAPTERS.append(MHRAAdapter())
