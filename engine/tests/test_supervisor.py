from __future__ import annotations

import asyncio

from ati_engine.core.supervisor import RestartPolicy, TaskState, TaskSupervisor


async def test_restarts_crashing_task_until_success() -> None:
    attempts = 0
    done = asyncio.Event()

    async def flaky() -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("geçici hata")
        done.set()
        await asyncio.Event().wait()

    sup = TaskSupervisor()
    sup.spawn("flaky", flaky, RestartPolicy(backoff_initial_s=0.001, backoff_max_s=0.01))
    await asyncio.wait_for(done.wait(), timeout=2)
    status = sup.status()[0]
    assert status.restarts == 2
    assert status.state is TaskState.RUNNING
    assert status.last_error is not None and "geçici hata" in status.last_error
    await sup.stop_all()
    assert sup.status()[0].state is TaskState.STOPPED


async def test_gives_up_after_too_many_crashes() -> None:
    gave_up: list[str] = []

    async def on_give_up(name: str, error: BaseException | None) -> None:
        gave_up.append(name)

    async def always_fails() -> None:
        raise ValueError("kalıcı hata")

    sup = TaskSupervisor(on_give_up=on_give_up)
    sup.spawn(
        "bad",
        always_fails,
        RestartPolicy(max_restarts=3, window_s=60, backoff_initial_s=0.001, backoff_max_s=0.001),
    )
    for _ in range(200):
        if gave_up:
            break
        await asyncio.sleep(0.005)
    assert gave_up == ["bad"]
    assert sup.status()[0].state is TaskState.GAVE_UP
    assert sup.status()[0].restarts == 3


async def test_non_restarting_task_completes() -> None:
    async def once() -> None:
        return None

    sup = TaskSupervisor()
    sup.spawn("once", once, RestartPolicy(restart=False))
    await asyncio.sleep(0.01)
    assert sup.status()[0].state is TaskState.COMPLETED


async def test_duplicate_name_rejected() -> None:
    sup = TaskSupervisor()
    sup.spawn("x", lambda: asyncio.Event().wait())
    try:
        import pytest

        with pytest.raises(ValueError, match="zaten"):
            sup.spawn("x", lambda: asyncio.Event().wait())
    finally:
        await sup.stop_all()
