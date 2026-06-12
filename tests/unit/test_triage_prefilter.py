"""Unit tests for the substantive-mention pre-filter (US2, FR-001)."""

from unittest.mock import patch

import pytest

from app.triage.prefilter import filter_substantive_drugs


@pytest.mark.asyncio
async def test_incidental_drug_filtered():
    """Drug in summary with no same-sentence DISEASE → filtered, empty result."""
    with patch("app.triage.prefilter._check_substantive_sync") as mock_fn:
        mock_fn.return_value = [("ibuprofen", False, "incidental_no_disease")]
        result = await filter_substantive_drugs(
            "Some text.\nibuprofen was used as comparator.",
            ["ibuprofen"],
            client_id=1,
            document_id=1,
        )
    assert result == []


@pytest.mark.asyncio
async def test_title_mention_is_substantive():
    """Drug sentence starts before the newline (title) → always substantive."""
    with patch("app.triage.prefilter._check_substantive_sync") as mock_fn:
        mock_fn.return_value = [("aspirin", True, "title_mention")]
        result = await filter_substantive_drugs(
            "Aspirin causes GI bleeding\nSummary text here.",
            ["aspirin"],
            client_id=1,
            document_id=1,
        )
    assert result == ["aspirin"]


@pytest.mark.asyncio
async def test_same_sentence_disease_is_substantive():
    """Drug co-occurring with DISEASE in the same summary sentence → substantive."""
    with patch("app.triage.prefilter._check_substantive_sync") as mock_fn:
        mock_fn.return_value = [("methotrexate", True, "same_sentence_disease")]
        result = await filter_substantive_drugs(
            "Abstract\nMethotrexate was associated with hepatotoxicity in 12 patients.",
            ["methotrexate"],
            client_id=1,
            document_id=1,
        )
    assert result == ["methotrexate"]


@pytest.mark.asyncio
async def test_mixed_drugs_only_substantive_returned():
    """Substantive drug passes; incidental drug is filtered; order preserved."""
    with patch("app.triage.prefilter._check_substantive_sync") as mock_fn:
        mock_fn.return_value = [
            ("aspirin", True, "same_sentence_disease"),
            ("placebo", False, "incidental_no_disease"),
        ]
        result = await filter_substantive_drugs(
            "Title\nAspirin caused bleeding. Placebo was used as control.",
            ["aspirin", "placebo"],
            client_id=1,
            document_id=1,
        )
    assert result == ["aspirin"]
    assert "placebo" not in result


@pytest.mark.asyncio
async def test_empty_matched_drugs_skips_nlp():
    """Empty drug list returns immediately without calling the NLP pipeline."""
    with patch("app.triage.prefilter._check_substantive_sync") as mock_fn:
        result = await filter_substantive_drugs("Some text.", [], client_id=1, document_id=1)
    mock_fn.assert_not_called()
    assert result == []


@pytest.mark.asyncio
async def test_all_drugs_incidental_returns_empty():
    """All matched drugs incidental → empty list returned."""
    with patch("app.triage.prefilter._check_substantive_sync") as mock_fn:
        mock_fn.return_value = [
            ("drugA", False, "incidental_no_disease"),
            ("drugB", False, "incidental_no_disease"),
        ]
        result = await filter_substantive_drugs(
            "Title\nText about drugA and drugB as comparators.",
            ["drugA", "drugB"],
            client_id=1,
            document_id=1,
        )
    assert result == []
