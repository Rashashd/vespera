"""Unit tests for triage severity bucketing: ICH keyword rule, regulatory floor, custom keywords."""

from app.triage.enums import Bucket
from app.triage.severity import assign_bucket


class TestIchKeywordMapping:
    def test_life_threatening_keyword_emergency(self):
        assert (
            assign_bucket(
                verdict=True,
                text="patient went into cardiac arrest",
                source_reliability="peer_reviewed",
            )
            == Bucket.EMERGENCY
        )

    def test_death_keyword_emergency(self):
        assert (
            assign_bucket(
                verdict=True, text="the outcome was fatal", source_reliability="peer_reviewed"
            )
            == Bucket.EMERGENCY
        )

    def test_hospitalization_keyword_urgent(self):
        assert (
            assign_bucket(
                verdict=True,
                text="patient required hospitalization for two weeks",
                source_reliability="peer_reviewed",
            )
            == Bucket.URGENT
        )

    def test_severe_keyword_urgent(self):
        assert (
            assign_bucket(
                verdict=True,
                text="severe hepatotoxicity observed",
                source_reliability="peer_reviewed",
            )
            == Bucket.URGENT
        )

    def test_no_ich_keyword_minor(self):
        assert (
            assign_bucket(
                verdict=True,
                text="mild nausea reported after dose",
                source_reliability="peer_reviewed",
            )
            == Bucket.MINOR
        )

    def test_highest_rank_wins(self):
        # Text contains both urgent and emergency keywords → EMERGENCY wins
        assert (
            assign_bucket(
                verdict=True,
                text="severe hospitalization and cardiac arrest occurred",
                source_reliability="peer_reviewed",
            )
            == Bucket.EMERGENCY
        )


class TestRegulatoryAlertFloor:
    def test_regulatory_alert_upgrades_minor_to_urgent(self):
        assert (
            assign_bucket(
                verdict=True,
                text="mild nausea reported after dose",
                source_reliability="regulatory_alert",
            )
            == Bucket.URGENT
        )

    def test_regulatory_alert_does_not_downgrade_emergency(self):
        assert (
            assign_bucket(
                verdict=True,
                text="patient went into cardiac arrest",
                source_reliability="regulatory_alert",
            )
            == Bucket.EMERGENCY
        )

    def test_non_regulatory_minor_stays_minor(self):
        assert (
            assign_bucket(
                verdict=True,
                text="mild nausea reported after dose",
                source_reliability="peer_reviewed",
            )
            == Bucket.MINOR
        )


class TestNoVerdictBucket:
    def test_false_verdict_returns_irrelevant(self):
        # NO verdict → IRRELEVANT (valence assessed separately in service.py)
        assert (
            assign_bucket(verdict=False, text="any text", source_reliability="peer_reviewed")
            == Bucket.IRRELEVANT
        )

    def test_false_verdict_ignores_keywords(self):
        assert (
            assign_bucket(
                verdict=False, text="fatal cardiac arrest", source_reliability="regulatory_alert"
            )
            == Bucket.IRRELEVANT
        )


class TestCustomKeywordEscalation:
    def test_custom_keyword_escalates_minor_to_urgent(self):
        custom = [{"keyword": "rhabdomyolysis", "tier": "serious"}]
        result = assign_bucket(
            verdict=True,
            text="patient developed rhabdomyolysis after statin use",
            source_reliability="peer_reviewed",
            custom_keywords=custom,
        )
        assert result == Bucket.URGENT

    def test_custom_keyword_escalates_to_emergency(self):
        custom = [{"keyword": "fatal myopathy", "tier": "life-threatening"}]
        result = assign_bucket(
            verdict=True,
            text="patient developed fatal myopathy",
            source_reliability="peer_reviewed",
            custom_keywords=custom,
        )
        assert result == Bucket.EMERGENCY

    def test_custom_keyword_cannot_downgrade(self):
        # Custom keyword tier=serious on an already-EMERGENCY bucket keeps EMERGENCY
        custom = [{"keyword": "rhabdomyolysis", "tier": "serious"}]
        result = assign_bucket(
            verdict=True,
            text="fatal cardiac arrest and rhabdomyolysis",
            source_reliability="peer_reviewed",
            custom_keywords=custom,
        )
        assert result == Bucket.EMERGENCY

    def test_empty_custom_keywords_uses_ich_defaults(self):
        assert (
            assign_bucket(
                verdict=True,
                text="mild nausea after dose",
                source_reliability="peer_reviewed",
                custom_keywords=[],
            )
            == Bucket.MINOR
        )

    def test_none_custom_keywords_uses_ich_defaults(self):
        assert (
            assign_bucket(
                verdict=True,
                text="mild nausea after dose",
                source_reliability="peer_reviewed",
                custom_keywords=None,
            )
            == Bucket.MINOR
        )

    def test_custom_keyword_case_insensitive(self):
        custom = [{"keyword": "RHABDOMYOLYSIS", "tier": "serious"}]
        result = assign_bucket(
            verdict=True,
            text="rhabdomyolysis observed",
            source_reliability="peer_reviewed",
            custom_keywords=custom,
        )
        assert result == Bucket.URGENT
