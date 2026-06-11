"""Client-scoped dense (HNSW cosine) and lexical (GIN tsquery) candidate retrieval."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.embedding.models import Chunk
from app.ingestion.models import Document, DocumentSource
from app.rag.schemas import RetrievedPassage

# Internal candidate row: carries just what's needed for ranking + projection
_CANDIDATE_COLS = (
    Chunk.id,
    Chunk.document_id,
    Chunk.ordinal,
    Chunk.chunk_type,
    Chunk.section,
    Chunk.text,
    Chunk.source_reliability,
    Chunk.date,
)


async def dense_candidates(
    session: AsyncSession,
    client_id: int,
    qvec: list[float],
    n: int = 50,
    chunk_types: list[str] | None = None,
    source_reliabilities: list[str] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[Any]:
    """Return up to n chunks ordered by HNSW cosine similarity (client-scoped, D2).

    Sets SET LOCAL hnsw.ef_search = 100 for better recall on small corpora.
    """
    await session.execute(text("SET LOCAL hnsw.ef_search = 100"))

    q = select(*_CANDIDATE_COLS).where(Chunk.client_id == client_id)

    if chunk_types:
        q = q.where(Chunk.chunk_type.in_(chunk_types))
    if source_reliabilities:
        q = q.where(Chunk.source_reliability.in_(source_reliabilities))
    if date_from:
        q = q.where(Chunk.date >= date_from)
    if date_to:
        q = q.where(Chunk.date <= date_to)

    q = q.order_by(Chunk.embedding.cosine_distance(qvec)).limit(n)

    rows = (await session.execute(q)).all()
    return list(rows)


async def lexical_candidates(
    session: AsyncSession,
    client_id: int,
    query_str: str,
    n: int = 50,
    chunk_types: list[str] | None = None,
    source_reliabilities: list[str] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[Any]:
    """Return up to n chunks ordered by ts_rank_cd over the GIN text_tsv index (D3).

    Uses 'english' config — must match the Spec-6 generated text_tsv config exactly.
    Tie-break by chunk id ASC for determinism (FR-010).
    """
    tsq = func.websearch_to_tsquery("english", query_str)
    rank_score = func.ts_rank_cd(Chunk.text_tsv, tsq)

    q = (
        select(*_CANDIDATE_COLS)
        .where(Chunk.client_id == client_id)
        .where(Chunk.text_tsv.op("@@")(tsq))
    )

    if chunk_types:
        q = q.where(Chunk.chunk_type.in_(chunk_types))
    if source_reliabilities:
        q = q.where(Chunk.source_reliability.in_(source_reliabilities))
    if date_from:
        q = q.where(Chunk.date >= date_from)
    if date_to:
        q = q.where(Chunk.date <= date_to)

    q = q.order_by(rank_score.desc(), Chunk.id.asc()).limit(n)

    rows = (await session.execute(q)).all()
    return list(rows)


async def project_passages(
    session: AsyncSession,
    candidates: list[Any],
) -> list[RetrievedPassage]:
    """Join candidates with documents/document_sources to produce full provenance passages.

    Returns passages in the same order as the input candidate list (FR-010).
    """
    if not candidates:
        return []

    doc_ids = list({row.document_id for row in candidates})

    # Fetch documents
    docs_result = await session.execute(select(Document).where(Document.id.in_(doc_ids)))
    docs: dict[int, Document] = {d.id: d for d in docs_result.scalars().all()}

    # Fetch sources per document
    sources_result = await session.execute(
        select(DocumentSource).where(DocumentSource.document_id.in_(doc_ids))
    )
    sources_by_doc: dict[int, list[str]] = {}
    for ds in sources_result.scalars().all():
        sources_by_doc.setdefault(ds.document_id, []).append(ds.source)

    passages: list[RetrievedPassage] = []
    for row in candidates:
        doc = docs.get(row.document_id)
        if doc is None:
            continue
        passages.append(
            RetrievedPassage(
                chunk_id=row.id,
                document_id=row.document_id,
                ordinal=row.ordinal,
                chunk_type=row.chunk_type,
                section=row.section,
                text=row.text,
                score=0.0,  # placeholder; set by caller after ranking
                rank=0,  # placeholder; set by caller after ranking
                source_reliability=row.source_reliability,
                title=doc.title,
                external_id=doc.normalized_external_id,
                date=doc.published_at,
                sources=sources_by_doc.get(row.document_id, []),
            )
        )

    return passages
