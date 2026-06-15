"""Transient vs permanent job failure classification (spec 11 FR-007/FR-008)."""


class PermanentJobError(Exception):
    """Raise to skip all retries and go straight to the dead-letter queue (FR-008).

    Use for: validation errors, 4xx HTTP responses from external services, business-rule
    violations (e.g. watchlist inactive, cycle already completed). Any other exception is
    treated as transient — ARQ will retry up to max_tries=3 with backoff (FR-007).
    """

    def __init__(self, message: str, *, error_class: str = "") -> None:
        super().__init__(message)
        self.error_class = error_class or type(self).__name__


def is_permanent(exc: BaseException) -> bool:
    """Return True if the exception should NOT be retried (dead-letter immediately)."""
    return isinstance(exc, PermanentJobError)
