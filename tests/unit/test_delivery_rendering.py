"""Unit tests for render_report_document (US1/FR-002): content + batch included-only + escaping."""

from types import SimpleNamespace

from app.delivery.rendering import render_report_document


def _report(**overrides):
    base = dict(
        id=42,
        report_type="batch",
        status="approved",
        structured_fields=[
            {"text": "Hepatotoxicity observed in 3 cases", "provenance": "drafted_grounded"},
            {"text": "Reviewer-confirmed causality", "provenance": "reviewer_attested"},
        ],
        corroboration_count=3,
        corroboration_sources=[{"title": "PMID-111"}, {"title": "PMID-222"}, {"title": "PMID-333"}],
        draft_body="Narrative summary of the safety signal.",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestRenderReportDocument:
    def test_self_contained_html(self):
        html = render_report_document(_report())
        assert html.startswith("<!DOCTYPE html>")
        assert "<html" in html and "</html>" in html

    def test_includes_claims_and_provenance(self):
        html = render_report_document(_report())
        assert "Hepatotoxicity observed in 3 cases" in html
        assert "drafted_grounded" in html
        assert "reviewer_attested" in html

    def test_includes_corroboration_count_and_all_sources(self):
        html = render_report_document(_report())
        assert "Corroborating sources: 3" in html
        assert "PMID-111" in html and "PMID-222" in html and "PMID-333" in html

    def test_includes_narrative_body(self):
        html = render_report_document(_report())
        assert "Narrative summary of the safety signal." in html

    def test_batch_renders_only_included_findings(self):
        findings = [
            {"drug": "DrugIncluded", "reaction": "rashA", "bucket": "serious", "state": "included"},
            {"drug": "DrugDropped", "reaction": "rashB", "bucket": "serious", "state": "dropped"},
            {
                "drug": "DrugDiscarded",
                "reaction": "rashC",
                "bucket": "serious",
                "state": "discarded",
            },
        ]
        html = render_report_document(_report(), findings)
        assert "DrugIncluded" in html
        assert "DrugDropped" not in html
        assert "DrugDiscarded" not in html

    def test_escapes_html_in_body(self):
        html = render_report_document(_report(draft_body="<script>alert(1)</script>"))
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html


def _cited_report(**overrides):
    """Report whose claims carry source_refs that resolve into numbered corroboration sources."""
    base = dict(
        id=7,
        report_type="expedited",
        status="approved",
        structured_fields=[
            {
                "text": "Acute liver injury observed",
                "provenance": "drafted_grounded",
                "source_ref": "101",
            },
            {
                "text": "Reviewer-confirmed causality",
                "provenance": "reviewer_attested",
                "source_ref": None,
            },
            {
                "text": "Claim with a dangling ref",
                "provenance": "drafted_grounded",
                "source_ref": "999",
            },
        ],
        corroboration_count=2,
        corroboration_sources=[
            {
                "title": "Hepatotoxicity case series",
                "external_id": "PMID-101",
                "source_reliability": "peer_reviewed",
                "passage_chunk_ids": [101, 102],
            },
            {
                "title": "FAERS signal",
                "external_id": "FAERS-22",
                "source_reliability": "regulatory",
                "passage_chunk_ids": ["205"],  # str on the wire — must coerce
            },
        ],
        draft_body="Narrative.",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestNumberedCitations:
    def test_grounded_claim_gets_clickable_anchor_to_its_source(self):
        html = render_report_document(_cited_report())
        # chunk 101 → source #1 → claim cites [1] anchored at <li id="ref-1">.
        assert '<a class="cite" href="#ref-1">[1]</a>' in html
        assert '<li id="ref-1">' in html
        assert "[1] Hepatotoxicity case series" in html

    def test_only_resolvable_claims_are_numbered(self):
        # source_ref=None (reviewer-attested) and "999" (dangling) get no number → exactly 1 cite.
        html = render_report_document(_cited_report())
        assert html.count('class="cite"') == 1

    def test_unresolvable_source_ref_does_not_crash(self):
        # A claim whose source_ref matches no source renders without a number (FR-002: no throw).
        rpt = _cited_report(
            structured_fields=[
                {"text": "orphan", "provenance": "drafted_grounded", "source_ref": "abc"},
            ]
        )
        html = render_report_document(rpt)
        assert "orphan" in html
        assert 'class="cite"' not in html

    def test_references_numbered_stably_no_duplicates(self):
        html = render_report_document(_cited_report())
        assert '<li id="ref-1">' in html
        assert '<li id="ref-2">' in html
        assert '<li id="ref-3">' not in html  # only two sources
        assert html.count('id="ref-1"') == 1
        assert html.count('id="ref-2"') == 1

    def test_every_citation_anchor_has_a_target(self):
        import re

        html = render_report_document(_cited_report())
        for num in re.findall(r'href="#ref-(\d+)"', html):
            assert f'id="ref-{num}"' in html

    def test_reference_shows_external_id_and_reliability(self):
        html = render_report_document(_cited_report())
        assert "PMID-101" in html and "peer_reviewed" in html

    def test_self_contained_no_external_requests(self):
        html = render_report_document(_cited_report())
        assert "http://" not in html
        assert "https://" not in html
        assert "<script" not in html
        assert "src=" not in html  # no external images/scripts
        # the only hrefs are in-document anchors
        import re

        for href in re.findall(r'href="([^"]*)"', html):
            assert href.startswith("#ref-")
