from __future__ import annotations

import asyncio
import time

import pytest

from ati_engine.core.bus import BusClosedError, EventBus, OverflowPolicy
from ati_engine.core.events import Alert, Event, Heartbeat, KillSwitchEngaged
from ati_engine.core.models import EngineState, Severity, TradingMode


def _hb(i: int) -> Heartbeat:
    return Heartbeat(
        uptime_s=float(i),
        loop_lag_ms=0.0,
        state=EngineState.RUNNING,
        trading_mode=TradingMode.PAPER,
    )


async def _settle(bus: EventBus) -> None:
    for _ in range(50):
        await asyncio.sleep(0)


async def test_delivers_in_order(bus: EventBus) -> None:
    received: list[float] = []
    bus.subscribe(Heartbeat, lambda e: received.append(e.uptime_s), name="t")
    for i in range(100):
        await bus.publish(_hb(i))
    await _settle(bus)
    assert received == [float(i) for i in range(100)]


async def test_base_class_subscription_receives_subclasses(bus: EventBus) -> None:
    got: list[str] = []
    bus.subscribe(Event, lambda e: got.append(type(e).__name__), name="all")
    bus.subscribe(KillSwitchEngaged, lambda e: got.append("specific"), name="ks")
    await bus.publish(_hb(1))
    await bus.publish(KillSwitchEngaged(reason="test", actor="t"))
    await _settle(bus)
    assert sorted(got) == ["Heartbeat", "KillSwitchEngaged", "specific"]


async def test_handler_error_is_isolated(bus: EventBus) -> None:
    good: list[int] = []

    def bad(_: Event) -> None:
        raise RuntimeError("boom")

    bad_sub = bus.subscribe(Heartbeat, bad, name="bad")
    bus.subscribe(Heartbeat, lambda e: good.append(1), name="good")
    for i in range(3):
        await bus.publish(_hb(i))
    await _settle(bus)
    assert len(good) == 3
    assert bad_sub.stats.errors == 3


async def test_drop_oldest_keeps_latest(bus: EventBus) -> None:
    gate = asyncio.Event()
    seen: list[float] = []

    async def slow(e: Heartbeat) -> None:
        await gate.wait()
        seen.append(e.uptime_s)

    sub = bus.subscribe(Heartbeat, slow, name="slow", maxsize=3, policy=OverflowPolicy.DROP_OLDEST)
    await bus.publish(_hb(0))
    await _settle(bus)  # 0 işleyicide bekliyor
    for i in range(1, 11):
        await bus.publish(_hb(i))
    gate.set()
    await _settle(bus)
    assert seen == [0.0, 8.0, 9.0, 10.0]
    assert sub.stats.dropped == 7


async def test_drop_newest_keeps_earliest(bus: EventBus) -> None:
    gate = asyncio.Event()
    seen: list[float] = []

    async def slow(e: Heartbeat) -> None:
        await gate.wait()
        seen.append(e.uptime_s)

    sub = bus.subscribe(Heartbeat, slow, name="slow", maxsize=2, policy=OverflowPolicy.DROP_NEWEST)
    await bus.publish(_hb(0))
    await _settle(bus)
    for i in range(1, 6):
        await bus.publish(_hb(i))
    gate.set()
    await _settle(bus)
    assert seen == [0.0, 1.0, 2.0]
    assert sub.stats.dropped == 3


async def test_block_policy_applies_backpressure_and_loses_nothing(bus: EventBus) -> None:
    seen: list[float] = []

    async def slow(e: Heartbeat) -> None:
        await asyncio.sleep(0.001)
        seen.append(e.uptime_s)

    bus.subscribe(Heartbeat, slow, name="critical", maxsize=2, policy=OverflowPolicy.BLOCK)
    for i in range(50):
        await bus.publish(_hb(i))
    for _ in range(200):
        if len(seen) == 50:
            break
        await asyncio.sleep(0.005)
    assert seen == [float(i) for i in range(50)]


async def test_unsubscribe_and_close(bus: EventBus) -> None:
    got: list[int] = []
    sub = bus.subscribe(Alert, lambda e: got.append(1), name="a")
    await bus.unsubscribe(sub)
    await bus.publish(Alert(severity=Severity.INFO, title="x", message="y"))
    await _settle(bus)
    assert got == []
    await bus.close()
    with pytest.raises(BusClosedError):
        await bus.publish(Alert(severity=Severity.INFO, title="x", message="y"))


async def test_subscribe_rejects_non_events(bus: EventBus) -> None:
    with pytest.raises(TypeError):
        bus.subscribe(int, lambda e: None, name="x")  # type: ignore[arg-type]


async def test_metrics(bus: EventBus) -> None:
    bus.subscribe(Heartbeat, lambda e: None, name="m")
    await bus.publish(_hb(1))
    await _settle(bus)
    metrics = bus.metrics()
    assert metrics["published"]["Heartbeat"] == 1
    assert metrics["subscriptions"][0]["delivered"] == 1


async def test_throughput(bus: EventBus) -> None:
    """Aşama 2 piyasa verisi yükü için alt sınır: tek çekirdekte >= 50k olay/sn."""
    count = 0

    def handler(_: Heartbeat) -> None:
        nonlocal count
        count += 1

    bus.subscribe(Heartbeat, handler, name="perf", maxsize=200_000)
    events = [_hb(i) for i in range(100_000)]
    start = time.perf_counter()
    for event in events:
        await bus.publish(event)
    while count < len(events):
        await asyncio.sleep(0)
    elapsed = time.perf_counter() - start
    rate = len(events) / elapsed
    print(f"olay veri yolu: {rate:,.0f} olay/sn")
    assert rate > 50_000
