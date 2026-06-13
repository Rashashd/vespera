"""Unit tests for stack-free components (adapter, dispatcher, audit wiring, deps, factories)."""

from types import SimpleNamespace

import pytest

from app.audit.handler import _target_for, audit_log_handler, register_audit_handlers
from app.audit.models import AuditLog
from app.core.config import Settings, get_settings
from app.core.dependencies import get_redis, get_settings_dep
from app.core.dispatcher import EventDispatcher
from app.core.startup import check_model_artifacts
from app.db.base import create_engine, create_session_factory
from app.domain.events import ClientErased, DomainEvent, FindingClassified, ReportApproved
from app.infra.llm_adapter import build_llm_client


# --- LLM adapter ---
def test_adapter_prefers_anthropic():
    assert build_llm_client(Settings(anthropic_api_key="a")).provider == "anthropic"


def test_adapter_falls_back_to_openai():
    assert build_llm_client(Settings(openai_api_key="o")).provider == "openai"


def test_adapter_raises_without_key():
    with pytest.raises(RuntimeError):
        build_llm_client(Settings())


# --- dispatcher ---
async def test_dispatch_invokes_handlers_in_order():
    dispatcher = EventDispatcher()
    calls: list[int] = []
    dispatcher.register(FindingClassified, lambda e, s: _append(calls, 1))
    dispatcher.register(FindingClassified, lambda e, s: _append(calls, 2))
    await dispatcher.dispatch(FindingClassified(actor_id=0, actor_type="system"), session=None)
    assert calls == [1, 2]


async def test_dispatch_unregistered_event_is_noop():
    await EventDispatcher().dispatch(ClientErased(actor_id=0, actor_type="system"), session=None)


async def _append(target: list[int], value: int) -> None:
    target.append(value)


# --- audit wiring ---
def test_register_audit_handlers_covers_all_event_types():
    dispatcher = EventDispatcher()
    register_audit_handlers(dispatcher)
    for event_type in (FindingClassified, ReportApproved, ClientErased):
        assert audit_log_handler in dispatcher._handlers[event_type]


def test_target_for_each_event_kind():
    finding = FindingClassified(actor_id=0, actor_type="system", finding_id=3)
    erased = ClientErased(actor_id=0, actor_type="system", erased_client_id=9)
    assert _target_for(finding) == "finding:3"
    assert _target_for(erased) == "client:9"
    assert _target_for(DomainEvent(actor_id=0, actor_type="system")) == "DomainEvent"


async def test_handler_writes_one_row():
    added: list[object] = []
    session = SimpleNamespace(add=added.append)
    event = FindingClassified(actor_id=0, actor_type="system", finding_id=1)
    await audit_log_handler(event, session)
    assert len(added) == 1 and isinstance(added[0], AuditLog)


# --- dependencies ---
def test_dependency_providers_return_state():
    state = SimpleNamespace(settings="S", redis="R")
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    assert get_settings_dep(request) == "S"
    assert get_redis(request) == "R"


# --- db factories + misc ---
def test_engine_and_session_factory_build():
    engine = create_engine("postgresql+asyncpg://u:p@localhost:5432/db")
    assert create_session_factory(engine) is not None


def test_get_settings_and_model_artifacts_noop():
    assert isinstance(get_settings(), Settings)
    assert check_model_artifacts(Settings()) is None
