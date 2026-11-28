"""Celery çalışanı:  celery -A bizcenter.worker worker -l info"""

import asyncio
from uuid import UUID

from celery import Celery

from .config import get_settings
from .db import Database
from .dispatch import CeleryDispatcher, make_orchestrator
from .middleware import setup_logging
from .scheduler import tick

settings = get_settings()
app = Celery("bizcenter", broker=settings.redis_url or "redis://localhost:6379/0")
app.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, task_reject_on_worker_lost=True,
                worker_hijack_root_logger=False,
                beat_schedule={"scheduler-tick": {"task": "bizcenter.tick", "schedule": 60.0}})
setup_logging()


async def _run(task_id: str) -> None:
    db = Database(settings.database_url, 2)
    await db.open()
    try:
        await make_orchestrator(settings, db).run(UUID(task_id))
    finally:
        await db.close()


@app.task(name="bizcenter.run_task")
def run_task(task_id: str) -> None:
    asyncio.run(_run(task_id))


async def _tick() -> None:
    db = Database(settings.database_url, 2)
    await db.open()
    try:
        await tick(db, CeleryDispatcher(), settings.max_active_tasks_per_org,
                   task_timeout_minutes=settings.task_timeout_minutes)
    finally:
        await db.close()


@app.task(name="bizcenter.tick")
def scheduler_tick() -> None:
    asyncio.run(_tick())
