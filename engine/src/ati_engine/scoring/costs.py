"""İşlem maliyeti tahmini: komisyon, spread, kayma ve (vadelide) funding.

Varsayımlar ihtiyatlıdır: giriş ve çıkış alıcı (taker) emriyle yapılır. Spread ve emir defteri
derinliği biliniyorsa (odak sembolleri) gerçek değer kullanılır; bilinmiyorsa 24 saatlik işlem
hacmine göre kademeli bir tahmin yapılır ve bu, dökümde "tahmini" olarak belirtilir.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CostSettingsView:
    spot_taker_fee: float = 0.001  # %0,10 (Binance VIP0, BNB indirimi yok)
    futures_taker_fee: float = 0.0005  # %0,05 (USDⓈ-M VIP0)
    notional_usd: float = 1_000.0  # maliyet hesabındaki örnek işlem büyüklüğü
    funding_interval_hours: float = 8.0


@dataclass(frozen=True)
class CostBreakdown:
    fee_pct: float
    spread_pct: float
    slippage_pct: float
    funding_pct: float
    total_pct: float
    estimated: bool  # spread/derinlik gerçek değil tahmini mi
    notes: tuple[str, ...] = field(default_factory=tuple)


def _volume_tier(quote_volume_24h: float | None, tiers: tuple[float, ...]) -> float:
    """Hacim kademesine göre tahmin (tiers: ≥1 milyar, ≥100 milyon, ≥10 milyon, ≥1 milyon,
    daha az)."""
    volume = quote_volume_24h or 0.0
    for limit, value in zip((1e9, 1e8, 1e7, 1e6), tiers, strict=False):
        if volume >= limit:
            return value
    return tiers[-1]


class CostModel:
    def __init__(self, settings: CostSettingsView | None = None) -> None:
        self.settings = settings or CostSettingsView()

    def estimate(
        self,
        market: str,
        *,
        direction: int,
        holding_hours: float,
        quote_volume_24h: float | None = None,
        spread_bps: float | None = None,
        book_notional: float | None = None,
        funding_rate: float | None = None,
    ) -> CostBreakdown:
        """Gidiş-dönüş toplam maliyet (yüzde)."""
        cfg = self.settings
        notes: list[str] = []
        futures = market == "usdm_futures"
        fee = 2 * (cfg.futures_taker_fee if futures else cfg.spot_taker_fee) * 100
        estimated = False
        if spread_bps is not None and spread_bps >= 0:
            spread = spread_bps / 100  # baz puan → yüzde (giriş + çıkışta yarım spread)
        else:
            spread = _volume_tier(quote_volume_24h, (0.01, 0.03, 0.08, 0.2, 0.5))
            estimated = True
            notes.append("spread 24 saatlik hacme göre tahmini")
        if book_notional is not None and book_notional > 0:
            impact = min(0.5, cfg.notional_usd / book_notional * 0.1)
            slippage = 2 * impact
        else:
            slippage = 2 * _volume_tier(quote_volume_24h, (0.005, 0.01, 0.03, 0.1, 0.3))
            estimated = True
            notes.append("kayma 24 saatlik hacme göre tahmini")
        funding = 0.0
        if futures and funding_rate is not None:
            periods = holding_hours / cfg.funding_interval_hours
            # Pozitif funding'de long öder, short alır.
            funding = funding_rate * 100 * periods * direction
            if funding:
                notes.append(f"funding {funding_rate * 10_000:+.2f} baz puan x {periods:.2f} dönem")
        total = fee + spread + slippage + funding
        return CostBreakdown(
            fee_pct=round(fee, 5),
            spread_pct=round(spread, 5),
            slippage_pct=round(slippage, 5),
            funding_pct=round(funding, 5),
            total_pct=round(total, 5),
            estimated=estimated,
            notes=tuple(notes),
        )
