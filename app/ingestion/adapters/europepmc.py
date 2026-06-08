"""Europe PMC REST adapter: JSON search → RawRecord (DOI/PMID capture, D5)."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from app.infra.http import build_http_client, get_source_semaphore, with_retry
from app.ingestion.adapters import ENABLED_ADAPTERS, RawRecord, WatchlistQuery
from app.ingestion.enums import SourceName, SourceReliability

_log = structlog.get_logger(__name__)
_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_PAGE_SIZE = 25
_PREPRINT_SOURCE_CODES = frozenset({"PPR"})  # Europe PMC preprint server


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse YYYY-MM-DD date from Europe PMC; return None on failure."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(date_str[:10], fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _parse_search_response(data: dict) -> list[RawRecord]:
    """Parse Europe PMC search JSON response into RawRecords."""
    results = data.get("resultList", {}).get("result", [])
    records: list[RawRecord] = []
    for item in results:
        ext_id = item.get("id", "").strip()
        if not ext_id:
            continue
        pmid = item.get("pmid", "").strip() or None
        doi_raw = item.get("doi", "").strip()
        doi = doi_raw if doi_raw else None
        title = item.get("title", "").strip() or None
        abstract = item.get("abstractText", "").strip() or None
        published_at = _parse_date(item.get("firstPublicationDate"))
        source_code = item.get("source", "")
        is_preprint = source_code in _PREPRINT_SOURCE_CODES

        origin_url: str | None = None
        if pmid:
            origin_url = f"https://europepmc.org/article/MED/{pmid}"
        elif doi:
            origin_url = f"https://doi.org/{doi}"

        raw_payload: dict = {
            "id": ext_id,
            "pmid": pmid,
            "doi": doi,
            "source": source_code,
            "title": title,
            "firstPublicationDate": item.get("firstPublicationDate"),
        }
        records.append(
            RawRecord(
                source=SourceName.EUROPEPMC,
                source_external_id=ext_id,
                doi=doi,
                pmid=pmid,
                title=title,
                summary=abstract,
                published_at=published_at,
                origin_url=origin_url,
                raw_payload=raw_payload,
                # Preprints flagged separately for reliability; stored in raw_payload.
            )
        )
        # Attach preprint flag via raw_payload so runner can re-use if needed.
        raw_payload["is_preprint"] = is_preprint
    return records


class EuropePMCAdapter:
    """Europe PMC REST source adapter (peer_reviewed tier; preprints also tagged here)."""

    name = SourceName.EUROPEPMC
    reliability = SourceReliability.PEER_REVIEWED

    def __init__(self) -> None:
        self._semaphore = get_source_semaphore(SourceName.EUROPEPMC.value)

    async def fetch(
        self,
        query: WatchlistQuery,
        since: datetime | None,
        cap: int,
    ) -> list[RawRecord]:
        """Fetch up to `cap` Europe PMC records matching the watchlist query."""
        async with self._semaphore:
            return await self._fetch(query, since, cap)

    def _build_query(self, query: WatchlistQuery, since: datetime | None) -> str:
        terms: list[str] = []
        for drug in query.drugs:
            terms.append(f'"{drug}"')
        for kw in query.keywords:
            terms.append(f'"{kw}"')
        for mesh in query.mesh_terms:
            terms.append(f'MESH:"{mesh}"')
        base = " OR ".join(terms) if terms else "pharmacovigilance"
        if since:
            date_str = since.strftime("%Y-%m-%d")
            base += f" AND FIRST_PDATE:[{date_str} TO 9999-12-31]"
        return base

    async def _fetch(
        self, query: WatchlistQuery, since: datetime | None, cap: int
    ) -> list[RawRecord]:
        q = self._build_query(query, since)
        records: list[RawRecord] = []
        cursor = "*"

        @with_retry
        async def _page(client, params):
            resp = await client.get(_SEARCH_URL, params=params)
            resp.raise_for_status()
            return resp.json()

        async with build_http_client() as http:
            while len(records) < cap:
                params = {
                    "query": q,
                    "format": "json",
                    "pageSize": str(min(_PAGE_SIZE, cap - len(records))),
                    "cursorMark": cursor,
                    "resultType": "core",
                }
                data = await _page(http, params)
                batch = _parse_search_response(data)
                if not batch:
                    break
                records.extend(batch)
                next_cursor = data.get("nextCursorMark", "")
                if not next_cursor or next_cursor == cursor:
                    break
                cursor = next_cursor

        return records[:cap]


ENABLED_ADAPTERS.append(EuropePMCAdapter())
