"""Aynı coinde art arda gelen büyük emirlerin kümelenmesi.

Binance hesapları anonimdir; "birden fazla büyük yatırımcı" doğrudan görülemez. Görülebilen,
kısa sürede aynı yönde gelen birden çok balina emridir. Bir pencerede (varsayılan 5 dk) aynı
yönde en az N emir ve toplamda yeterli net tutar varsa kümelenme sayılır: alım yönünde
**birikim (accumulation)**, satım yönünde **dağıtım (distribution)**.

Aynı coinin hem Spot hem Futures piyasasında aynı yönde kümelenme varsa bu ayrıca
işaretlenir (çapraz piyasa teyidi).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from ati_engine.core.models import Market


@dataclass(frozen=True)
class ClusterResult:
    market: Market
    symbol: str
    side: str
    count: int
    notional: float  # kümedeki emirlerin toplamı (yönlü)
    opposite_notional: float  # aynı penceredeki ters yönlü balina emirleri
    window_s: int
    cross_market: bool


def base_asset(symbol: str, quote: str = "USDT") -> str:
    return symbol[: -len(quote)] if symbol.endswith(quote) else symbol


class ClusterDetector:
    def __init__(
        self,
        *,
        window_s: int = 300,
        min_count: int = 3,
        min_notional: float = 500_000,
        quote_asset: str = "USDT",
    ) -> None:
        self._window_ms = window_s * 1000
        self._window_s = window_s
        self._min_count = min_count
        self._min_notional = min_notional
        self._quote = quote_asset
        self._orders: dict[tuple[Market, str], deque[tuple[int, str, float]]] = {}
        # Çapraz piyasa teyidi için: (taban varlık, yön) -> son kümelenme zamanı ve piyasası
        self._recent: dict[tuple[str, str], tuple[int, Market]] = {}

    def _trim(self, orders: deque[tuple[int, str, float]], now_ms: int) -> None:
        while orders and now_ms - orders[0][0] > self._window_ms:
            orders.popleft()

    def add(
        self, market: Market, symbol: str, time_ms: int, side: str, notional: float
    ) -> ClusterResult | None:
        """Balina emrini ekler; kümelenme koşulu sağlanıyorsa sonucu döner."""
        key = (market, symbol)
        orders = self._orders.setdefault(key, deque())
        orders.append((time_ms, side, notional))
        self._trim(orders, time_ms)
        same = [n for _, s, n in orders if s == side]
        opposite = sum(n for _, s, n in orders if s != side)
        total = sum(same)
        if len(same) < self._min_count or total - opposite < self._min_notional:
            return None
        base = base_asset(symbol, self._quote)
        previous = self._recent.get((base, side))
        cross = (
            previous is not None
            and previous[1] is not market
            and time_ms - previous[0] <= self._window_ms
        )
        self._recent[(base, side)] = (time_ms, market)
        return ClusterResult(
            market=market,
            symbol=symbol,
            side=side,
            count=len(same),
            notional=total,
            opposite_notional=opposite,
            window_s=self._window_s,
            cross_market=cross,
        )

    def summary(self, market: Market, now_ms: int) -> dict[str, tuple[int, float, float]]:
        """Pencere içindeki her sembol için (emir sayısı, alış tutarı, satış tutarı)."""
        result: dict[str, tuple[int, float, float]] = {}
        for (m, symbol), orders in self._orders.items():
            if m is not market:
                continue
            self._trim(orders, now_ms)
            if not orders:
                continue
            buy = sum(n for _, s, n in orders if s == "buy")
            sell = sum(n for _, s, n in orders if s == "sell")
            result[symbol] = (len(orders), buy, sell)
        return result
