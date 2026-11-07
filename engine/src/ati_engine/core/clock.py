"""Saat soyutlaması.

Bütün bileşenler zamanı doğrudan ``time`` modülünden değil bir ``Clock`` üzerinden okur.
Böylece aynı strateji kodu canlı piyasada (``SystemClock``) ve geriye dönük testte
(``ManualClock``) değiştirilmeden çalışabilir. Geriye dönük testte gelecekteki veriye
bakma (look-ahead) hatalarını önlemenin ilk adımı budur.
"""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def now_ms(self) -> int:
        """Unix epoch milisaniye (duvar saati)."""
        ...

    def monotonic(self) -> float:
        """Süre ölçümü için monoton saniye."""
        ...


class SystemClock:
    def now_ms(self) -> int:
        return time.time_ns() // 1_000_000

    def monotonic(self) -> float:
        return time.monotonic()


class ManualClock:
    """Testler ve geriye dönük test motoru için elle ilerletilen saat."""

    def __init__(self, start_ms: int = 0) -> None:
        self._now_ms = start_ms
        self._mono = 0.0

    def now_ms(self) -> int:
        return self._now_ms

    def monotonic(self) -> float:
        return self._mono

    def advance(self, ms: int) -> None:
        if ms < 0:
            raise ValueError("Saat geriye alınamaz")
        self._now_ms += ms
        self._mono += ms / 1000.0

    def set(self, now_ms: int) -> None:
        if now_ms < self._now_ms:
            raise ValueError("Saat geriye alınamaz")
        self.advance(now_ms - self._now_ms)


def now_ms() -> int:
    return time.time_ns() // 1_000_000
