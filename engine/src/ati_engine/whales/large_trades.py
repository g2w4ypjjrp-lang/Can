"""Uyarlanabilir büyük işlem (balina emri) tespiti.

**Süpürme birleştirme:** Binance, birden çok fiyat kademesini tek seferde alan bir piyasa emrini
her kademe için ayrı ``aggTrade`` olarak yayınlar; bunların işlem zamanı (``T``) ve yönü
aynıdır. ``SweepAggregator`` bu parçaları tek bir "agresif emir" olarak birleştirir; aksi halde
büyük bir emir birkaç küçük işleme bölünüp gözden kaçardı.

**Sembole göre eşik:** Her sembolün emir büyüklüğü dağılımı logaritmik kovalı ve üstel
sönümlü bir histogramda tutulur (``LogHistogram``). Balina eşiği bu dağılımın yüksek bir
yüzdeliği (varsayılan %99,9) olur ve ayarlanabilir bir tabanın altına inmez. BTC'de 300 bin
dolarlık bir emir sıradan olabilirken küçük bir coinde 50 bin dolar olağanüstüdür.
"""

from __future__ import annotations

import math
from array import array
from dataclasses import dataclass


class LogHistogram:
    """log10(tutar) ölçeğinde kovalı, üstel sönümlü dağılım.

    Sönüm "tembel" uygulanır: her yeni gözlemin ağırlığı bir öncekinden ``growth`` kat
    büyüktür; böylece eski gözlemlerin göreli ağırlığı her adımda azalır ve hiçbir kova tek
    tek çarpılmaz. Ağırlıklar çok büyüyünce tümü yeniden ölçeklenir.
    """

    LOW = 0.0  # 1 USDT
    HIGH = 10.0  # 10 milyar USDT
    STEP = 0.05
    BINS = int((HIGH - LOW) / STEP)
    __slots__ = ("_bins", "_growth", "_total", "_weight", "count")

    def __init__(self, half_life: int = 50_000) -> None:
        if half_life < 10:
            raise ValueError("Yarı ömür en az 10 gözlem olmalı")
        self._bins = array("d", [0.0]) * self.BINS
        self._growth = 2.0 ** (1.0 / half_life)
        self._weight = 1.0
        self._total = 0.0
        self.count = 0

    def add(self, value: float) -> None:
        if value <= 0:
            return
        idx = int((math.log10(value) - self.LOW) / self.STEP)
        idx = min(max(idx, 0), self.BINS - 1)
        self._bins[idx] += self._weight
        self._total += self._weight
        self._weight *= self._growth
        self.count += 1
        if self._weight > 1e200:
            scale = 1.0 / self._weight
            for i in range(self.BINS):
                self._bins[i] *= scale
            self._total *= scale
            self._weight = 1.0

    def quantile(self, q: float) -> float | None:
        """``q`` yüzdeliğinin üst kova sınırı (ör. 0.999). Gözlem yoksa None."""
        if self._total <= 0:
            return None
        target = (1.0 - q) * self._total
        cumulative = 0.0
        for idx in range(self.BINS - 1, -1, -1):
            cumulative += self._bins[idx]
            if cumulative >= target:
                return 10 ** (self.LOW + (idx + 1) * self.STEP)
        return 10**self.LOW


@dataclass
class TakerOrder:
    """Aynı anda aynı yönde gerçekleşen işlemlerin birleşimi (tek bir agresif emir)."""

    symbol: str
    time_ms: int
    taker_buy: bool
    notional: float = 0.0
    qty: float = 0.0
    first_price: float = 0.0
    last_price: float = 0.0
    fills: int = 0

    @property
    def avg_price(self) -> float:
        return self.notional / self.qty if self.qty else self.last_price

    @property
    def side(self) -> str:
        return "buy" if self.taker_buy else "sell"

    @property
    def price_impact_pct(self) -> float:
        """Emrin kendi süpürdüğü fiyat aralığı (%)."""
        if self.first_price <= 0:
            return 0.0
        return abs(self.last_price / self.first_price - 1.0) * 100.0


class SweepAggregator:
    """Sembol başına bekleyen emir; zaman damgası veya yön değişince tamamlanır."""

    def __init__(self) -> None:
        self._pending: dict[str, TakerOrder] = {}

    def add(
        self, symbol: str, time_ms: int, price: float, qty: float, *, taker_buy: bool
    ) -> TakerOrder | None:
        """İşlemi ekler; önceki emir tamamlandıysa onu döner."""
        current = self._pending.get(symbol)
        completed = None
        if current is not None and (current.time_ms != time_ms or current.taker_buy != taker_buy):
            completed = current
            current = None
        if current is None:
            current = TakerOrder(
                symbol=symbol, time_ms=time_ms, taker_buy=taker_buy, first_price=price
            )
            self._pending[symbol] = current
        current.notional += price * qty
        current.qty += qty
        current.last_price = price
        current.fills += 1
        return completed

    def flush(self, older_than_ms: int) -> list[TakerOrder]:
        """``older_than_ms`` öncesine ait bekleyen emirleri tamamlar (sessiz semboller için)."""
        done = [o for o in self._pending.values() if o.time_ms < older_than_ms]
        for order in done:
            del self._pending[order.symbol]
        return done


class WhaleThresholds:
    """Sembol başına balina eşiği: max(taban, dağılımın yüksek yüzdeliği)."""

    def __init__(
        self,
        *,
        floor_usd: float,
        quantile: float = 0.999,
        min_samples: int = 2_000,
        half_life: int = 50_000,
        refresh_every: int = 200,
    ) -> None:
        self._floor = floor_usd
        self._q = quantile
        self._min_samples = min_samples
        self._half_life = half_life
        self._refresh = refresh_every
        self._hist: dict[str, LogHistogram] = {}
        self._cached: dict[str, float] = {}

    def observe(self, symbol: str, notional: float) -> None:
        hist = self._hist.get(symbol)
        if hist is None:
            hist = self._hist[symbol] = LogHistogram(self._half_life)
        hist.add(notional)
        if hist.count >= self._min_samples and hist.count % self._refresh == 0:
            value = hist.quantile(self._q)
            if value is not None:
                self._cached[symbol] = value

    def threshold(self, symbol: str) -> float:
        return max(self._floor, self._cached.get(symbol, 0.0))

    def learned(self, symbol: str) -> bool:
        return symbol in self._cached
