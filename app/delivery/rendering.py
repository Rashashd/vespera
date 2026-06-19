"""Render an approved report into the self-contained HTML document delivered to the client."""

from __future__ import annotations

import html
from typing import Any

# Minimal inline styling — NO external CSS/JS/fonts/images (this artifact is emailed, SFTP'd, and
# downloaded, so it must render offline with zero external requests; PDF-conversion friendly).
_STYLE = (
    "<style>"
    "body{font-family:Georgia,'Times New Roman',serif;max-width:760px;margin:2rem auto;"
    "padding:0 1rem;line-height:1.55;color:#1a1a1a}"
    "h1{font-size:1.5rem;margin-bottom:.2rem}"
    "h2{font-size:1.1rem;border-bottom:1px solid #ddd;padding-bottom:.2rem;margin-top:1.6rem}"
    ".meta{color:#555;font-size:.9em}"
    ".provenance{color:#777;font-size:.82em}"
    "ul.references{list-style:none;padding-left:0}"
    "ul.references li{margin:.3rem 0;font-size:.92em}"
    "a.cite{color:#0a5ad6;text-decoration:none;font-variant-position:super;font-size:.85em}"
    ".narrative{white-space:pre-wrap}"
    "</style>"
)


def _esc(value: Any) -> str:
    """HTML-escape a value (None → empty string)."""
    return html.escape(str(value)) if value is not None else ""


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """Read a field from either a dict or an object."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _ref_by_chunk(sources: list) -> dict[int, int]:
    """Map a passage chunk id → its 1-based reference number (first source wins for a shared chunk).

    Mirrors the int()-coercion pattern in app/reports/passages.py:42-54 — both chunk ids and claim
    source_refs may be str or int on the wire. Never raises on a malformed entry.
    """
    by_chunk: dict[int, int] = {}
    for idx, src in enumerate(sources, start=1):
        for cid in _attr(src, "passage_chunk_ids", None) or []:
            try:
                by_chunk.setdefault(int(cid), idx)
            except (ValueError, TypeError):
                continue
    return by_chunk


def _claim_ref(claim: Any, by_chunk: dict[int, int]) -> int | None:
    """Resolve a claim's source_ref (chunk id, str|int|None) to a reference number, or None.

    A None / unresolvable / malformed source_ref yields None so the claim renders without a number
    — a citation gap must never throw (rendering failure would hold the report, FR-002).
    """
    ref = _attr(claim, "source_ref", None)
    if ref is None:
        return None
    try:
        return by_chunk.get(int(ref))
    except (ValueError, TypeError):
        return None


def render_report_document(report: Any, findings: Any = ()) -> str:
    """Render a report as one self-contained, journal-style HTML document (no external assets).

    Every grounded claim carries a numbered cross-reference [n] (a clickable in-document anchor)
    into a numbered References list built from the corroboration sources, so a recipient can trace
    each assertion to its exact source (FR-002). Claims with no source_ref (aggregated /
    reviewer-attested) get no number. Includes provenance, the corroboration count, the narrative
    body, and — for batch reports — only the *included* findings (drop/discard excluded, FR-013a).
    This is the delivered email/SFTP body and the download-endpoint response (FR-002/FR-017).
    """
    report_id = _esc(_attr(report, "id", ""))
    report_type = _esc(_attr(report, "report_type", ""))
    status = _esc(_attr(report, "status", ""))
    claims = _attr(report, "structured_fields", None) or []
    corroboration_count = _attr(report, "corroboration_count", 0)
    sources = list(_attr(report, "corroboration_sources", None) or [])
    body = _attr(report, "draft_body", None) or ""

    by_chunk = _ref_by_chunk(sources)

    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Pantera report {report_id}</title>",
        _STYLE,
        "</head><body>",
        f"<h1>Pharmacovigilance Report #{report_id}</h1>",
        f'<p class="meta">Type: {report_type} &middot; Status: {status} &middot; '
        f"Corroborating sources: {_esc(corroboration_count)}</p>",
        "<h2>Claims</h2><ul>",
    ]
    for c in claims:
        num = _claim_ref(c, by_chunk)
        cite = f' <a class="cite" href="#ref-{num}">[{num}]</a>' if num else ""
        parts.append(
            f'<li>{_esc(_attr(c, "text", ""))} '
            f'<span class="provenance">[{_esc(_attr(c, "provenance", ""))}]</span>{cite}</li>'
        )
    parts.append("</ul>")

    # Batch: render only included findings (drop/discard excluded — FR-013a / Edge Cases).
    included = [f for f in findings if _attr(f, "state", "included") in (None, "included")]
    if included:
        parts.append("<h2>Findings</h2><ul>")
        for f in included:
            parts.append(
                f'<li>{_esc(_attr(f, "drug", ""))} &mdash; {_esc(_attr(f, "reaction", ""))} '
                f'({_esc(_attr(f, "bucket", ""))})</li>'
            )
        parts.append("</ul>")

    parts.append("<h2>Narrative</h2>")
    parts.append(f'<div class="narrative">{_esc(body)}</div>')

    # Numbered References (stable list order); each [n] anchor above jumps to <li id="ref-n">.
    if sources:
        parts.append('<h2>References</h2><ul class="references">')
        for idx, src in enumerate(sources, start=1):
            label = (
                _attr(src, "title", None)
                or _attr(src, "external_id", None)
                or _attr(src, "source", None)
                or f"Source {idx}"
            )
            external_id = _attr(src, "external_id", None)
            reliability = _attr(src, "source_reliability", None)
            extra = ""
            if external_id and external_id != label:
                extra += f" &middot; {_esc(external_id)}"
            if reliability:
                extra += f" ({_esc(reliability)})"
            parts.append(f'<li id="ref-{idx}">[{idx}] {_esc(label)}{extra}</li>')
        parts.append("</ul>")

    parts.append("</body></html>")
    return "\n".join(parts)
