"""Unit tests for corroboration grouping logic (T025 / US3 / FR-013–015)."""

from __future__ import annotations

from datetime import datetime

from app.rag.corroboration import build_corroboration
from app.rag.schemas import RetrievedPassage


def _passage(
    chunk_id: int,
    document_id: int,
    *,
    title: str = "Doc",
    external_id: str = "ext-1",
) -> RetrievedPassage:
    return RetrievedPassage(
        chunk_id=chunk_id,
        document_id=document_id,
        ordinal=0,
        chunk_type="text",
        section=None,
        text="sample",
        score=1.0,
        rank=1,
        source_reliability="peer_reviewed",
        title=title,
        external_id=external_id,
        date=None,
        sources=["pubmed"],
    )


def test_empty_passages():
    count, sources = build_corroboration([])
    assert count == 0
    assert sources == []


def test_single_passage_single_doc():
    count, sources = build_corroboration([_passage(1, 10, external_id="doc-10")])
    assert count == 1
    assert len(sources) == 1
    assert sources[0].document_id == 10
    assert sources[0].passage_chunk_ids == [1]


def test_n_distinct_docs_count_n():
    """N passages from N different documents → corroboration_count == N."""
    passages = [_passage(i, i * 100, external_id=f"ext-{i}") for i in range(1, 6)]
    count, sources = build_corroboration(passages)
    assert count == 5
    assert len(sources) == 5


def test_multi_passage_single_doc_counts_once():
    """Multiple passages from one document count as ONE corroboration source (FR-013)."""
    passages = [
        _passage(1, 10, external_id="doc-10"),
        _passage(2, 10, external_id="doc-10"),
        _passage(3, 10, external_id="doc-10"),
    ]
    count, sources = build_corroboration(passages)
    assert count == 1
    src = sources[0]
    assert src.document_id == 10
    assert set(src.passage_chunk_ids) == {1, 2, 3}


def test_all_sources_listed_never_truncated():
    """ALL distinct source documents must appear in corroboration_sources (FR-015)."""
    n = 20
    passages = [_passage(i, i, external_id=f"ext-{i}") for i in range(n)]
    count, sources = build_corroboration(passages)
    assert count == n
    assert len(sources) == n  # none truncated


def test_preserves_document_metadata():
    """CorroborationSource inherits title/external_id/reliability from passage."""
    p = RetrievedPassage(
        chunk_id=99,
        document_id=55,
        ordinal=0,
        chunk_type="text",
        section="Methods",
        text="example",
        score=5.0,
        rank=1,
        source_reliability="regulatory_alert",
        title="Safety Report",
        external_id="PMID:999",
        date=datetime(2024, 1, 1),
        sources=["europepmc"],
    )
    count, sources = build_corroboration([p])
    src = sources[0]
    assert src.title == "Safety Report"
    assert src.external_id == "PMID:999"
    assert src.source_reliability == "regulatory_alert"
    assert src.sources == ["europepmc"]
    assert src.passage_chunk_ids == [99]


def test_mixed_single_and_multi_passage_docs():
    """Some docs with one passage, some with many — each counted once."""
    passages = [
        _passage(1, 10, external_id="doc-10"),
        _passage(2, 10, external_id="doc-10"),
        _passage(3, 20, external_id="doc-20"),
        _passage(4, 30, external_id="doc-30"),
        _passage(5, 30, external_id="doc-30"),
    ]
    count, sources = build_corroboration(passages)
    assert count == 3
    doc_ids = {s.document_id for s in sources}
    assert doc_ids == {10, 20, 30}

    src_10 = next(s for s in sources if s.document_id == 10)
    assert set(src_10.passage_chunk_ids) == {1, 2}

    src_20 = next(s for s in sources if s.document_id == 20)
    assert src_20.passage_chunk_ids == [3]
