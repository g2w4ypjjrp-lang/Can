"""Balina olaylarının fiyat etkisi istatistikleri.

Her balina olayı (büyük alış/satış, kümelenme, tasfiye zinciri) bir "beklenen yön" taşır:
büyük alış → yukarı, büyük satış → aşağı, long tasfiyesi → aşağı. Olaydan 1, 5, 15 ve
60 dakika sonra fiyat ölçülür ve getiri beklenen yönle çarpılır (yönlü getiri). Böylece
"bu tür olaylardan sonra fiyat gerçekten o yöne gidiyor mu, ne kadar?" sorusu tahminle değil
ölçümle cevaplanır:

* ortalama yönlü getiri (%), standart sapma
* isabet oranı: yönlü getirinin pozitif olduğu olayların payı

Sonuçlar ``whale_impacts`` tablosuna yazılır; motor yeniden başladığında istatistikler bu
kayıtlardan yeniden kurulur. Geçmiş performans geleceği garanti etmez.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from ati_engine.core.models import Market

HORIZONS_S: tuple[int, ...] = (60, 300, 900, 3600)


@dataclass
class ImpactStat:
    n: int = 0
    total: float = 0.0
    total_sq: float = 0.0
    hits: int = 0

    def add(self, value: float) -> None:
        self.n += 1
        self.total += value
        self.total_sq += value * value
        if value > 0:
            self.hits += 1

    @property
    def mean(self) -> float:
        return self.total / self.n if self.n else 0.0

    @property
    def std(self) -> float:
        if self.n < 2:
            return 0.0
        var = (self.total_sq - self.total * self.total / self.n) / (self.n - 1)
        return math.sqrt(var) if var > 0 else 0.0

    @property
    def hit_rate(self) -> float:
        return self.hits / self.n if self.n else 0.0


@dataclass
class _Pending:
    kind: str
    direction: int  # +1 yukarı beklenir, -1 aşağı beklenir
    market: Market
    symbol: str
    t0_ms: int
    p0: float
    remaining: list[int] = field(default_factory=lambda: list(HORIZONS_S))


@dataclass(frozen=True)
class ImpactResult:
    kind: str
    direction: int
    market: Market
    symbol: str
    t0_ms: int
    horizon_s: int
    return_pct: float  # ham getiri
    directional_pct: float  # beklenen yönle çarpılmış getiri


PriceLookup = Callable[[Market, str], float | None]


class ImpactTracker:
    def __init__(
        self, *, horizons: tuple[int, ...] = HORIZONS_S, max_pending: int = 20_000
    ) -> None:
        self._horizons = horizons
        self._max_pending = max_pending
        self._pending: list[_Pending] = []
        self.stats: dict[tuple[str, int, int], ImpactStat] = {}
        self.dropped = 0

    @property
    def pending(self) -> int:
        return len(self._pending)

    def register(
        self, kind: str, direction: int, market: Market, symbol: str, t0_ms: int, p0: float
    ) -> None:
        if p0 <= 0 or direction not in (1, -1):
            return
        if len(self._pending) >= self._max_pending:
            self._pending.pop(0)
            self.dropped += 1
        self._pending.append(
            _Pending(kind, direction, market, symbol, t0_ms, p0, list(self._horizons))
        )

    def discard_pending(self) -> int:
        """Bekleyen ölçümleri atar (veri boşluğunda ufuk fiyatı doğru ölçülemez)."""
        count = len(self._pending)
        self._pending.clear()
        return count

    def restore(self, kind: str, direction: int, horizon_s: int, directional_pct: float) -> None:
        """Veritabanındaki geçmiş ölçümlerden istatistikleri yeniden kurar."""
        self.stats.setdefault((kind, direction, horizon_s), ImpactStat()).add(directional_pct)

    def due(self, now_ms: int, price_of: PriceLookup) -> list[ImpactResult]:
        results: list[ImpactResult] = []
        keep: list[_Pending] = []
        stale_after = (max(self._horizons) + 120) * 1000
        for item in self._pending:
            for horizon in list(item.remaining):
                if item.t0_ms + horizon * 1000 > now_ms:
                    continue
                price = price_of(item.market, item.symbol)
                item.remaining.remove(horizon)
                if price is None or price <= 0:
                    continue
                ret = (price / item.p0 - 1) * 100
                directional = ret * item.direction
                self.stats.setdefault((item.kind, item.direction, horizon), ImpactStat()).add(
                    directional
                )
                results.append(
                    ImpactResult(
                        kind=item.kind,
                        direction=item.direction,
                        market=item.market,
                        symbol=item.symbol,
                        t0_ms=item.t0_ms,
                        horizon_s=horizon,
                        return_pct=ret,
                        directional_pct=directional,
                    )
                )
            if item.remaining and now_ms - item.t0_ms <= stale_after:
                keep.append(item)
        self._pending = keep
        return results

    def summary(self) -> list[dict[str, float | int | str]]:
        rows: list[dict[str, float | int | str]] = []
        for (kind, direction, horizon), stat in sorted(self.stats.items()):
            rows.append(
                {
                    "kind": kind,
                    "expected_direction": "up" if direction > 0 else "down",
                    "horizon_s": horizon,
                    "samples": stat.n,
                    "mean_directional_pct": round(stat.mean, 4),
                    "std_pct": round(stat.std, 4),
                    "hit_rate": round(stat.hit_rate, 4),
                }
            )
        return rows
