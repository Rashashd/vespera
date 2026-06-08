"""PubMed E-utilities adapter: esearch + efetch, MeSH targeting, stdlib XML → RawRecord."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import structlog

from app.infra.http import build_http_client, get_source_semaphore, with_retry
from app.ingestion.adapters import ENABLED_ADAPTERS, RawRecord, WatchlistQuery
from app.ingestion.enums import SourceName, SourceReliability

_log = structlog.get_logger(__name__)

_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_BATCH_SIZE = 50  # NCBI recommends ≤200 PMIDs per efetch; we keep smaller for safety


def _parse_date(year: str | None, month: str | None, day: str | None) -> datetime | None:
    """Parse a PubMed PubDate into a UTC datetime; return None if unparseable."""
    if not year:
        return None
    try:
        y = int(year)
        m = int(month or 1)
        d = int(day or 1)
        return datetime(y, m, d, tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def _parse_efetch_xml(xml_text: str) -> list[RawRecord]:
    """Parse a PubMed efetch XML response into a list of RawRecords."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        _log.warning("pubmed.xml_parse_error", error=str(exc))
        return []

    records: list[RawRecord] = []
    for article in root.findall(".//PubmedArticle"):
        citation = article.find("MedlineCitation")
        if citation is None:
            continue

        pmid_el = citation.find("PMID")
        pmid = pmid_el.text.strip() if pmid_el is not None and pmid_el.text else None
        if not pmid:
            continue

        art = citation.find("Article")
        if art is None:
            continue

        title_el = art.find("ArticleTitle")
        title = title_el.text.strip() if title_el is not None and title_el.text else None

        abstract_el = art.find("Abstract/AbstractText")
        summary = abstract_el.text.strip() if abstract_el is not None and abstract_el.text else None

        # Publication date from Journal/JournalIssue/PubDate.
        pub_date_el = art.find("Journal/JournalIssue/PubDate")
        published_at: datetime | None = None
        if pub_date_el is not None:
            year = getattr(pub_date_el.find("Year"), "text", None)
            month = getattr(pub_date_el.find("Month"), "text", None)
            day = getattr(pub_date_el.find("Day"), "text", None)
            # Medline date alternative (e.g., <MedlineDate>2026 Jan-Feb</MedlineDate>)
            if not year:
                medline = getattr(pub_date_el.find("MedlineDate"), "text", None)
                if medline:
                    year = medline[:4] if len(medline) >= 4 else None
            published_at = _parse_date(year, month, day)

        # Collect DOI and confirm PMID from ArticleIdList.
        doi: str | None = None
        for aid in art.findall(".//ArticleId"):
            id_type = aid.get("IdType", "")
            text = (aid.text or "").strip()
            if id_type == "doi" and text:
                doi = text
        # Also check PubmedData ArticleIdList.
        for aid in article.findall(".//PubmedData/ArticleIdList/ArticleId"):
            id_type = aid.get("IdType", "")
            text = (aid.text or "").strip()
            if id_type == "doi" and text and doi is None:
                doi = text

        origin_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        raw_payload: dict = {
            "pmid": pmid,
            "doi": doi,
            "title": title,
            "published_at": published_at.isoformat() if published_at else None,
        }

        records.append(
            RawRecord(
                source=SourceName.PUBMED,
                source_external_id=pmid,
                doi=doi,
                pmid=pmid,
                title=title,
                summary=summary,
                published_at=published_at,
                origin_url=origin_url,
                raw_payload=raw_payload,
            )
        )

    return records


class PubMedAdapter:
    """PubMed E-utilities source adapter (peer_reviewed tier)."""

    name = SourceName.PUBMED
    reliability = SourceReliability.PEER_REVIEWED

    def __init__(self, *, api_key: str = "", ncbi_tool_email: str = "pantera@example.com") -> None:
        self._api_key = api_key
        self._tool_email = ncbi_tool_email
        self._semaphore = get_source_semaphore(SourceName.PUBMED.value)

    def _base_params(self) -> dict:
        params: dict = {"tool": "pantera", "email": self._tool_email, "retmode": "json"}
        if self._api_key:
            params["api_key"] = self._api_key
        return params

    def _build_query(self, query: WatchlistQuery, since: datetime | None) -> str:
        """Compose an E-utilities query string from the watchlist."""
        terms: list[str] = []
        for mesh in query.mesh_terms:
            terms.append(f'"{mesh}"[MeSH Terms]')
        for drug in query.drugs:
            terms.append(f'"{drug}"[MeSH Terms:NoExp]')
        for kw in query.keywords:
            terms.append(f'"{kw}"[Title/Abstract]')
        base = " OR ".join(terms) if terms else "pharmacovigilance"
        if since:
            date_str = since.strftime("%Y/%m/%d")
            base += f' AND ("{date_str}"[PDAT] : "3000"[PDAT])'
        return base

    async def fetch(
        self,
        query: WatchlistQuery,
        since: datetime | None,
        cap: int,
    ) -> list[RawRecord]:
        """Fetch up to `cap` PubMed records matching the watchlist query."""
        async with self._semaphore:
            return await self._fetch(query, since, cap)

    async def _fetch(
        self,
        query: WatchlistQuery,
        since: datetime | None,
        cap: int,
    ) -> list[RawRecord]:
        q = self._build_query(query, since)

        @with_retry
        async def _esearch(client, params):
            resp = await client.get(_ESEARCH_URL, params=params)
            resp.raise_for_status()
            return resp.json()

        @with_retry
        async def _efetch(client, params):
            resp = await client.get(_EFETCH_URL, params=params)
            resp.raise_for_status()
            return resp.text

        async with build_http_client(ncbi_tool_email=self._tool_email) as http:
            esearch_params = {
                **self._base_params(),
                "db": "pubmed",
                "term": q,
                "retmax": str(min(cap, 200)),
                "usehistory": "n",
            }
            esearch_data = await _esearch(http, esearch_params)
            pmids: list[str] = esearch_data.get("esearchresult", {}).get("idlist", [])

            if not pmids:
                return []

            records: list[RawRecord] = []
            for i in range(0, len(pmids), _BATCH_SIZE):
                batch = pmids[i : i + _BATCH_SIZE]
                efetch_params = {
                    **self._base_params(),
                    "db": "pubmed",
                    "id": ",".join(batch),
                    "rettype": "xml",
                    "retmode": "xml",
                }
                xml_text = await _efetch(http, efetch_params)
                records.extend(_parse_efetch_xml(xml_text))

        return records[:cap]


# Register the adapter on module import.
ENABLED_ADAPTERS.append(PubMedAdapter())
