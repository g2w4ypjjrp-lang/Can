"""Balina radarının Binance işlem arşivi üzerinde yeniden oynatılması.

Canlı radarla **aynı** bileşenler kullanılır (süpürme birleştirme, sembole göre öğrenilen eşik,
fiyat etkisi ölçümü). Arşivdeki her işlem zaman sırasıyla verilir; ileriye bakılmaz.

Karşılaştırma için bir **temel çizgi** de ölçülür: düzenli aralıklarla (balina olsun olmasın)
aynı ufuklardaki fiyat değişimi. Balina sonrası hareket temel çizgiden anlamlı biçimde
farklı değilse, balina sinyalinin tek başına bir avantaj sağlamadığı sonucuna varılır.
Sonuçlar geçmişi anlatır; gelecekteki fiyatı garanti etmez.
"""

from __future__ import annotations

import io
import math
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date

from ati_engine.core.models import Market
from ati_engine.history.archive import ArchiveError, market_prefix
from ati_engine.whales.impact import HORIZONS_S, ImpactStat, ImpactTracker
from ati_engine.whales.large_trades import SweepAggregator, TakerOrder, WhaleThresholds

BASELINE = "baseline"
WHALE = "whale_trade"


def aggtrades_key(market: Market, symbol: str, day: date) -> str:
    period = day.isoformat()
    return f"data/{market_prefix(market)}/daily/aggTrades/{symbol}/{symbol}-aggTrades-{period}.zip"


def iter_aggtrades(data: bytes) -> Iterator[tuple[int, float, float, bool]]:
    """(zaman ms, fiyat, miktar, alıcı yapıcı mı) — Spot (mikrosaniye, başlıksız, True/False)
    ve Futures (milisaniye, başlıklı, true/false) biçimlerini destekler. Bellek dostu:
    satırlar zip içinden akış olarak okunur."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ArchiveError(f"Bozuk zip: {exc}") from exc
    with archive:
        names = [n for n in archive.namelist() if n.endswith(".csv")]
        if len(names) != 1:
            raise ArchiveError(f"Beklenmeyen zip içeriği: {archive.namelist()}")
        with archive.open(names[0]) as raw:
            for line in io.TextIOWrapper(raw, encoding="ascii"):
                if not line or not line[0].isdigit():
                    continue
                f = line.split(",")
                stamp = int(f[5])
                if stamp >= 10**14:
                    stamp //= 1000
                yield stamp, float(f[1]), float(f[2]), f[6].strip().lower() == "true"


@dataclass
class Comparison:
    direction: int  # +1: alış balinası (yükseliş beklenir), -1: satış balinası
    horizon_s: int
    whale_n: int
    whale_mean_pct: float
    whale_hit_rate: float
    baseline_n: int
    baseline_mean_pct: float
    baseline_hit_rate: float
    t_stat: float  # ortalama farkının standart hataya oranı (|t| < 2: anlamlı değil)


@dataclass
class ReplayReport:
    market: str
    symbol: str
    days: list[str] = field(default_factory=list)
    trades: int = 0
    orders: int = 0
    whales: int = 0
    independent: int = 0  # etki ölçümüne alınan, birbirinden bağımsız balina olayları
    missing_days: list[str] = field(default_factory=list)  # arşivde bulunmayan günler
    discarded: int = 0  # veri boşluğu nedeniyle ölçülemeyen ufuklar
    whale_notional: float = 0.0
    final_threshold: float = 0.0
    comparisons: list[Comparison] = field(default_factory=list)


def _welch_t(a: ImpactStat, b: ImpactStat) -> float:
    if a.n < 2 or b.n < 2:
        return 0.0
    se = math.sqrt(a.std**2 / a.n + b.std**2 / b.n)
    return (a.mean - b.mean) / se if se > 0 else 0.0


class WhaleReplay:
    def __init__(
        self,
        market: Market,
        symbol: str,
        *,
        floor_usd: float,
        quantile: float = 0.999,
        min_samples: int = 2_000,
        horizons: tuple[int, ...] = HORIZONS_S,
        baseline_every_s: int = 300,
        min_gap_s: int = 900,
    ) -> None:
        self.market = market
        self.symbol = symbol
        self.sweeps = SweepAggregator()
        self.thresholds = WhaleThresholds(
            floor_usd=floor_usd, quantile=quantile, min_samples=min_samples
        )
        self.impact = ImpactTracker(horizons=horizons, max_pending=200_000)
        self._baseline_ms = baseline_every_s * 1000
        # Balina emirleri kümelenir (bir satış dalgasında onlarca emir). Kümelenmiş olaylar
        # bağımsız sayılırsa istatistik şişer; etki ölçümüne yalnızca aynı yöndeki bir önceki
        # ölçülen olaydan en az ``min_gap_s`` sonra gelen olaylar alınır.
        self._min_gap_ms = min_gap_s * 1000
        self._last_counted: dict[int, int] = {}
        self._next_baseline: int | None = None
        self._next_due = 0
        self._price = 0.0
        self.report = ReplayReport(market=market.value, symbol=symbol)

    def _price_of(self, market: Market, symbol: str) -> float | None:
        return self._price or None

    def feed(self, time_ms: int, price: float, qty: float, buyer_is_maker: bool) -> None:
        self.report.trades += 1
        completed = self.sweeps.add(self.symbol, time_ms, price, qty, taker_buy=not buyer_is_maker)
        if completed is not None:
            self._order(completed)
        self._price = price
        if time_ms >= self._next_due:
            # Ufuk ölçümleri, ufuk zamanına ulaşan ilk işlemin fiyatıyla yapılır (±1 sn).
            self.impact.due(time_ms, self._price_of)
            self._next_due = time_ms + 1_000
        if self._next_baseline is None:
            self._next_baseline = time_ms - time_ms % self._baseline_ms + self._baseline_ms
        if time_ms >= self._next_baseline:
            for direction in (1, -1):
                self.impact.register(BASELINE, direction, self.market, self.symbol, time_ms, price)
            self._next_baseline += self._baseline_ms

    def _order(self, order: TakerOrder) -> None:
        self.report.orders += 1
        threshold = self.thresholds.threshold(order.symbol)
        self.thresholds.observe(order.symbol, order.notional)
        if order.notional < threshold or not self.thresholds.learned(order.symbol):
            return  # eşik öğrenilmeden (ısınma) balina sayılmaz
        self.report.whales += 1
        self.report.whale_notional += order.notional
        direction = 1 if order.taker_buy else -1
        last = self._last_counted.get(direction)
        if last is not None and order.time_ms - last < self._min_gap_ms:
            return
        self._last_counted[direction] = order.time_ms
        self.report.independent += 1
        self.impact.register(
            WHALE, direction, self.market, self.symbol, order.time_ms, order.last_price
        )

    def gap(self, day: str) -> None:
        """Eksik gün: bekleyen emir tamamlanır, boşluğu aşan ölçümler atılır ve temel çizgi
        zamanlaması sıfırlanır (aksi halde ufuk fiyatı günler sonrasından okunurdu)."""
        for order in self.sweeps.flush(older_than_ms=2**62):
            self._order(order)
        self.report.discarded += self.impact.discard_pending()
        self.report.missing_days.append(day)
        self._next_baseline = None
        self._next_due = 0
        self._last_counted.clear()

    def finish(self) -> ReplayReport:
        for order in self.sweeps.flush(older_than_ms=2**62):
            self._order(order)
        self.report.final_threshold = self.thresholds.threshold(self.symbol)
        comparisons = []
        for (kind, direction, horizon), stat in sorted(self.impact.stats.items()):
            if kind != WHALE:
                continue
            base = self.impact.stats.get((BASELINE, direction, horizon), ImpactStat())
            comparisons.append(
                Comparison(
                    direction=direction,
                    horizon_s=horizon,
                    whale_n=stat.n,
                    whale_mean_pct=round(stat.mean, 5),
                    whale_hit_rate=round(stat.hit_rate, 4),
                    baseline_n=base.n,
                    baseline_mean_pct=round(base.mean, 5),
                    baseline_hit_rate=round(base.hit_rate, 4),
                    t_stat=round(_welch_t(stat, base), 3),
                )
            )
        self.report.comparisons = comparisons
        return self.report
