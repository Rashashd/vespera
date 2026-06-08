"""Unit tests for client schema validation (name trim/non-empty; status not API-settable)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.clients.schemas import ClientRead, ClientUpdate, WatchlistCreate


def test_client_update_trims_name():
    """A surrounding-whitespace name is trimmed."""
    assert ClientUpdate(name="  Acme Pharma  ").name == "Acme Pharma"


def test_client_update_rejects_empty_name():
    """An all-whitespace name is rejected (FR-001)."""
    with pytest.raises(ValidationError):
        ClientUpdate(name="   ")


def test_client_update_allows_omitted_name():
    """Name is optional on PATCH (no-op update is valid)."""
    assert ClientUpdate().name is None


def test_client_update_has_no_status_field():
    """`status` is operator-only and must not be settable via the API (contract)."""
    assert "status" not in ClientUpdate.model_fields


def test_client_read_from_attributes():
    """ClientRead reads straight from an ORM-like object."""
    now = datetime.now(UTC)
    attrs = {"id": 3, "name": "Acme", "status": "active", "created_at": now, "updated_at": now}
    obj = type("Row", (), attrs)()
    read = ClientRead.model_validate(obj)
    assert read.id == 3 and read.status == "active"


def test_watchlist_create_requires_items_field():
    """`items` is a required field; omitting it is a validation error (≥1 enforced downstream)."""
    with pytest.raises(ValidationError):
        WatchlistCreate(name="X")
