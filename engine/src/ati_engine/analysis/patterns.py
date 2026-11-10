"""Formasyon tanıma: mum formasyonları ve klasik grafik formasyonları.

Girdi, ``StrategyBook``'un tuttuğu kapanmış mumlardır: ``(açılış zamanı, açılış, en yüksek,
en düşük, kapanış, hacim)``. Yalnızca **bu mumda tamamlanan** formasyonlar döner; yani her
formasyon, oluştuğu mum kapandığı anda bir kez görülür.

**İleriye bakma yasağı:** Grafik formasyonları yalnızca kesinleşmiş dönüş noktalarını (sağında
``right`` mum kapanmış pivotları) kullanır ve yalnızca boyun çizgisi / sınır **bu mumda**
kırıldığında tetiklenir. Böylece geçmiş üzerinde bulunan formasyonlar canlıda da aynı anda
bulunur (backtest ve sanal yarışma ile tutarlı).

Formasyonlar kâr garantisi değildir. Strateji olarak backtest ve sanal yarışmada ayrıca ölçülür,
fırsat puanına diğer stratejilerle birlikte katkı yapar.

Mum formasyonları:
    yutan mum (boğa/ayı), çekiç / kayan yıldız (iğne mum), sabah / akşam yıldızı,
    üç beyaz asker / üç kara karga
Grafik formasyonları:
    ikili dip / ikili tepe, omuz-baş-omuz / ters omuz-baş-omuz,
    yükselen / alçalan / simetrik üçgen kırılımı, boğa / ayı bayrağı
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from ati_engine.history.levels import Level, Pivot, pivots

BarRow = Sequence[float]  # (t, o, h, l, c, v)
T, OPEN, H, L, C, V = 0, 1, 2, 3, 4, 5

WINDOW = 160  # grafik formasyonları için bakılan son mum sayısı
PIVOT_SIDE = 3  # dönüş noktası: solda ve sağda 3 mum


@dataclass(frozen=True)
class Pattern:
    key: str
    title: str
    kind: Literal["candle", "chart"]
    direction: int  # +1 yükseliş, -1 düşüş
    strength: float  # 0-1
    reason: str
    stop_price: float | None = None  # formasyonun geçersizleştiği seviye
    target_price: float | None = None  # ölçülen hareket hedefi (grafik formasyonları)

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "title": self.title,
            "kind": self.kind,
            "direction": "long" if self.direction > 0 else "short",
            "strength": round(self.strength, 3),
            "reason": self.reason,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
        }


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _body(b: BarRow) -> float:
    return abs(b[C] - b[OPEN])


def _range(b: BarRow) -> float:
    return b[H] - b[L]


def _upper(b: BarRow) -> float:
    return b[H] - max(b[OPEN], b[C])


def _lower(b: BarRow) -> float:
    return min(b[OPEN], b[C]) - b[L]


def _bull(b: BarRow) -> bool:
    return b[C] > b[OPEN]


def _bear(b: BarRow) -> bool:
    return b[C] < b[OPEN]


def _prior_move(bars: Sequence[BarRow], end: int, atr: float, n: int = 5) -> float:
    """``end`` mumunun kapanışına kadar son ``n`` mumdaki hareket (ATR cinsinden)."""
    start = end - n
    if start < 0 or atr <= 0:
        return 0.0
    return (bars[end][C] - bars[start][C]) / atr


def _level_near(price: float, levels: Sequence[Level], kind: str, atr: float) -> Level | None:
    near = [lv for lv in levels if lv.kind == kind and abs(lv.price - price) <= 0.5 * atr]
    return max(near, key=lambda lv: lv.touches) if near else None


def _volume_ratio(bars: Sequence[BarRow], lookback: int = 20) -> float:
    if len(bars) < lookback + 1:
        return 1.0
    past = [b[V] for b in bars[-lookback - 1 : -1]]
    average = sum(past) / len(past)
    return bars[-1][V] / average if average > 0 else 1.0


# --- Mum formasyonları ----------------------------------------------------------------------


def _with_level(strength: float, reason: str, level: Level | None, side: str) -> tuple[float, str]:
    if level is None:
        return strength, reason
    return (
        strength + 0.15 + min(level.touches, 6) * 0.02,
        f"{reason}; {level.touches} kez test edilmiş {level.price:.6g} {side} üzerinde",
    )


def candle_patterns(
    bars: Sequence[BarRow], atr: float, levels: Sequence[Level] = ()
) -> list[Pattern]:
    """Son mumda tamamlanan mum formasyonları. Dönüş formasyonları yalnızca önceki hareket
    ters yöndeyse (en az 1 ATR) sayılır."""
    if len(bars) < 9 or atr <= 0:
        return []
    found: list[Pattern] = []
    b0, b1, b2 = bars[-1], bars[-2], bars[-3]
    i0 = len(bars) - 1
    before_b1 = _prior_move(bars, i0 - 1, atr)  # son mumdan önceki hareket
    before_b2 = _prior_move(bars, i0 - 2, atr)  # üçlü formasyonlarda ilk mumdan önce

    # Yutan mum: önceki mumun gövdesini tamamen saran, ters yönde güçlü gövde.
    if (
        _bear(b1)
        and _bull(b0)
        and b0[OPEN] <= b1[C]
        and b0[C] >= b1[OPEN]
        and _body(b0) >= max(_body(b1), 0.5 * atr)
        and before_b1 <= -1.0
    ):
        strength, reason = _with_level(
            0.45 + min(_body(b0) / atr, 2.0) * 0.1,
            f"boğa yutan mum: gövde {_body(b0) / atr:.1f} ATR, öncesinde "
            f"{abs(before_b1):.1f} ATR düşüş",
            _level_near(min(b0[L], b1[L]), levels, "support", atr),
            "desteği",
        )
        found.append(
            Pattern(
                "bullish_engulfing",
                "Boğa yutan mum",
                "candle",
                1,
                _clamp(strength),
                reason,
                stop_price=min(b0[L], b1[L]) - 0.1 * atr,
            )
        )
    if (
        _bull(b1)
        and _bear(b0)
        and b0[OPEN] >= b1[C]
        and b0[C] <= b1[OPEN]
        and _body(b0) >= max(_body(b1), 0.5 * atr)
        and before_b1 >= 1.0
    ):
        strength, reason = _with_level(
            0.45 + min(_body(b0) / atr, 2.0) * 0.1,
            f"ayı yutan mum: gövde {_body(b0) / atr:.1f} ATR, öncesinde "
            f"{before_b1:.1f} ATR yükseliş",
            _level_near(max(b0[H], b1[H]), levels, "resistance", atr),
            "direnci",
        )
        found.append(
            Pattern(
                "bearish_engulfing",
                "Ayı yutan mum",
                "candle",
                -1,
                _clamp(strength),
                reason,
                stop_price=max(b0[H], b1[H]) + 0.1 * atr,
            )
        )

    # İğne mum: uzun alt fitil (çekiç) / uzun üst fitil (kayan yıldız).
    rng = _range(b0)
    if rng >= 0.8 * atr:
        body = max(_body(b0), 1e-12)
        if (
            _lower(b0) >= 2 * body
            and _lower(b0) >= 0.6 * rng
            and _upper(b0) <= 0.25 * rng
            and before_b1 <= -1.0
        ):
            strength, reason = _with_level(
                0.4 + min(_lower(b0) / atr, 2.0) * 0.1,
                f"çekiç: alt fitil {_lower(b0) / atr:.1f} ATR (mumun %{_lower(b0) / rng * 100:.0f}"
                f"'i), öncesinde {abs(before_b1):.1f} ATR düşüş",
                _level_near(b0[L], levels, "support", atr),
                "desteği",
            )
            found.append(
                Pattern(
                    "hammer",
                    "Çekiç",
                    "candle",
                    1,
                    _clamp(strength),
                    reason,
                    stop_price=b0[L] - 0.1 * atr,
                )
            )
        if (
            _upper(b0) >= 2 * body
            and _upper(b0) >= 0.6 * rng
            and _lower(b0) <= 0.25 * rng
            and before_b1 >= 1.0
        ):
            strength, reason = _with_level(
                0.4 + min(_upper(b0) / atr, 2.0) * 0.1,
                f"kayan yıldız: üst fitil {_upper(b0) / atr:.1f} ATR (mumun "
                f"%{_upper(b0) / rng * 100:.0f}'i), öncesinde {before_b1:.1f} ATR yükseliş",
                _level_near(b0[H], levels, "resistance", atr),
                "direnci",
            )
            found.append(
                Pattern(
                    "shooting_star",
                    "Kayan yıldız",
                    "candle",
                    -1,
                    _clamp(strength),
                    reason,
                    stop_price=b0[H] + 0.1 * atr,
                )
            )

    # Sabah / akşam yıldızı: güçlü mum, küçük gövdeli kararsız mum, ters yönde güçlü kapanış.
    small_middle = _body(b1) <= max(0.3 * atr, 0.5 * _body(b2))
    if (
        _bear(b2)
        and _body(b2) >= 0.6 * atr
        and small_middle
        and _bull(b0)
        and b0[C] >= (b2[OPEN] + b2[C]) / 2
        and before_b2 <= -1.0
    ):
        low = min(b0[L], b1[L], b2[L])
        strength, reason = _with_level(
            0.55,
            f"sabah yıldızı: kapanış önceki düşüş mumunun ortasının üstünde, öncesinde "
            f"{abs(before_b2):.1f} ATR düşüş",
            _level_near(low, levels, "support", atr),
            "desteği",
        )
        found.append(
            Pattern(
                "morning_star",
                "Sabah yıldızı",
                "candle",
                1,
                _clamp(strength),
                reason,
                stop_price=low - 0.1 * atr,
            )
        )
    if (
        _bull(b2)
        and _body(b2) >= 0.6 * atr
        and small_middle
        and _bear(b0)
        and b0[C] <= (b2[OPEN] + b2[C]) / 2
        and before_b2 >= 1.0
    ):
        high = max(b0[H], b1[H], b2[H])
        strength, reason = _with_level(
            0.55,
            f"akşam yıldızı: kapanış önceki yükseliş mumunun ortasının altında, öncesinde "
            f"{before_b2:.1f} ATR yükseliş",
            _level_near(high, levels, "resistance", atr),
            "direnci",
        )
        found.append(
            Pattern(
                "evening_star",
                "Akşam yıldızı",
                "candle",
                -1,
                _clamp(strength),
                reason,
                stop_price=high + 0.1 * atr,
            )
        )

    # Üç beyaz asker / üç kara karga: üç ardışık güçlü, kısa fitilli gövde.
    three = (b2, b1, b0)
    if all(_bull(b) and _body(b) >= 0.5 * atr and _upper(b) <= 0.3 * _body(b) for b in three) and (
        b1[C] > b2[C]
        and b0[C] > b1[C]
        and b2[OPEN] <= b1[OPEN] <= b2[C]
        and b1[OPEN] <= b0[OPEN] <= b1[C]
    ):
        found.append(
            Pattern(
                "three_white_soldiers",
                "Üç beyaz asker",
                "candle",
                1,
                _clamp(0.4 + min(sum(_body(b) for b in three) / atr, 4.0) * 0.05),
                "üç beyaz asker: ardışık üç güçlü yükseliş mumu, kısa üst fitiller",
                stop_price=b2[L] - 0.1 * atr,
            )
        )
    if all(_bear(b) and _body(b) >= 0.5 * atr and _lower(b) <= 0.3 * _body(b) for b in three) and (
        b1[C] < b2[C]
        and b0[C] < b1[C]
        and b2[C] <= b1[OPEN] <= b2[OPEN]
        and b1[C] <= b0[OPEN] <= b1[OPEN]
    ):
        found.append(
            Pattern(
                "three_black_crows",
                "Üç kara karga",
                "candle",
                -1,
                _clamp(0.4 + min(sum(_body(b) for b in three) / atr, 4.0) * 0.05),
                "üç kara karga: ardışık üç güçlü düşüş mumu, kısa alt fitiller",
                stop_price=b2[H] + 0.1 * atr,
            )
        )
    return found


# --- Grafik formasyonları -------------------------------------------------------------------


def _line(a: Pivot, b: Pivot, index: int) -> float:
    if b.index == a.index:
        return b.price
    return a.price + (b.price - a.price) * (index - a.index) / (b.index - a.index)


def _crossed_up(bars: Sequence[BarRow], now_level: float, prev_level: float) -> bool:
    return bars[-1][C] > now_level and bars[-2][C] <= prev_level


def _crossed_down(bars: Sequence[BarRow], now_level: float, prev_level: float) -> bool:
    return bars[-1][C] < now_level and bars[-2][C] >= prev_level


def _volume_bonus(bars: Sequence[BarRow]) -> tuple[float, str]:
    ratio = _volume_ratio(bars)
    if ratio >= 1.5:
        return 0.15, f", kırılım hacmi ortalamanın {ratio:.1f} katı"
    if ratio < 0.8:
        return -0.1, ", kırılım hacmi zayıf"
    return 0.0, ""


def _double(bars: Sequence[BarRow], piv: list[Pivot], atr: float, bottom: bool) -> Pattern | None:
    n = len(bars)
    own = [p for p in piv if p.kind == ("low" if bottom else "high")]
    other = [p for p in piv if p.kind == ("high" if bottom else "low")]
    if len(own) < 2:
        return None
    a, b = own[-2], own[-1]
    if not (5 <= b.index - a.index <= 80) or n - 1 - b.index > 30:
        return None
    tolerance = max(0.6 * atr, 0.003 * b.price)
    if abs(a.price - b.price) > tolerance:
        return None
    between = [p for p in other if a.index < p.index < b.index]
    if not between:
        return None
    if bottom:
        neck = max(p.price for p in between)
        extreme = min(a.price, b.price)
        height = neck - extreme
        after = min(r[L] for r in bars[b.index + 1 :])
        if height < 1.5 * atr or after < extreme - 0.5 * tolerance:
            return None
        if not _crossed_up(bars, neck, neck):
            return None
    else:
        neck = min(p.price for p in between)
        extreme = max(a.price, b.price)
        height = extreme - neck
        after = max(r[H] for r in bars[b.index + 1 :])
        if height < 1.5 * atr or after > extreme + 0.5 * tolerance:
            return None
        if not _crossed_down(bars, neck, neck):
            return None
    bonus, volume_note = _volume_bonus(bars)
    direction = 1 if bottom else -1
    close = bars[-1][C]
    return Pattern(
        "double_bottom" if bottom else "double_top",
        "İkili dip" if bottom else "İkili tepe",
        "chart",
        direction,
        _clamp(0.55 + min(height / atr, 6.0) * 0.03 + bonus),
        f"{'ikili dip' if bottom else 'ikili tepe'}: {a.price:.6g} ve {b.price:.6g} "
        f"{'dipleri' if bottom else 'tepeleri'}, boyun çizgisi {neck:.6g} "
        f"{'yukarı' if bottom else 'aşağı'} kırıldı{volume_note}",
        stop_price=extreme - direction * 0.2 * atr,
        target_price=close + direction * height,
    )


def _head_shoulders(
    bars: Sequence[BarRow], piv: list[Pivot], atr: float, inverse: bool
) -> Pattern | None:
    n = len(bars)
    peaks = [p for p in piv if p.kind == ("low" if inverse else "high")]
    troughs = [p for p in piv if p.kind == ("high" if inverse else "low")]
    if len(peaks) < 3:
        return None
    left, head, right = peaks[-3], peaks[-2], peaks[-1]
    if n - 1 - right.index > 25 or right.index - left.index > 100:
        return None
    sign = -1 if inverse else 1  # baş, omuzlardan bu yönde uzakta
    if sign * (head.price - max(left.price, right.price, key=lambda x: sign * x)) < 1.0 * atr:
        return None
    if abs(left.price - right.price) > max(1.0 * atr, 0.01 * head.price):
        return None
    t1 = [p for p in troughs if left.index < p.index < head.index]
    t2 = [p for p in troughs if head.index < p.index < right.index]
    if not t1 or not t2:
        return None
    pick = max if inverse else min
    n1 = pick(t1, key=lambda p: p.price)
    n2 = pick(t2, key=lambda p: p.price)
    neck_now = _line(n1, n2, n - 1)
    neck_prev = _line(n1, n2, n - 2)
    height = abs(head.price - _line(n1, n2, head.index))
    if inverse:
        if not _crossed_up(bars, neck_now, neck_prev):
            return None
    elif not _crossed_down(bars, neck_now, neck_prev):
        return None
    direction = 1 if inverse else -1
    bonus, volume_note = _volume_bonus(bars)
    close = bars[-1][C]
    return Pattern(
        "inverse_head_shoulders" if inverse else "head_shoulders",
        "Ters omuz-baş-omuz" if inverse else "Omuz-baş-omuz",
        "chart",
        direction,
        _clamp(0.6 + min(height / atr, 6.0) * 0.03 + bonus),
        f"{'ters ' if inverse else ''}omuz-baş-omuz: baş {head.price:.6g}, omuzlar "
        f"{left.price:.6g} / {right.price:.6g}; boyun çizgisi {neck_now:.6g} "
        f"{'yukarı' if inverse else 'aşağı'} kırıldı{volume_note}",
        stop_price=right.price - direction * 0.2 * atr,
        target_price=close + direction * height,
    )


def _triangle(bars: Sequence[BarRow], piv: list[Pivot], atr: float) -> Pattern | None:
    n = len(bars)
    highs = [p for p in piv if p.kind == "high" and n - 1 - p.index <= 60]
    lows = [p for p in piv if p.kind == "low" and n - 1 - p.index <= 60]
    if len(highs) < 2 or len(lows) < 2:
        return None
    h1, h2 = highs[-2], highs[-1]
    l1, l2 = lows[-2], lows[-1]
    start = min(h1.index, l1.index)
    if n - 1 <= max(h2.index, l2.index):
        return None
    width_start = _line(h1, h2, start) - _line(l1, l2, start)
    upper_now, lower_now = _line(h1, h2, n - 1), _line(l1, l2, n - 1)
    width_now = upper_now - lower_now
    if width_start < 2 * atr or width_now <= 0 or width_now > 0.75 * width_start:
        return None
    flat = 0.3 * atr
    upper_flat = abs(h2.price - h1.price) <= flat
    lower_flat = abs(l2.price - l1.price) <= flat
    upper_falling = h2.price < h1.price - flat
    lower_rising = l2.price > l1.price + flat
    if upper_flat and lower_rising:
        shape, bias, title = "ascending", 1, "Yükselen üçgen"
    elif lower_flat and upper_falling:
        shape, bias, title = "descending", -1, "Alçalan üçgen"
    elif upper_falling and lower_rising:
        shape, bias, title = "symmetrical", 0, "Simetrik üçgen"
    else:
        return None
    if _crossed_up(bars, upper_now, _line(h1, h2, n - 2)):
        direction, stop = 1, lower_now
    elif _crossed_down(bars, lower_now, _line(l1, l2, n - 2)):
        direction, stop = -1, upper_now
    else:
        return None
    bonus, volume_note = _volume_bonus(bars)
    agrees = bias == direction
    close = bars[-1][C]
    return Pattern(
        f"{shape}_triangle",
        title,
        "chart",
        direction,
        _clamp(0.45 + (0.15 if agrees else 0.0) + bonus),
        f"{title.lower()} {'yukarı' if direction > 0 else 'aşağı'} kırıldı "
        f"(daralma: {width_start / atr:.1f} → {width_now / atr:.1f} ATR)"
        f"{'' if agrees or bias == 0 else ', beklenen yönün tersine'}{volume_note}",
        stop_price=stop,
        target_price=close + direction * width_start,
    )


def _flag(bars: Sequence[BarRow], atr: float) -> Pattern | None:
    """Bayrak: güçlü direk (en çok 8 mumda en az 4 ATR) + dar ve sığ dinlenme (4-15 mum) +
    dinlenme aralığının bu mumda kırılması."""
    n = len(bars)
    close = bars[-1][C]
    best: tuple[float, int, int, int, float] | None = None  # derinlik, yön, uzunluk, açıklık, stop
    for length in range(4, 16):
        pole_end = n - 2 - length
        if pole_end < 9:
            break
        rest = bars[pole_end + 1 : n - 1]
        rest_high = max(r[H] for r in rest)
        rest_low = min(r[L] for r in rest)
        for span in range(3, 9):
            start = pole_end - span
            if start < 0:
                break
            move = bars[pole_end][C] - bars[start][C]
            depth = abs(move)
            if depth < 4 * atr or rest_high - rest_low > 0.5 * depth:
                continue
            if move > 0:
                if bars[pole_end][H] - rest_low > 0.5 * depth or close <= rest_high:
                    continue
                candidate = (depth, 1, length, span, rest_low)
            else:
                if rest_high - bars[pole_end][L] > 0.5 * depth or close >= rest_low:
                    continue
                candidate = (depth, -1, length, span, rest_high)
            if best is None or candidate[0] > best[0]:
                best = candidate
    if best is None:
        return None
    depth, direction, length, span, stop = best
    bonus, volume_note = _volume_bonus(bars)
    bull = direction > 0
    return Pattern(
        "bull_flag" if bull else "bear_flag",
        "Boğa bayrağı" if bull else "Ayı bayrağı",
        "chart",
        direction,
        _clamp(0.5 + min(depth / atr, 10.0) * 0.02 + bonus),
        f"{'boğa' if bull else 'ayı'} bayrağı: {span} mumda {depth / atr:.1f} ATR direk, "
        f"{length} mum dar dinlenme, dinlenme aralığı "
        f"{'yukarı' if bull else 'aşağı'} kırıldı{volume_note}",
        stop_price=stop,
        target_price=close + direction * depth,
    )


def chart_patterns(bars: Sequence[BarRow], atr: float) -> list[Pattern]:
    """Son mumda (kırılımla) tamamlanan grafik formasyonları."""
    window = list(bars)[-WINDOW:]
    if len(window) < 20 or atr <= 0:
        return []
    piv = pivots(window, PIVOT_SIDE, PIVOT_SIDE)
    candidates = [
        _double(window, piv, atr, bottom=True),
        _double(window, piv, atr, bottom=False),
        _head_shoulders(window, piv, atr, inverse=False),
        _head_shoulders(window, piv, atr, inverse=True),
        _triangle(window, piv, atr),
        _flag(window, atr),
    ]
    return [p for p in candidates if p is not None]


def detect_patterns(
    bars: Iterable[BarRow], atr: float, levels: Sequence[Level] = ()
) -> tuple[Pattern, ...]:
    """Bu mumda tamamlanan bütün formasyonlar (``bars`` bir deque de olabilir)."""
    rows = list(bars)[-WINDOW:]
    return tuple(candle_patterns(rows, atr, levels) + chart_patterns(rows, atr))
