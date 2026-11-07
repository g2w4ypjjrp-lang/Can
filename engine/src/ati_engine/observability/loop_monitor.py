"""Olay döngüsü gecikme (loop lag) izleyicisi.

Gerçek zamanlı bir işlem motorunda olay döngüsünün tıkanması, piyasa verisinin geç
işlenmesi ve stop emirlerinin gecikmesi demektir. İzleyici belirli aralıklarla uyur ve
planlanandan ne kadar geç uyandığını ölçer. Eşik aşılırsa uyarı verilir; Aşama 2'de
piyasa verisi parçalama (sharding) kararları bu ölçüme göre ayarlanır.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque


class LoopLagMonitor:
    def __init__(self, *, interval_s: float = 0.25, window: int = 240) -> None:
        self._interval = interval_s
        self._samples: deque[float] = deque(maxlen=window)
        self._last_ms = 0.0

    @property
    def last_ms(self) -> float:
        return self._last_ms

    @property
    def max_ms(self) -> float:
        return max(self._samples, default=0.0)

    def p99_ms(self) -> float:
        if not self._samples:
            return 0.0
        ordered = sorted(self._samples)
        index = min(len(ordered) - 1, round(0.99 * (len(ordered) - 1)))
        return ordered[index]

    def record(self, lag_ms: float) -> None:
        self._last_ms = max(0.0, lag_ms)
        self._samples.append(self._last_ms)

    async def run(self) -> None:
        while True:
            start = time.perf_counter()
            await asyncio.sleep(self._interval)
            elapsed = time.perf_counter() - start
            self.record((elapsed - self._interval) * 1000.0)
