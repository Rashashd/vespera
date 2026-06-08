"""openFDA adapter: FAERS (case_report) + drug-label (peer_reviewed) endpoints → RawRecord."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from app.infra.http import build_http_client, get_source_semaphore, with_retry
from app.ingestion.adapters import ENABLED_ADAPTERS, RawRecord, WatchlistQuery
from app.ingestion.enums import SourceName, SourceReliability

_log = structlog.get_logger(__name__)
_BASE_URL = "https://api.fda.gov"
_FAERS_URL = f"{_BASE_URL}/drug/event.json"
_LABEL_URL = f"{_BASE_URL}/drug/label.json"


def _parse_receipt_date(date_str: str | None) -> datetime | None:
    """Parse YYYYMMDD openFDA date; return None on failure."""
    if not date_str or len(date_str) < 8:
        return None
    try:
        return datetime(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]), tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def _parse_label_date(date_str: str | None) -> datetime | None:
    """Parse YYYYMMDD effective_time date; return None on failure."""
    return _parse_receipt_date(date_str)


def _parse_faers_response(data: dict) -> list[RawRecord]:
    """Parse openFDA FAERS event search response into case_report RawRecords."""
    results = data.get("results", [])
    records: list[RawRecord] = []
    for item in results:
        report_id = item.get("safetyreportid", "").strip()
        if not report_id:
            continue
        published_at = _parse_receipt_date(item.get("receiptdate"))
        title = f"FAERS Adverse Event Report: {report_id}"
        raw_payload = {k: v for k, v in item.items() if k != "patient"}  # no PII in payload
        record = RawRecord(
            source=SourceName.OPENFDA_FAERS,
            source_external_id=f"US-FDA-{report_id}",
            title=title,
            published_at=published_at,
            origin_url=f"https://api.fda.gov/drug/event.json?search=safetyreportid:{report_id}",
            raw_payload=raw_payload,
        )
        records.append(record)
    return records


def _parse_label_response(data: dict) -> list[RawRecord]:
    """Parse openFDA drug-label search response into peer_reviewed RawRecords."""
    results = data.get("results", [])
    records: list[RawRecord] = []
    for item in results:
        label_id = item.get("id", "").strip()
        if not label_id:
            continue
        openfda = item.get("openfda", {})
        brand_names = openfda.get("brand_name", [])
        title = f"Drug Label: {', '.join(brand_names)}" if brand_names else f"Drug Label {label_id}"
        published_at = _parse_label_date(item.get("effective_time"))
        raw_payload = {
            "id": label_id,
            "openfda": openfda,
            "effective_time": item.get("effective_time"),
        }
        record = RawRecord(
            source=SourceName.OPENFDA_LABEL,
            source_external_id=label_id,
            title=title,
            published_at=published_at,
            origin_url=f"https://api.fda.gov/drug/label.json?search=id:{label_id}",
            raw_payload=raw_payload,
            reliability=SourceReliability.PEER_REVIEWED,
        )
        records.append(record)
    return records


class OpenFDAAdapter:
    """openFDA adapter: queries both FAERS (case_report) and drug-label (peer_reviewed)."""

    name = SourceName.OPENFDA_FAERS  # primary name; label records use OPENFDA_LABEL
    reliability = SourceReliability.CASE_REPORT  # FAERS tier; labels override per-record

    def __init__(self, *, api_key: str = "") -> None:
        self._api_key = api_key
        self._semaphore = get_source_semaphore("openfda")

    def _base_params(self) -> dict:
        params: dict = {}
        if self._api_key:
            params["api_key"] = self._api_key
        return params

    def _build_drug_query(self, query: WatchlistQuery) -> str:
        terms = [f'"{d}"' for d in query.drugs] + [f'"{kw}"' for kw in query.keywords]
        return " OR ".join(terms) if terms else "warfarin"

    async def fetch(
        self,
        query: WatchlistQuery,
        since: datetime | None,
        cap: int,
    ) -> list[RawRecord]:
        """Fetch FAERS adverse events + drug labels; cap split evenly between both."""
        async with self._semaphore:
            return await self._fetch(query, since, cap)

    async def _fetch(
        self, query: WatchlistQuery, since: datetime | None, cap: int
    ) -> list[RawRecord]:
        drug_q = self._build_drug_query(query)
        half_cap = max(1, cap // 2)

        @with_retry
        async def _get(client, url, params):
            resp = await client.get(url, params=params)
            if resp.status_code == 404:
                return {"results": []}
            resp.raise_for_status()
            return resp.json()

        async with build_http_client() as http:
            faers_params = {
                **self._base_params(),
                "search": f"patient.drug.medicinalproduct:{drug_q}",
                "limit": str(half_cap),
            }
            if since:
                date_str = since.strftime("%Y%m%d")
                faers_params["search"] += f" AND receiptdate:[{date_str} TO 99991231]"

            label_params = {
                **self._base_params(),
                "search": f"openfda.brand_name:{drug_q}",
                "limit": str(half_cap),
            }

            faers_data = await _get(http, _FAERS_URL, faers_params)
            label_data = await _get(http, _LABEL_URL, label_params)

        return _parse_faers_response(faers_data) + _parse_label_response(label_data)


# openFDA registers once — the adapter fetches from both sub-sources internally.
ENABLED_ADAPTERS.append(OpenFDAAdapter())
