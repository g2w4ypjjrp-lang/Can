"""REST ağırlık (request weight) bütçesi.

Binance REST limitleri IP başınadır ve ``exchangeInfo.rateLimits`` içinde yayımlanır
(Spot ``REQUEST_WEIGHT`` 6000/dk, USDⓈ-M Futures 2400/dk - 2026-11-07 itibarıyla). Limitler
kodda sabit tutulmaz; çalışma anında exchangeInfo'dan okunur.

Bütçe iki kaynaktan beslenir:
1. Yerel tahmin: gönderilen her isteğin ağırlığı mevcut dakika penceresine eklenir.
2. Sunucunun bildirdiği değer: her yanıttaki ``X-MBX-USED-WEIGHT-1M`` başlığı (aynı IP'deki
   başka programların tükettiği ağırlığı da yansıtır).

Öncelik seviyeleri, limite yaklaşıldığında hangi isteklerin bekleyeceğini belirler: geçmiş veri
indirme gibi arka plan işleri (%60) erkenden durur; emir/pozisyon işlemleri (%95) en son durur.

HTTP 429 alınınca ``Retry-After`` süresi boyunca tüm istekler durdurulur. HTTP 418 (IP yasağı)
alınınca yasak bitene kadar hiçbir istek gönderilmez ve ``IpBannedError`` yükseltilir.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from ati_engine.core.clock import Clock, SystemClock

_INTERVAL_MS = {"SECOND": 1_000, "MINUTE": 60_000, "HOUR": 3_600_000, "DAY": 86_400_000}


class Priority(IntEnum):
    LOW = 0  # geçmiş veri indirme, toplu işler
    NORMAL = 1  # emir defteri anlık görüntüsü, keşif
    HIGH = 2  # emir, pozisyon, mutabakat (Aşama 10)


_THRESHOLDS = {Priority.LOW: 0.60, Priority.NORMAL: 0.80, Priority.HIGH: 0.95}


class RateLimitError(RuntimeError):
    def __init__(self, message: str, retry_after_s: float) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class IpBannedError(RateLimitError):
    pass


@dataclass(frozen=True)
class RateLimitRule:
    kind: str
    interval_ms: int
    limit: int


def parse_rate_limits(raw: Iterable[Mapping[str, Any]]) -> list[RateLimitRule]:
    rules: list[RateLimitRule] = []
    for item in raw:
        unit = _INTERVAL_MS.get(str(item.get("interval")))
        if unit is None:
            continue
        rules.append(
            RateLimitRule(
                kind=str(item["rateLimitType"]),
                interval_ms=unit * int(item.get("intervalNum", 1)),
                limit=int(item["limit"]),
            )
        )
    return rules


def request_weight_per_minute(rules: Iterable[RateLimitRule]) -> int | None:
    for rule in rules:
        if rule.kind == "REQUEST_WEIGHT" and rule.interval_ms == 60_000:
            return rule.limit
    return None


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


class WeightBudget:
    def __init__(
        self,
        limit_per_minute: int,
        *,
        clock: Clock | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if limit_per_minute <= 0:
            raise ValueError("Limit pozitif olmalı")
        self._limit = limit_per_minute
        self._clock = clock or SystemClock()
        self._sleep = sleep
        self._window = -1
        self._used = 0
        self._blocked_until_ms = 0
        self._banned = False
        self.waits = 0
        self.total_used = 0

    @property
    def limit(self) -> int:
        return self._limit

    def set_limit(self, limit_per_minute: int) -> None:
        if limit_per_minute > 0:
            self._limit = limit_per_minute

    def _roll(self, now_ms: int) -> None:
        window = now_ms // 60_000
        if window != self._window:
            self._window = window
            self._used = 0

    @property
    def used(self) -> int:
        self._roll(self._clock.now_ms())
        return self._used

    def _ms_until_next_window(self, now_ms: int) -> int:
        return 60_000 - (now_ms % 60_000)

    def delay_for(self, weight: int, priority: Priority) -> float:
        """İsteğin gönderilebilmesi için beklenmesi gereken süre (sn). 0 = hemen."""
        now = self._clock.now_ms()
        self._roll(now)
        if self._blocked_until_ms > now:
            return (self._blocked_until_ms - now) / 1000
        allowed = self._limit * _THRESHOLDS[priority]
        if self._used + weight <= allowed:
            return 0.0
        return self._ms_until_next_window(now) / 1000

    async def acquire(self, weight: int, priority: Priority = Priority.NORMAL) -> None:
        if weight <= 0:
            raise ValueError("Ağırlık pozitif olmalı")
        if weight > self._limit * _THRESHOLDS[Priority.HIGH]:
            raise ValueError(f"İstek ağırlığı ({weight}) dakikalık bütçeyi aşıyor")
        # asyncio tek iş parçacıklıdır: kontrol ile ayırma arasında bekleme olmadığı için kilit
        # gerekmez. Bekleyen düşük öncelikli istek, yüksek öncelikli olanı engellemez.
        while True:
            now = self._clock.now_ms()
            if self._banned and self._blocked_until_ms > now:
                remaining = (self._blocked_until_ms - now) / 1000
                raise IpBannedError("Binance IP yasağı sürüyor", remaining)
            delay = self.delay_for(weight, priority)
            if delay <= 0:
                self._used += weight
                self.total_used += weight
                return
            self.waits += 1
            await self._sleep(delay)

    def update_from_headers(self, headers: Mapping[str, str]) -> None:
        value = _header(headers, "x-mbx-used-weight-1m")
        if value is None:
            return
        try:
            reported = int(value)
        except ValueError:
            return
        self._roll(self._clock.now_ms())
        # Sunucu, aynı IP'deki diğer programların tükettiği ağırlığı da bildirir.
        self._used = max(self._used, reported)

    def on_rate_limited(self, retry_after_s: float) -> None:
        """HTTP 429: belirtilen süre boyunca tüm istekleri durdur."""
        until = self._clock.now_ms() + int(max(retry_after_s, 1.0) * 1000)
        self._blocked_until_ms = max(self._blocked_until_ms, until)

    def on_banned(self, retry_after_s: float) -> None:
        """HTTP 418: IP yasaklandı. Süre bitene kadar istek gönderilmez."""
        self._banned = True
        self.on_rate_limited(retry_after_s)

    def snapshot(self) -> dict[str, Any]:
        now = self._clock.now_ms()
        self._roll(now)
        return {
            "limit_per_minute": self._limit,
            "used": self._used,
            "blocked_for_s": max(0.0, (self._blocked_until_ms - now) / 1000),
            "banned": self._banned and self._blocked_until_ms > now,
            "waits": self.waits,
            "total_used": self.total_used,
        }
