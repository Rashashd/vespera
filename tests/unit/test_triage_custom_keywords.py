"""Unit tests for the per-client custom severity keyword layer (US3, FR-004)."""

from app.triage.enums import Bucket
from app.triage.severity import assign_bucket


class TestCustomKeywordEscalation:
    def test_keyword_escalates_minor_to_urgent(self):
        custom = [{"keyword": "rhabdomyolysis", "tier": "serious"}]
        bucket = assign_bucket(
            verdict=True,
            text="Patient developed rhabdomyolysis after treatment.",
            source_reliability="peer_reviewed",
            custom_keywords=custom,
        )
        assert bucket == Bucket.URGENT

    def test_keyword_escalates_minor_to_emergency(self):
        custom = [{"keyword": "fatal outcome", "tier": "life-threatening"}]
        bucket = assign_bucket(
            verdict=True,
            text="Fatal outcome observed in two patients.",
            source_reliability="peer_reviewed",
            custom_keywords=custom,
        )
        assert bucket == Bucket.EMERGENCY

    def test_custom_keyword_never_downgrades_ich_emergency(self):
        """A 'serious' custom keyword cannot lower an ICH emergency bucket."""
        custom = [{"keyword": "mild side effect", "tier": "serious"}]
        bucket = assign_bucket(
            verdict=True,
            text="The patient experienced death from the reaction.",
            source_reliability="peer_reviewed",
            custom_keywords=custom,
        )
        assert bucket == Bucket.EMERGENCY

    def test_client_isolation_same_text_different_keywords(self):
        """Same document; client A escalates via custom keyword, client B uses ICH defaults."""
        text = "Patient had serious liver damage."
        custom_a = [{"keyword": "liver damage", "tier": "life-threatening"}]
        custom_b: list = []

        bucket_a = assign_bucket(
            verdict=True,
            text=text,
            source_reliability="peer_reviewed",
            custom_keywords=custom_a,
        )
        bucket_b = assign_bucket(
            verdict=True,
            text=text,
            source_reliability="peer_reviewed",
            custom_keywords=custom_b,
        )

        assert bucket_a == Bucket.EMERGENCY
        assert bucket_b == Bucket.MINOR  # "liver damage" not an ICH keyword

    def test_empty_custom_keywords_falls_through_to_ich(self):
        """Empty list means ICH defaults only."""
        bucket = assign_bucket(
            verdict=True,
            text="Patient experienced nausea.",
            source_reliability="peer_reviewed",
            custom_keywords=[],
        )
        assert bucket == Bucket.MINOR

    def test_none_custom_keywords_falls_through_to_ich(self):
        """None is treated the same as empty — no custom escalation."""
        bucket = assign_bucket(
            verdict=True,
            text="Patient experienced nausea.",
            source_reliability="peer_reviewed",
            custom_keywords=None,
        )
        assert bucket == Bucket.MINOR

    def test_multiple_keywords_max_rank_wins(self):
        """When two custom keywords match, the higher-tier one determines the bucket."""
        custom = [
            {"keyword": "nausea", "tier": "serious"},
            {"keyword": "cardiac arrest", "tier": "life-threatening"},
        ]
        bucket = assign_bucket(
            verdict=True,
            text="Patient had nausea and cardiac arrest.",
            source_reliability="peer_reviewed",
            custom_keywords=custom,
        )
        assert bucket == Bucket.EMERGENCY
