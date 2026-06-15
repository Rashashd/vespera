"""WorkerContext shim: duck-types app.state so stage runners work unchanged in ARQ jobs."""

from __future__ import annotations

from typing import Any


class WorkerContext:
    """Thin wrapper around ARQ's ctx dict; exposes the same attrs as app.state.

    Built in each task from the ARQ ctx so callers like draft_expedited / redraft_report
    that read app_state.{settings,session_factory,redis,dispatcher,llm} work unchanged.
    ctx['redis'] IS an ArqRedis (enqueue_job available) — exposed as both .redis and .arq.
    """

    __slots__ = ("settings", "session_factory", "redis", "arq", "dispatcher", "llm")

    def __init__(self, ctx: dict[str, Any]) -> None:
        self.settings = ctx["settings"]
        self.session_factory = ctx["session_factory"]
        self.redis = ctx["redis"]  # ArqRedis — supports enqueue_job
        self.arq = ctx["redis"]  # same object; alias used by enqueue()
        self.dispatcher = ctx["dispatcher"]
        self.llm = ctx.get("llm")
