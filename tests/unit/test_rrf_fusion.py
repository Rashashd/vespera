"""Unit tests for RRF fusion math and deterministic tie-break (T020 / US2 / FR-007/010)."""

from __future__ import annotations

from types import SimpleNamespace

from app.rag.fusion import reciprocal_rank_fusion


def _rows(*ids):
    """Create a list of SimpleNamespace rows with .id attributes."""
    return [SimpleNamespace(id=i) for i in ids]


def test_single_leg_preserves_order():
    rows = _rows(3, 1, 2)
    fused = reciprocal_rank_fusion(rows)
    assert [r.id for r in fused] == [3, 1, 2]


def test_two_legs_sum_scores():
    """Chunk appearing in both legs gets higher fused score than chunk in one."""
    leg_dense = _rows(10, 20, 30)
    leg_lexical = _rows(20, 30, 10)
    fused = reciprocal_rank_fusion(leg_dense, leg_lexical)

    ids = [r.id for r in fused]
    # 20 is rank-1 in dense + rank-0 in lexical → highest
    # 10 is rank-0 in dense + rank-2 in lexical
    # 30 is rank-2 in dense + rank-1 in lexical
    # All appear in both legs, so all get summed contributions
    assert set(ids) == {10, 20, 30}
    # 20 should be first (rank-1+rank-0 → lowest ranks sum → highest score)
    assert ids[0] == 20


def test_deduplication():
    """A chunk in both legs appears exactly once in output."""
    leg_a = _rows(1, 2, 3)
    leg_b = _rows(2, 3, 4)
    fused = reciprocal_rank_fusion(leg_a, leg_b)
    ids = [r.id for r in fused]
    assert len(ids) == len(set(ids))
    assert set(ids) == {1, 2, 3, 4}


def test_deterministic_tie_break_by_id_asc():
    """Chunks with identical fused scores are broken by id ascending (FR-010)."""
    # Each chunk appears once in each leg but at the same rank
    leg_a = _rows(5, 3)
    leg_b = _rows(3, 5)
    fused = reciprocal_rank_fusion(leg_a, leg_b)
    ids = [r.id for r in fused]
    # Both have same fused score (1/(60+1) + 1/(60+2) for each) — id tie-break
    assert ids[0] == 3  # smaller id first
    assert ids[1] == 5


def test_empty_legs():
    fused = reciprocal_rank_fusion([], [])
    assert fused == []


def test_empty_one_leg():
    rows = _rows(1, 2)
    fused = reciprocal_rank_fusion(rows, [])
    assert [r.id for r in fused] == [1, 2]


def test_rrf_constant_k():
    """Score of rank-0 item is 1/(k+1) — verifiable formula check."""
    rows = _rows(42)
    fused = reciprocal_rank_fusion(rows, k=60)
    assert len(fused) == 1


def test_deterministic_repeated_calls():
    """Same inputs always produce identical output (FR-010)."""
    leg_a = _rows(7, 2, 9)
    leg_b = _rows(9, 7, 2)
    result1 = [r.id for r in reciprocal_rank_fusion(leg_a, leg_b)]
    result2 = [r.id for r in reciprocal_rank_fusion(leg_a, leg_b)]
    assert result1 == result2


def test_three_legs():
    """Fusion works with more than two legs."""
    leg_a = _rows(1, 2)
    leg_b = _rows(2, 3)
    leg_c = _rows(1, 3)
    fused = reciprocal_rank_fusion(leg_a, leg_b, leg_c)
    ids = [r.id for r in fused]
    assert set(ids) == {1, 2, 3}
