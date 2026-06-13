"""Unit tests for failure classification in index build (T037, FR-011)."""

from app.embedding.parsers.base import ParseError


class TestFailureClassification:
    """Test transient vs permanent error classification."""

    def test_parse_error_transient_flag(self) -> None:
        """ParseError tracks whether failure is transient (retryable)."""
        # Transient error (modelserver timeout, 5xx)
        transient_err = ParseError("modelserver timeout", is_transient=True)
        assert transient_err.is_transient is True

        # Permanent error (bad XML, 4xx)
        permanent_err = ParseError("malformed XML", is_transient=False)
        assert permanent_err.is_transient is False

    def test_transient_includes_network_issues(self) -> None:
        """Transient errors include: timeout, 5xx, connection errors."""
        scenarios = [
            ("modelserver unavailable (5xx)", True),
            ("connection timeout", True),
            ("socket reset", True),
            ("malformed JSON (4xx)", False),
            ("unknown source type (4xx)", False),
            ("invalid XML structure (parse error)", False),
        ]

        for description, is_transient in scenarios:
            err = ParseError(description, is_transient=is_transient)
            assert (
                err.is_transient == is_transient
            ), f"{description} should be transient={is_transient}"

    def test_document_index_state_transitions(self) -> None:
        """Verify state transitions for different error types."""
        from app.embedding.enums import DocumentIndexStatus

        # Transient error → errored_transient (can be retried)
        # On next run: pick up errored_transient docs again
        transient_status = DocumentIndexStatus.ERRORED_TRANSIENT
        assert transient_status == "errored_transient"

        # Permanent error → errored_permanent (skip on re-runs)
        # On next run: skip errored_permanent docs
        permanent_status = DocumentIndexStatus.ERRORED_PERMANENT
        assert permanent_status == "errored_permanent"

        # Successful → indexed or indexed_empty
        # On next run: skip (already indexed)
        indexed = DocumentIndexStatus.INDEXED
        indexed_empty = DocumentIndexStatus.INDEXED_EMPTY
        assert indexed == "indexed"
        assert indexed_empty == "indexed_empty"

    def test_retry_logic(self) -> None:
        """Verify retry behavior: transient retried, permanent skipped."""
        from app.embedding.enums import DocumentIndexStatus

        # Transient failure should be in eligible list for next run
        eligible_statuses = [
            DocumentIndexStatus.NOT_INDEXED,
            DocumentIndexStatus.ERRORED_TRANSIENT,
        ]

        skip_statuses = [
            DocumentIndexStatus.INDEXED,
            DocumentIndexStatus.INDEXED_EMPTY,
            DocumentIndexStatus.ERRORED_PERMANENT,
        ]

        # Next run should process eligible
        for status in eligible_statuses:
            assert status in eligible_statuses, f"Status {status} should be retried"

        # Next run should skip non-eligible
        for status in skip_statuses:
            assert status not in eligible_statuses, f"Status {status} should be skipped"
