"""Parser router: dispatch a raw payload to the right parser by source type."""

from app.embedding.parsers.base import ParsedChunk, ParseError
from app.ingestion.enums import SourceName


def route(source: str, raw_payload: str | dict) -> list[ParsedChunk]:
    """Dispatch raw payload to the appropriate parser by source type.

    Args:
        source: The SourceName value (e.g., 'pubmed', 'openfda_faers').
        raw_payload: The raw document payload from DocumentSource.raw_payload.

    Returns:
        List of ParsedChunk from the parser.

    Raises:
        ParseError: If the parser fails (transient vs permanent).
    """
    try:
        source_enum = SourceName(source)
    except ValueError:
        raise ParseError(f"Unknown source: {source}", is_transient=False) from None

    match source_enum:
        case SourceName.PUBMED:
            from app.embedding.parsers.pubmed_jats import PubMedParser

            return PubMedParser().parse(raw_payload)
        case SourceName.EUROPEPMC:
            from app.embedding.parsers.europepmc_jats import EuropePMCParser

            return EuropePMCParser().parse(raw_payload)
        case SourceName.OPENFDA_FAERS:
            from app.embedding.parsers.openfda_faers import OpenFDAFAERSParser

            return OpenFDAFAERSParser().parse(raw_payload)
        case SourceName.OPENFDA_LABEL:
            from app.embedding.parsers.openfda_label import OpenFDALabelParser

            return OpenFDALabelParser().parse(raw_payload)
        case SourceName.FDA_MEDWATCH | SourceName.EMA | SourceName.MHRA:
            from app.embedding.parsers.regulatory_feed import RegulatoryFeedParser

            return RegulatoryFeedParser().parse(raw_payload)
