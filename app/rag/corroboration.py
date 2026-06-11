"""Group retrieved passages by source document to compute corroboration metadata."""

from __future__ import annotations

from app.rag.schemas import CorroborationSource, RetrievedPassage


def build_corroboration(
    passages: list[RetrievedPassage],
) -> tuple[int, list[CorroborationSource]]:
    """Return (count, sources) where count == number of distinct document_ids in passages.

    A document contributing multiple passages counts as ONE corroboration source.
    All distinct sources are listed — never truncated (FR-013–015).
    """
    if not passages:
        return 0, []

    seen: dict[int, CorroborationSource] = {}
    # Preserve document appearance order (first passage rank wins ordering)
    for passage in passages:
        doc_id = passage.document_id
        if doc_id not in seen:
            seen[doc_id] = CorroborationSource(
                document_id=doc_id,
                title=passage.title,
                external_id=passage.external_id,
                date=passage.date,
                source_reliability=passage.source_reliability,
                sources=list(passage.sources),
                passage_chunk_ids=[passage.chunk_id],
            )
        else:
            seen[doc_id].passage_chunk_ids.append(passage.chunk_id)

    sources = list(seen.values())
    return len(sources), sources
