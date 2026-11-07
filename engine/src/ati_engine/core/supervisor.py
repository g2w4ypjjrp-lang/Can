"""Uzun ömürlü görevlerin denetimi.

Piyasa veri bağlantıları, sağlık izleyicileri gibi sürekli çalışan görevler burada
başlatılır. Bir görev beklenmedik şekilde biterse üstel geri çekilme (exponential
backoff) ile yeniden başlatılır. Belirli bir zaman penceresinde çok fazla çökme olursa
görev "vazgeçildi" durumuna geçer ve ``on_give_up`` çağrılır; motor bu durumda güvenli
moda geçer.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum

logger = logging.getLogger(__name__)


class TaskState(StrEnum):
    RUNNING = "running"
    BACKOFF = "backoff"
    COMPLETED = "completed"
    GAVE_UP = "gave_up"
    STOPPED = "stopped"


@dataclass(frozen=True)
class RestartPolicy:
    restart: bool = True
    max_restarts: int = 5
    window_s: float = 60.0
    backoff_initial_s: float = 0.5
    backoff_max_s: float = 30.0


@dataclass
class TaskStatus:
    name: str
    state: TaskState
    restarts: int = 0
    last_error: str | None = None
    _crash_times: deque[float] = field(default_factory=deque, repr=False)


GiveUpCallback = Callable[[str, BaseException | None], Awaitable[None]]


class TaskSupervisor:
    def __init__(self, *, on_give_up: GiveUpCallback | None = None) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._status: dict[str, TaskStatus] = {}
        self._on_give_up = on_give_up

    def spawn(
        self,
        name: str,
        factory: Callable[[], Awaitable[None]],
        policy: RestartPolicy | None = None,
    ) -> None:
        if name in self._tasks and not self._tasks[name].done():
            raise ValueError(f"'{name}' adlı görev zaten çalışıyor")
        status = TaskStatus(name=name, state=TaskState.RUNNING)
        self._status[name] = status
        self._tasks[name] = asyncio.create_task(
            self._run(name, factory, policy or RestartPolicy(), status), name=f"sup:{name}"
        )

    async def _run(
        self,
        name: str,
        factory: Callable[[], Awaitable[None]],
        policy: RestartPolicy,
        status: TaskStatus,
    ) -> None:
        backoff = policy.backoff_initial_s
        while True:
            status.state = TaskState.RUNNING
            error: BaseException | None = None
            try:
                await factory()
            except asyncio.CancelledError:
                status.state = TaskState.STOPPED
                raise
            except Exception as exc:
                error = exc
                status.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Denetlenen görev çöktü", extra={"task": name})
            else:
                if not policy.restart:
                    status.state = TaskState.COMPLETED
                    return
                logger.warning(
                    "Denetlenen görev beklenmedik şekilde sonlandı", extra={"task": name}
                )

            if not policy.restart:
                status.state = TaskState.GAVE_UP
                await self._give_up(name, error)
                return

            now = time.monotonic()
            status._crash_times.append(now)
            while status._crash_times and now - status._crash_times[0] > policy.window_s:
                status._crash_times.popleft()
            if len(status._crash_times) > policy.max_restarts:
                status.state = TaskState.GAVE_UP
                await self._give_up(name, error)
                return

            status.state = TaskState.BACKOFF
            status.restarts += 1
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, policy.backoff_max_s)

    async def _give_up(self, name: str, error: BaseException | None) -> None:
        logger.error("Görev yeniden başlatılmaktan vazgeçildi", extra={"task": name})
        if self._on_give_up is not None:
            try:
                await self._on_give_up(name, error)
            except Exception:
                logger.exception("on_give_up geri çağrısı hata verdi", extra={"task": name})

    def status(self) -> list[TaskStatus]:
        return list(self._status.values())

    async def stop(self, name: str) -> None:
        task = self._tasks.pop(name, None)
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self._status[name].state = TaskState.STOPPED

    async def stop_all(self) -> None:
        for name in list(self._tasks):
            await self.stop(name)
