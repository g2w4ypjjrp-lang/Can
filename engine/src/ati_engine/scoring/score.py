"""Fırsat puanı (0-100) ve açıklanabilir bileşen dökümü.

Hesap şeffaftır ve dökümdeki sayılar puanı birebir verir:

1. Her **yönlü bileşen** -1 (güçlü short) ile +1 (güçlü long) arasında bir değer üretir:
   stratejiler, trend, momentum, akış (hacim + agresif alış/satış), balina, emir defteri,
   tarihsel benzerlik, model. Verisi olmayan bileşen hesaba katılmaz; ağırlıklar mevcut
   bileşenler arasında yeniden dağıtılır.
2. Ağırlıklı ortalamanın işareti **yönü**, büyüklüğü **ham puanı** (0-100) verir. Her bileşenin
   ham puana katkısı (puan) dökümde gösterilir; yönle çelişen bileşenler eksi katkı yapar.
3. **Cezalar** ham puandan düşülür: işlem maliyetinin beklenen harekete oranı, düşük ödül/risk,
   düşük likidite, az veri.

Puan bir **fırsat göstergesidir, kâr olasılığı değildir**. Geçmişte aynı puan aralığının
maliyet sonrası ne getirdiği kalibrasyon tablosundan ayrıca gösterilir. Puan tek başına emir
üretmez; her işlem risk kapısından geçmek zorundadır (Aşama 11).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from ati_engine.analysis.features import Snapshot
from ati_engine.analysis.patterns import Pattern
from ati_engine.history.levels import Level
from ati_engine.scoring.costs import CostBreakdown, CostModel
from ati_engine.strategies.base import ModelView, StrategySignal

DEFAULT_WEIGHTS: dict[str, float] = {
    "strategies": 0.30,
    "trend": 0.15,
    "momentum": 0.10,
    "flow": 0.10,
    "whale": 0.10,
    "orderbook": 0.05,
    "similarity": 0.10,
    "model": 0.10,
}

TITLES = {
    "strategies": "Strateji uzlaşısı",
    "trend": "Trend",
    "momentum": "Momentum",
    "flow": "Hacim ve agresif akış",
    "whale": "Balina akışı",
    "orderbook": "Emir defteri dengesi",
    "similarity": "Tarihsel benzerlik",
    "model": "Makine öğrenmesi modeli",
}

DISCLAIMER = (
    "Puan bir fırsat göstergesidir, kâr olasılığı veya garantisi değildir. Tek başına emir "
    "üretmez; her işlem risk kapısından geçer."
)


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass(frozen=True)
class Component:
    key: str
    title: str
    available: bool
    signal: float  # -1..+1 (artı = long)
    weight: float  # yeniden dağıtılmış ağırlık
    points: float  # seçilen yöndeki ham puana katkı
    detail: str


@dataclass(frozen=True)
class Penalty:
    key: str
    title: str
    points: float  # düşülen puan (pozitif sayı)
    detail: str


@dataclass(frozen=True)
class WhaleContext:
    net_usd: float  # son pencerede balina alış - satış
    threshold_usd: float
    count: int


@dataclass(frozen=True)
class BookContext:
    imbalance: float  # -1..+1 (artı = alış tarafı derin)
    spread_bps: float | None
    notional: float | None


@dataclass(frozen=True)
class SimilarityContext:
    n: int
    positive_rate: float
    median_pct: float


@dataclass
class Opportunity:
    market: str
    symbol: str
    interval: str
    time_ms: int
    price: float
    direction: str  # long | short | none
    score: float
    raw_score: float
    components: list[Component]
    penalties: list[Penalty]
    signals: list[dict[str, Any]]
    cost: CostBreakdown
    stop_price: float | None
    target_price: float | None
    reward_risk: float | None
    target_pct: float | None
    calibration: dict[str, Any] | None = None
    disclaimer: str = DISCLAIMER
    notes: list[str] = field(default_factory=list)
    patterns: list[dict[str, Any]] = field(default_factory=list)  # bu mumdaki formasyonlar

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScoreInputs:
    market: str
    symbol: str
    interval: str
    interval_hours: float
    horizon_bars: int
    snapshot: Snapshot
    signals: Sequence[StrategySignal]
    levels: Sequence[Level] = ()
    quote_volume_24h: float | None = None
    whale: WhaleContext | None = None
    book: BookContext | None = None
    similarity: SimilarityContext | None = None
    model: ModelView | None = None
    patterns: Sequence[Pattern] = ()


class OpportunityScorer:
    def __init__(
        self,
        *,
        weights: Mapping[str, float] | None = None,
        cost_model: CostModel | None = None,
        calibration: Mapping[str, Any] | None = None,
    ) -> None:
        self.weights = dict(DEFAULT_WEIGHTS)
        if weights:
            unknown = set(weights) - set(DEFAULT_WEIGHTS)
            if unknown:
                raise ValueError(f"Bilinmeyen bileşen ağırlığı: {sorted(unknown)}")
            self.weights.update(weights)
        self.costs = cost_model or CostModel()
        self.calibration = calibration

    # --- Bileşenler --------------------------------------------------------------------

    def _components(self, x: ScoreInputs) -> dict[str, tuple[float | None, str]]:
        s = x.snapshot
        out: dict[str, tuple[float | None, str]] = {}

        if x.signals:
            total = sum(sig.direction * sig.strength for sig in x.signals)
            longs = sum(1 for sig in x.signals if sig.direction > 0)
            shorts = len(x.signals) - longs
            out["strategies"] = (
                math.tanh(total / 1.5),
                f"{len(x.signals)} strateji sinyal verdi ({longs} long, {shorts} short)",
            )
        else:
            out["strategies"] = (0.0, "Bu mumda hiçbir strateji sinyal vermedi")

        alignment = _clamp((s.ema21 - s.ema50) / s.atr / 3)
        long_term = math.copysign(min(abs(s.close - s.ema200) / s.atr / 5, 1.0), s.close - s.ema200)
        out["trend"] = (
            0.5 * alignment + 0.5 * long_term,
            f"EMA21-EMA50 {((s.ema21 - s.ema50) / s.atr):+.1f} ATR, "
            f"fiyat EMA200'ün {abs(s.close - s.ema200) / s.atr:.1f} ATR "
            f"{'üstünde' if s.close >= s.ema200 else 'altında'}",
        )

        momentum = 0.5 * _clamp((s.rsi - 50) / 25) + 0.5 * _clamp(s.macd_hist / s.atr * 2)
        out["momentum"] = (
            momentum,
            f"RSI {s.rsi:.0f}, MACD histogramı {s.macd_hist / s.atr:+.2f} ATR",
        )

        activity = min(1.0, max(s.volume_z, 0.0) / 2)
        flow = _clamp((s.taker_buy_ratio - 0.5) * 4) * activity
        out["flow"] = (
            flow,
            f"agresif alış oranı %{s.taker_buy_ratio * 100:.0f}, hacim z={s.volume_z:.1f}",
        )

        if x.whale is not None and x.whale.count > 0 and x.whale.threshold_usd > 0:
            out["whale"] = (
                math.tanh(x.whale.net_usd / (3 * x.whale.threshold_usd)),
                f"son 1 saatte {x.whale.count} balina emri, net {x.whale.net_usd:+,.0f} USDT",
            )
        else:
            out["whale"] = (None, "balina verisi yok")

        if x.book is not None:
            out["orderbook"] = (
                _clamp(x.book.imbalance),
                f"ilk 10 kademe dengesi {x.book.imbalance:+.2f}",
            )
        else:
            out["orderbook"] = (None, "emir defteri yalnızca odak sembollerinde izlenir")

        if x.similarity is not None and x.similarity.n >= 3:
            shrink = min(1.0, x.similarity.n / 10)
            out["similarity"] = (
                _clamp((x.similarity.positive_rate - 0.5) * 2) * shrink,
                f"{x.similarity.n} benzer geçmiş dönemin %{x.similarity.positive_rate * 100:.0f}'i "
                f"yükseldi (medyan {x.similarity.median_pct:+.2f}%)",
            )
        else:
            out["similarity"] = (None, "benzerlik verisi yok")

        m = x.model
        if m is not None and m.p_long is not None and m.base_long is not None:
            edge = m.p_long - m.base_long
            if m.p_short is not None and m.base_short is not None:
                edge -= m.p_short - m.base_short
            out["model"] = (
                _clamp(edge * 4),
                f"model olasılık farkı {edge * 100:+.1f} puan (temel orana göre)",
            )
        else:
            out["model"] = (None, "eğitilmiş model yok")
        return out

    # --- Puan ---------------------------------------------------------------------------

    def score(self, x: ScoreInputs) -> Opportunity:
        s = x.snapshot
        raw_components = self._components(x)
        available: dict[str, float] = {
            k: v[0] for k, v in raw_components.items() if v[0] is not None
        }
        total_weight = sum(self.weights[k] for k in available) or 1.0
        evidence = sum(self.weights[k] * value for k, value in available.items()) / total_weight
        direction = 1 if evidence >= 0.05 else -1 if evidence <= -0.05 else 0
        d = direction or 1

        components = []
        for key, (value, detail) in raw_components.items():
            weight = self.weights[key] / total_weight if value is not None else 0.0
            points = 100 * weight * (value or 0.0) * d if direction else 0.0
            components.append(
                Component(
                    key=key,
                    title=TITLES[key],
                    available=value is not None,
                    signal=round(value, 4) if value is not None else 0.0,
                    weight=round(weight, 4),
                    points=round(points, 2),
                    detail=detail,
                )
            )
        raw = sum(c.points for c in components) if direction else 0.0

        # Ödül / risk: stratejilerin önerilerinin medyanı, hedef karşı seviyeyle sınırlanır.
        agreeing = [sig for sig in x.signals if sig.direction == d]
        stop_atr = _median([sig.stop_atr for sig in agreeing]) if agreeing else 1.5
        target_atr = _median([sig.target_atr for sig in agreeing]) if agreeing else 3.0
        stop_atr, target_atr = max(stop_atr, 0.5), max(target_atr, 0.5)
        target = s.close + d * target_atr * s.atr
        notes: list[str] = []
        opposing = [
            lv.price
            for lv in x.levels
            if (lv.kind == "resistance" and d > 0 and lv.price > s.close)
            or (lv.kind == "support" and d < 0 and lv.price < s.close)
        ]
        if opposing:
            nearest = min(opposing, key=lambda p: abs(p - s.close))
            if abs(nearest - s.close) < abs(target - s.close):
                target = nearest
                notes.append(f"hedef en yakın karşı seviyeyle sınırlandı ({nearest:.6g})")
        stop = s.close - d * stop_atr * s.atr
        reward = abs(target - s.close)
        risk = abs(s.close - stop)
        rr = reward / risk if risk > 0 else None
        target_pct = reward / s.close * 100

        cost = self.costs.estimate(
            x.market,
            direction=d,
            holding_hours=x.interval_hours * x.horizon_bars,
            quote_volume_24h=x.quote_volume_24h,
            spread_bps=x.book.spread_bps if x.book else None,
            book_notional=x.book.notional if x.book else None,
            funding_rate=s.funding_rate,
        )

        penalties: list[Penalty] = []
        if direction and raw > 0:
            cost_ratio = max(cost.total_pct, 0.0) / target_pct if target_pct > 0 else 1.0
            penalties.append(
                Penalty(
                    "cost",
                    "İşlem maliyeti",
                    round(raw * min(1.0, cost_ratio), 2),
                    f"tahmini gidiş-dönüş maliyet %{cost.total_pct:.3f}, hedef hareketin "
                    f"%{min(cost_ratio, 9.99) * 100:.0f}'i",
                )
            )
            if rr is not None and rr < 1.5:
                penalties.append(
                    Penalty(
                        "reward_risk",
                        "Ödül/risk",
                        round(raw * (1.5 - rr) / 1.5 * 0.5, 2),
                        f"ödül/risk {rr:.2f} (1,5 altı)",
                    )
                )
            volume = x.quote_volume_24h
            if volume is not None and volume < 5e6:
                share = 0.5 if volume < 1e6 else 0.2
                penalties.append(
                    Penalty(
                        "liquidity",
                        "Düşük likidite",
                        round(raw * share, 2),
                        f"24 saatlik hacim {volume:,.0f} USDT",
                    )
                )
            if len(available) < 4:
                penalties.append(
                    Penalty(
                        "data",
                        "Sınırlı veri",
                        round(raw * 0.1, 2),
                        f"yalnızca {len(available)} bileşenin verisi var",
                    )
                )
        final = max(0.0, min(100.0, raw - sum(p.points for p in penalties)))
        opportunity = Opportunity(
            market=x.market,
            symbol=x.symbol,
            interval=x.interval,
            time_ms=s.open_time_ms,
            price=s.close,
            direction={1: "long", -1: "short", 0: "none"}[direction],
            score=round(final, 2),
            raw_score=round(raw, 2),
            components=components,
            penalties=penalties,
            signals=[
                {
                    "strategy": sig.strategy,
                    "direction": "long" if sig.direction > 0 else "short",
                    "strength": round(sig.strength, 3),
                    "reason": sig.reason,
                }
                for sig in x.signals
            ],
            cost=cost,
            stop_price=stop if direction else None,
            target_price=target if direction else None,
            reward_risk=round(rr, 3) if rr is not None and direction else None,
            target_pct=round(target_pct, 4) if direction else None,
            notes=notes,
            patterns=[p.to_dict() for p in x.patterns],
        )
        opportunity.calibration = self._calibration_for(final)
        return opportunity

    def _calibration_for(self, score: float) -> dict[str, Any] | None:
        if not self.calibration:
            return None
        for bucket in self.calibration.get("buckets", []):
            if bucket["low"] <= score < bucket["high"] or (score == 100 and bucket["high"] == 100):
                return {
                    "bucket": f"{bucket['low']:.0f}-{bucket['high']:.0f}",
                    "n": bucket["n"],
                    "hit_rate": bucket["hit_rate"],
                    "mean_net_return_pct": bucket["mean_net_return_pct"],
                    "source": self.calibration.get("source"),
                }
        return None


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2
