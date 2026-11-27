"""Görev dağıtımı: Redis varsa Celery kuyruğu, yoksa süreç içi arka plan görevi."""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from .agents.llm import LLM, ClaudeLLM, LLMError
from .agents.orchestrator import Orchestrator
from .config import Settings
from .db import Database

log = logging.getLogger("bizcenter.dispatch")


class Dispatcher(Protocol):
    def enqueue(self, task_id: UUID) -> None: ...


def build_llm(settings: Settings) -> LLM:
    return ClaudeLLM(settings.anthropic_api_key, settings.llm_model, settings.max_web_searches_per_call)


class _NoKeyLLM:
    async def complete(self, **_: object):  # type: ignore[no-untyped-def]
        raise LLMError("Anthropic API anahtarı yapılandırılmadı (BC_ANTHROPIC_API_KEY)")


def make_orchestrator(settings: Settings, db: Database, llm: LLM | None = None) -> Orchestrator:
    if llm is None:
        llm = build_llm(settings) if settings.anthropic_api_key else _NoKeyLLM()
    return Orchestrator(db, llm, settings.llm_model, Decimal(str(settings.max_task_cost_usd)))


class InlineDispatcher:
    def __init__(self, orchestrator: Orchestrator) -> None:
        self.orch = orchestrator
        self.tasks: set[asyncio.Task[None]] = set()

    def enqueue(self, task_id: UUID) -> None:
        t = asyncio.create_task(self.orch.run(task_id))
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)

    async def drain(self) -> None:
        while self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)


class CeleryDispatcher:
    def enqueue(self, task_id: UUID) -> None:
        from .worker import run_task

        run_task.delay(str(task_id))
