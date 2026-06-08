"""FDA MedWatch adapter: RSS/XML safety alert feed → regulatory_alert RawRecord."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import structlog

from app.infra.http import build_http_client, get_source_semaphore, with_retry
from app.ingestion.adapters import ENABLED_ADAPTERS, RawRecord, WatchlistQuery
from app.ingestion.enums import SourceName, SourceReliability

_log = structlog.get_logger(__name__)
_RSS_URL = "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/medwatch-safety-alerts/rss.xml"


def _parse_rfc2822_date(date_str: str | None) -> datetime | None:
    """Parse an RFC-2822 date string (RSS pubDate); return None on failure."""
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str).astimezone(UTC)
    except Exception:  # noqa: BLE001
        return None


def _parse_rss(xml_text: str) -> list[RawRecord]:
    """Parse a MedWatch RSS feed into regulatory_alert RawRecords."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        _log.warning("medwatch.xml_parse_error", error=str(exc))
        return []

    records: list[RawRecord] = []
    for item in root.findall(".//item"):
        title_el = item.find("title")
        title = title_el.text.strip() if title_el is not None and title_el.text else None

        link_el = item.find("link")
        url = link_el.text.strip() if link_el is not None and link_el.text else None

        desc_el = item.find("description")
        summary = desc_el.text.strip() if desc_el is not None and desc_el.text else None

        pub_date_el = item.find("pubDate")
        pub_date_str = pub_date_el.text.strip() if pub_date_el is not None else None
        published_at = _parse_rfc2822_date(pub_date_str)

        guid_el = item.find("guid")
        guid = guid_el.text.strip() if guid_el is not None and guid_el.text else url or ""

        ext_id = guid.split("/")[-1] if guid else ""
        if not ext_id:
            continue

        records.append(
            RawRecord(
                source=SourceName.FDA_MEDWATCH,
                source_external_id=ext_id,
                title=title,
                summary=summary,
                published_at=published_at,
                origin_url=url,
                raw_payload={"guid": guid, "title": title, "pubDate": pub_date_str, "url": url},
            )
        )
    return records


class FDAMedWatchAdapter:
    """FDA MedWatch RSS safety alert adapter (regulatory_alert tier)."""

    name = SourceName.FDA_MEDWATCH
    reliability = SourceReliability.REGULATORY_ALERT

    def __init__(self) -> None:
        self._semaphore = get_source_semaphore(SourceName.FDA_MEDWATCH.value)

    async def fetch(
        self,
        query: WatchlistQuery,
        since: datetime | None,
        cap: int,
    ) -> list[RawRecord]:
        """Fetch MedWatch RSS feed; filter by query drug/keyword terms post-fetch."""
        async with self._semaphore:
            return await self._fetch(query, since, cap)

    async def _fetch(
        self, query: WatchlistQuery, since: datetime | None, cap: int
    ) -> list[RawRecord]:
        @with_retry
        async def _get_feed(client):
            resp = await client.get(_RSS_URL)
            resp.raise_for_status()
            return resp.text

        async with build_http_client() as http:
            xml_text = await _get_feed(http)

        all_records = _parse_rss(xml_text)

        # Post-fetch filter: keep records matching any query term (drug or keyword).
        filter_terms = {t.lower() for t in (query.drugs + query.keywords + query.mesh_terms)}
        if filter_terms:
            filtered = [
                r
                for r in all_records
                if any(
                    t in (r.title or "").lower() or t in (r.summary or "").lower()
                    for t in filter_terms
                )
            ]
        else:
            filtered = all_records

        # Watermark filter.
        if since:
            filtered = [r for r in filtered if r.published_at is None or r.published_at >= since]

        return filtered[:cap]


ENABLED_ADAPTERS.append(FDAMedWatchAdapter())
