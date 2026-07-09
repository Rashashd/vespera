"""Small shared value-coercion helpers used across packages."""

from __future__ import annotations


def safe_int(value: object) -> int | None:
    """Coerce a value to int, returning None on a None/malformed input (never raises).

    Chunk ids and claim source_refs arrive as ``str`` or ``int`` on the wire; callers use this
    to accept a valid id and silently drop a malformed or missing one instead of crashing (a
    citation gap must never throw). ``safe_int(None)`` is None, so no separate None guard is
    needed at the call site.
    """
    try:
        return int(value)  # type: ignore[call-overload]
    except (ValueError, TypeError):
        return None
