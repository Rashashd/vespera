"""Public facade for report operations — re-exports from drafting/ and review/.

Implementation lives in:
- app/reports/drafting.py  — create_expedited_report, create_followup, persist_operator_alert
- app/reports/review.py    — approve/edit/reject/discard + per-finding drop/discard
- app/reports/_helpers.py  — shared load/transition helpers
"""

from app.reports.drafting import (
    create_expedited_report,
    create_followup,
    persist_operator_alert,
)
from app.reports.review import (
    approve_report,
    discard_finding_permanently,
    discard_report,
    drop_finding_from_report,
    edit_approve_report,
    reject_report,
)

__all__ = [
    "create_expedited_report",
    "create_followup",
    "persist_operator_alert",
    "approve_report",
    "edit_approve_report",
    "reject_report",
    "discard_report",
    "drop_finding_from_report",
    "discard_finding_permanently",
]
