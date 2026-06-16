"""Public facade for the clients domain — re-exports from accounts/, watchlists/, _helpers/.

Implementation lives in:
- app/clients/accounts.py    — client lifecycle + client-user management
- app/clients/watchlists.py  — watchlist queries/mutations + budget usage
- app/clients/_helpers.py     — shared exceptions and pure helpers
"""

from app.clients._helpers import (
    WARNING_FRACTION,
    CrossClientWatchlist,
    InvalidEmail,
    NameConflict,
    ScopeRequired,
    WatchlistEmpty,
    _validate_scope,
    current_period_start,
    derive_budget_state,
    validate_email_address,
)
from app.clients.accounts import (
    create_client,
    create_client_user,
    get_client,
    get_client_user,
    list_client_users,
    list_clients,
    reactivate_client,
    rename_client,
    set_client_status,
    set_report_emails,
    set_severity_keywords,
    suspend_client,
    update_client_user_scope,
)
from app.clients.watchlists import (
    add_item,
    create_watchlist,
    current_period_spend,
    get_watchlist,
    item_count,
    list_watchlists,
    read_figures,
    record_spend,
    remove_item,
    rename_watchlist,
    set_active,
)

__all__ = [
    # exceptions
    "NameConflict",
    "WatchlistEmpty",
    "InvalidEmail",
    "ScopeRequired",
    "CrossClientWatchlist",
    # pure helpers
    "WARNING_FRACTION",
    "current_period_start",
    "derive_budget_state",
    "validate_email_address",
    "_validate_scope",
    # client + client-user ops
    "get_client",
    "list_clients",
    "rename_client",
    "create_client",
    "set_client_status",
    "suspend_client",
    "reactivate_client",
    "set_report_emails",
    "set_severity_keywords",
    "create_client_user",
    "list_client_users",
    "get_client_user",
    "update_client_user_scope",
    # watchlist + budget ops
    "get_watchlist",
    "list_watchlists",
    "create_watchlist",
    "rename_watchlist",
    "item_count",
    "set_active",
    "add_item",
    "remove_item",
    "current_period_spend",
    "read_figures",
    "record_spend",
]
