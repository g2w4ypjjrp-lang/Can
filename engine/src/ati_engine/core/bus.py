"""Asenkron olay veri yolu (publish/subscribe).

Tasarım kararları:

* Her abonenin kendi sınırlı kuyruğu ve kendi tüketici görevi vardır. Yavaş bir abone
  (ör. arayüze veri gönderen WebSocket) hızlı bir aboneyi (ör. risk motoru) yavaşlatamaz.
* Taşma politikası abone başına seçilir:
    - ``DROP_OLDEST``: piyasa verisi gibi "son değer önemlidir" akışları için.
    - ``DROP_NEWEST``: düşük öncelikli tanılama akışları için.
    - ``BLOCK``: emir, risk ve denetim kaydı gibi asla kaybolmaması gereken olaylar için;
      yayıncı, kuyrukta yer açılana kadar bekler (geri basınç).
* Abonelik bir sınıfa yapılır ve alt sınıfları da kapsar (``Event`` aboneliği her şeyi alır).
* Bir abonenin işleyicisinde oluşan hata diğer aboneleri etkilemez; sayılır ve loglanır.
* Abone başına sıra (FIFO) korunur.

Süreçler arası dağıtım (Aşama 2'de piyasa verisi parçalama/sharding) bu arayüzün
arkasına bir taşıma katmanı eklenerek yapılacaktır; yayıncı ve aboneler değişmez.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ati_engine.core.events import Event

logger = logging.getLogger(__name__)

Handler = Callable[[Any], Awaitable[None] | None]


class OverflowPolicy(StrEnum):
    BLOCK = "block"
    DROP_OLDEST = "drop_oldest"
    DROP_NEWEST = "drop_newest"


class BusClosedError(RuntimeError):
    pass


@dataclass
class SubscriptionStats:
    received: int = 0
    delivered: int = 0
    dropped: int = 0
    errors: int = 0
    high_water: int = 0


class Subscription:
    def __init__(
        self,
        *,
        event_type: type[Event],
        handler: Handler,
        name: str,
        maxsize: int,
        policy: OverflowPolicy,
    ) -> None:
        if maxsize <= 0:
            raise ValueError("maxsize pozitif olmalı")
        self.event_type = event_type
        self.name = name
        self.policy = policy
        self.stats = SubscriptionStats()
        self._handler = handler
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def maxsize(self) -> int:
        return self._queue.maxsize

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._consume(), name=f"bus:{self.name}")

    async def _consume(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                result = self._handler(event)
                if inspect.isawaitable(result):
                    await result
                self.stats.delivered += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                self.stats.errors += 1
                logger.exception(
                    "Olay işleyicisi hata verdi",
                    extra={"subscription": self.name, "event_type": type(event).__name__},
                )
            finally:
                self._queue.task_done()

    def _track(self) -> None:
        self.stats.received += 1
        size = self._queue.qsize()
        if size > self.stats.high_water:
            self.stats.high_water = size

    def offer(self, event: Event) -> None:
        """Bekletmeyen teslim (DROP_* politikaları)."""
        if self._closed:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            if self.policy is OverflowPolicy.DROP_NEWEST:
                self.stats.dropped += 1
                return
            # DROP_OLDEST: en eski olayı at, yenisini koy.
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
                self._queue.task_done()
                self.stats.dropped += 1
            self._queue.put_nowait(event)
        self._track()

    async def put(self, event: Event) -> None:
        """Bekleyen teslim (BLOCK politikası)."""
        if self._closed:
            return
        await self._queue.put(event)
        self._track()

    async def drain(self, wait_s: float) -> bool:
        try:
            await asyncio.wait_for(self._queue.join(), timeout=wait_s)
        except TimeoutError:
            return False
        return True

    async def close(self, *, drain_timeout: float = 1.0) -> None:
        if self._task is not None and not self._task.done():
            await self.drain(drain_timeout)
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None


class EventBus:
    def __init__(self) -> None:
        self._subscriptions: dict[type[Event], list[Subscription]] = {}
        self._resolved: dict[type[Event], tuple[Subscription, ...]] = {}
        self._published: dict[str, int] = {}
        self._closed = False

    def subscribe(
        self,
        event_type: type[Event],
        handler: Handler,
        *,
        name: str,
        maxsize: int = 10_000,
        policy: OverflowPolicy = OverflowPolicy.DROP_OLDEST,
    ) -> Subscription:
        if self._closed:
            raise BusClosedError("Olay veri yolu kapalı")
        if not (isinstance(event_type, type) and issubclass(event_type, Event)):
            raise TypeError("Yalnızca Event alt sınıflarına abone olunabilir")
        sub = Subscription(
            event_type=event_type, handler=handler, name=name, maxsize=maxsize, policy=policy
        )
        self._subscriptions.setdefault(event_type, []).append(sub)
        self._resolved.clear()
        sub.start()
        return sub

    async def unsubscribe(self, sub: Subscription) -> None:
        subs = self._subscriptions.get(sub.event_type, [])
        if sub in subs:
            subs.remove(sub)
            self._resolved.clear()
        await sub.close(drain_timeout=0)

    def _resolve(self, event_type: type[Event]) -> tuple[Subscription, ...]:
        cached = self._resolved.get(event_type)
        if cached is not None:
            return cached
        result: list[Subscription] = []
        for klass in event_type.__mro__:
            subs = self._subscriptions.get(klass)
            if subs:
                result.extend(subs)
        resolved = tuple(result)
        self._resolved[event_type] = resolved
        return resolved

    async def publish(self, event: Event) -> None:
        if self._closed:
            raise BusClosedError("Olay veri yolu kapalı")
        event_type = type(event)
        name = event_type.__name__
        self._published[name] = self._published.get(name, 0) + 1
        for sub in self._resolve(event_type):
            if sub.policy is OverflowPolicy.BLOCK:
                await sub.put(event)
            else:
                sub.offer(event)

    def metrics(self) -> dict[str, Any]:
        subs = [s for group in self._subscriptions.values() for s in group]
        return {
            "published": dict(self._published),
            "subscriptions": [
                {
                    "name": s.name,
                    "event_type": s.event_type.__name__,
                    "policy": s.policy.value,
                    "pending": s.pending,
                    "maxsize": s.maxsize,
                    "received": s.stats.received,
                    "delivered": s.stats.delivered,
                    "dropped": s.stats.dropped,
                    "errors": s.stats.errors,
                    "high_water": s.stats.high_water,
                }
                for s in subs
            ],
        }

    async def close(self, *, drain_timeout: float = 2.0) -> None:
        if self._closed:
            return
        self._closed = True
        subs = [s for group in self._subscriptions.values() for s in group]
        await asyncio.gather(*(s.close(drain_timeout=drain_timeout) for s in subs))
        self._subscriptions.clear()
        self._resolved.clear()
