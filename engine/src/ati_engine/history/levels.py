"""Grafik analizi: ATR, dönüş noktaları (pivot), destek/direnç seviyeleri ve trend kırılımları.

Girdi olarak ``(açılış zamanı, açılış, en yüksek, en düşük, kapanış, hacim, ...)``
biçimindeki mum satırlarını alır (``KlineStore.candles`` ve ``KlineStore.resample`` çıktısı).

**İleriye bakma yasağı:** Bir dönüş noktası ancak sağındaki ``right`` mum kapandıktan sonra
kesinleşir. Trend kırılımı taraması her mumda yalnızca o ana kadar kesinleşmiş dönüş
noktalarını kullanır; böylece geçmiş üzerinde üretilen kırılımlar canlıda da aynı anda
üretilebilecek kırılımlardır (backtest ile tutarlı).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

Bars = Sequence[Sequence[Any]]

T, H, L, C, V = 0, 2, 3, 4, 5  # sütun indeksleri (1 = açılış)


def atr(bars: Bars, period: int = 14) -> list[float]:
    """Wilder ortalama gerçek aralık. İlk ``period`` mum için basit ortalama kullanılır."""
    result: list[float] = []
    value = 0.0
    for i, bar in enumerate(bars):
        high, low = float(bar[H]), float(bar[L])
        if i == 0:
            tr = high - low
        else:
            prev_close = float(bars[i - 1][C])
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        # İlk ``period`` mumda basit ortalama, sonrasında Wilder yumuşatması.
        value = (value * i + tr) / (i + 1) if i < period else (value * (period - 1) + tr) / period
        result.append(value)
    return result


@dataclass(frozen=True)
class Pivot:
    index: int
    time_ms: int
    price: float
    kind: Literal["high", "low"]
    volume: float


def pivots(bars: Bars, left: int = 3, right: int = 3) -> list[Pivot]:
    """Fraktal dönüş noktaları: solundaki ``left`` ve sağındaki ``right`` mumdan
    yüksek tepe / alçak dip. Eşit değerlerde ilk mum dönüş noktası sayılır."""
    found: list[Pivot] = []
    n = len(bars)
    for i in range(left, n - right):
        high, low = float(bars[i][H]), float(bars[i][L])
        before = bars[i - left : i]
        after = bars[i + 1 : i + right + 1]
        if all(high > float(b[H]) for b in before) and all(high >= float(b[H]) for b in after):
            found.append(Pivot(i, int(bars[i][T]), high, "high", float(bars[i][V])))
        if all(low < float(b[L]) for b in before) and all(low <= float(b[L]) for b in after):
            found.append(Pivot(i, int(bars[i][T]), low, "low", float(bars[i][V])))
    return found


# --- Destek / direnç ----------------------------------------------------------------------


@dataclass(frozen=True)
class Level:
    price: float
    kind: Literal["support", "resistance"]
    touches: int
    first_time_ms: int
    last_time_ms: int
    strength: float  # 0-100, aynı analizdeki seviyelere göre göreli
    distance_pct: float  # son kapanışa uzaklık (+ yukarıda, - aşağıda)


def find_levels(
    bars: Bars,
    *,
    left: int = 3,
    right: int = 3,
    tolerance_atr: float = 0.5,
    min_touches: int = 2,
    per_side: int = 5,
    atr_period: int = 14,
) -> list[Level]:
    """Dönüş noktalarını fiyat yakınlığına göre kümeler; en az ``min_touches`` kez test
    edilmiş bölgeleri seviye kabul eder. Son kapanışın altındakiler destek, üstündekiler
    direnç olarak, her yönde en yakın ``per_side`` seviye döner."""
    if len(bars) < left + right + 2:
        return []
    points = sorted(pivots(bars, left, right), key=lambda p: p.price)
    if not points:
        return []
    last_close = float(bars[-1][C])
    atr_values = atr(bars, atr_period)
    tolerance = tolerance_atr * atr_values[-1]
    if tolerance <= 0:
        tolerance = last_close * 0.002

    clusters: list[list[Pivot]] = [[points[0]]]
    for point in points[1:]:
        cluster = clusters[-1]
        center = sum(p.price for p in cluster) / len(cluster)
        if point.price - center <= tolerance:
            cluster.append(point)
        else:
            clusters.append([point])

    n = len(bars)
    raw: list[tuple[float, list[Pivot], float]] = []
    for cluster in clusters:
        if len(cluster) < min_touches:
            continue
        weight = sum(p.volume for p in cluster) or float(len(cluster))
        price = (
            sum(p.price * p.volume for p in cluster) / weight
            if any(p.volume for p in cluster)
            else sum(p.price for p in cluster) / len(cluster)
        )
        last_index = max(p.index for p in cluster)
        recency = math.exp(-(n - 1 - last_index) / max(n / 3, 1))  # yakın zamanda test edilen
        score = len(cluster) * (0.5 + recency)
        raw.append((price, cluster, score))
    if not raw:
        return []
    best = max(score for _, _, score in raw)
    levels = [
        Level(
            price=round(price, 10),
            kind="support" if price < last_close else "resistance",
            touches=len(cluster),
            first_time_ms=min(p.time_ms for p in cluster),
            last_time_ms=max(p.time_ms for p in cluster),
            strength=round(100 * score / best, 1),
            distance_pct=round((price / last_close - 1) * 100, 4),
        )
        for price, cluster, score in raw
    ]
    supports = sorted((lv for lv in levels if lv.kind == "support"), key=lambda lv: -lv.price)
    resistances = sorted((lv for lv in levels if lv.kind == "resistance"), key=lambda lv: lv.price)
    return supports[:per_side] + resistances[:per_side]


# --- Trend çizgileri ve kırılımlar --------------------------------------------------------


@dataclass(frozen=True)
class TrendLine:
    kind: Literal["support", "resistance"]  # yükselen dip çizgisi / alçalan tepe çizgisi
    a_index: int
    a_time_ms: int
    a_price: float
    b_index: int
    b_time_ms: int
    b_price: float

    @property
    def slope(self) -> float:
        return (self.b_price - self.a_price) / (self.b_index - self.a_index)

    def value_at(self, index: int) -> float:
        return self.a_price + self.slope * (index - self.a_index)


@dataclass(frozen=True)
class TrendBreak:
    line: TrendLine
    index: int
    time_ms: int
    close: float
    line_value: float
    direction: Literal["up", "down"]  # direnç yukarı kırıldı / destek aşağı kırıldı
    penetration_atr: float


@dataclass(frozen=True)
class TrendAnalysis:
    active: list[TrendLine]
    breaks: list[TrendBreak]


def _line_holds(
    bars: Bars, line: TrendLine, until: int, tolerance: list[float], *, support: bool
) -> bool:
    for i in range(line.a_index, until + 1):
        value = line.value_at(i)
        close = float(bars[i][C])
        if support and close < value - tolerance[i]:
            return False
        if not support and close > value + tolerance[i]:
            return False
    return True


def trend_analysis(
    bars: Bars,
    *,
    left: int = 3,
    right: int = 3,
    confirm_atr: float = 0.3,
    atr_period: int = 14,
) -> TrendAnalysis:
    """Mum mum ilerler; her mumda yalnızca kesinleşmiş dönüş noktalarıyla son yükselen dip
    çizgisini (destek) ve son alçalan tepe çizgisini (direnç) kurar. Kapanış çizginin
    ``confirm_atr`` × ATR ötesine geçerse kırılım kaydedilir ve çizgi kapanır."""
    all_pivots = pivots(bars, left, right)
    lows = [p for p in all_pivots if p.kind == "low"]
    highs = [p for p in all_pivots if p.kind == "high"]
    atr_values = atr(bars, atr_period)
    tolerance = [confirm_atr * a for a in atr_values]
    known_lows: list[Pivot] = []
    known_highs: list[Pivot] = []
    li = hi = 0
    support: TrendLine | None = None
    resistance: TrendLine | None = None
    breaks: list[TrendBreak] = []

    for t in range(len(bars)):
        new_low = new_high = False
        while li < len(lows) and lows[li].index + right <= t:
            known_lows.append(lows[li])
            li += 1
            new_low = True
        while hi < len(highs) and highs[hi].index + right <= t:
            known_highs.append(highs[hi])
            hi += 1
            new_high = True
        if new_low and len(known_lows) >= 2:
            a, b = known_lows[-2], known_lows[-1]
            if b.price > a.price:
                line = TrendLine(
                    "support", a.index, a.time_ms, a.price, b.index, b.time_ms, b.price
                )
                if _line_holds(bars, line, t, tolerance, support=True):
                    support = line
        if new_high and len(known_highs) >= 2:
            a, b = known_highs[-2], known_highs[-1]
            if b.price < a.price:
                line = TrendLine(
                    "resistance", a.index, a.time_ms, a.price, b.index, b.time_ms, b.price
                )
                if _line_holds(bars, line, t, tolerance, support=False):
                    resistance = line

        close = float(bars[t][C])
        if support is not None and t > support.b_index:
            value = support.value_at(t)
            if close < value - tolerance[t]:
                breaks.append(_break(support, t, bars, value, "down", atr_values[t]))
                support = None
        if resistance is not None and t > resistance.b_index:
            value = resistance.value_at(t)
            if close > value + tolerance[t]:
                breaks.append(_break(resistance, t, bars, value, "up", atr_values[t]))
                resistance = None

    active = [line for line in (support, resistance) if line is not None]
    return TrendAnalysis(active=active, breaks=breaks)


def _break(
    line: TrendLine,
    t: int,
    bars: Bars,
    value: float,
    direction: Literal["up", "down"],
    atr_value: float,
) -> TrendBreak:
    close = float(bars[t][C])
    return TrendBreak(
        line=line,
        index=t,
        time_ms=int(bars[t][T]),
        close=close,
        line_value=value,
        direction=direction,
        penetration_atr=round(abs(close - value) / atr_value, 3) if atr_value > 0 else 0.0,
    )
