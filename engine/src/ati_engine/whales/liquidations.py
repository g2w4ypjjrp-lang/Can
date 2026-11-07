"""Futures zorunlu tasfiyeleri: büyük tasfiyeler ve tasfiye zincirleri.

Binance ``!forceOrder@arr`` akışında her sembol için saniyede yalnızca **en büyük** tasfiye
emrini yayınlar. Bu yüzden buradaki toplamlar gerçek toplamın **alt sınırıdır**.

Yön: tasfiye emri ``SELL`` ise bir **long** pozisyon zorla kapatılmıştır (fiyata satış
baskısı); ``BUY`` ise bir **short** pozisyon kapatılmıştır (alış baskısı).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from ati_engine.market.events import Liquidation


def liquidation_notional(event: Liquidation) -> float:
    price = event.avg_price or event.price
    qty = event.filled_qty or event.qty
    return price * qty


@dataclass(frozen=True)
class CascadeResult:
    symbol: str
    liquidated: str  # "long" | "short"
    count: int
    notional: float
    window_s: int


class LiquidationMonitor:
    def __init__(
        self,
        *,
        min_notional: float = 100_000,
        window_s: int = 60,
        cascade_min_notional: float = 1_000_000,
        cascade_min_count: int = 3,
    ) -> None:
        self.min_notional = min_notional
        self._window_ms = window_s * 1000
        self._window_s = window_s
        self._cascade_notional = cascade_min_notional
        self._cascade_count = cascade_min_count
        self._recent: dict[tuple[str, str], deque[tuple[int, float]]] = {}
        self._all: deque[tuple[int, str, float]] = deque()

    def add(self, event: Liquidation) -> CascadeResult | None:
        notional = liquidation_notional(event)
        liquidated = "long" if event.side == "SELL" else "short"
        now = event.trade_time_ms or event.event_time_ms
        self._all.append((now, liquidated, notional))
        while self._all and now - self._all[0][0] > 3_600_000:
            self._all.popleft()
        recent = self._recent.setdefault((event.symbol, liquidated), deque())
        recent.append((now, notional))
        while recent and now - recent[0][0] > self._window_ms:
            recent.popleft()
        total = sum(n for _, n in recent)
        if len(recent) >= self._cascade_count and total >= self._cascade_notional:
            return CascadeResult(
                symbol=event.symbol,
                liquidated=liquidated,
                count=len(recent),
                notional=total,
                window_s=self._window_s,
            )
        return None

    def totals(self, now_ms: int, window_s: int = 300) -> dict[str, float]:
        """Son ``window_s`` saniyede tüm piyasadaki long/short tasfiye toplamı (alt sınır)."""
        cutoff = now_ms - window_s * 1000
        result = {"long": 0.0, "short": 0.0}
        for ts, liquidated, notional in self._all:
            if ts >= cutoff:
                result[liquidated] += notional
        return result
