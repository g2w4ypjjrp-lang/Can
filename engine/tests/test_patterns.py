"""Formasyon tanıma: mum ve grafik formasyonları yapay mumlarla, bağlam koşulları, ileriye
bakmama (formasyon yalnızca kırılım mumunda), stratejiler ve gerçek veride hatasız çalışma."""

from __future__ import annotations

import json
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

from ati_engine.analysis.features import Bar, FeatureEngine
from ati_engine.analysis.patterns import candle_patterns, chart_patterns, detect_patterns
from ati_engine.history.levels import Level
from ati_engine.strategies.base import StrategyView
from ati_engine.strategies.book import StrategyBook
from ati_engine.strategies.library import ALL_STRATEGIES

HOUR = 3_600_000
ATR = 1.0
FIXTURE = Path(__file__).parent / "fixtures" / "binance" / "spot_btcusdt_1h_1500.json"

Row = tuple[int, float, float, float, float, float]


def bar(i: int, o: float, h: float, low: float, c: float, v: float = 100.0) -> Row:
    return (i * HOUR, o, h, low, c, v)


def path(points: list[float], steps: int = 6, wick: float = 0.2) -> list[Row]:
    """Noktalar arasında doğrusal ilerleyen mumlar (her mum bir öncekinin kapanışında açılır)."""
    closes: list[float] = [points[0]]
    for a, b in pairwise(points):
        closes.extend(a + (b - a) * k / steps for k in range(1, steps + 1))
    rows: list[Row] = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        rows.append(bar(i, o, max(o, c) + wick, min(o, c) - wick, c))
    return rows


def append(
    rows: list[Row], o: float, h: float, low: float, c: float, v: float = 100.0
) -> list[Row]:
    return [*rows, bar(len(rows), o, h, low, c, v)]


def keys(found: object) -> set[str]:
    return {p.key for p in found}  # type: ignore[attr-defined]


def downtrend(start: float = 106.0, n: int = 8) -> list[Row]:
    rows = []
    for i in range(n):
        c = start - i * 0.8
        rows.append(bar(i, c + 0.6, c + 0.7, c - 0.1, c))
    return rows


def uptrend(start: float = 94.0, n: int = 8) -> list[Row]:
    rows = []
    for i in range(n):
        c = start + i * 0.8
        rows.append(bar(i, c - 0.6, c + 0.1, c - 0.7, c))
    return rows


# --- Mum formasyonları -------------------------------------------------------------------------


def test_engulfing_requires_prior_opposite_move_and_gains_at_support() -> None:
    base = downtrend()
    last = base[-1][4]
    rows = append(base, last + 0.3, last + 0.4, last - 0.4, last - 0.3)  # küçük düşüş mumu
    rows = append(rows, last - 0.4, last + 0.9, last - 0.5, last + 0.8)  # saran yükseliş
    found = candle_patterns(rows, ATR)
    assert "bullish_engulfing" in keys(found)
    plain = next(p for p in found if p.key == "bullish_engulfing")
    assert plain.direction == 1 and plain.stop_price is not None and plain.stop_price < last - 0.4
    support = Level(last - 0.6, "support", 4, 0, 0, 90.0, -1.0)
    strong = next(p for p in candle_patterns(rows, ATR, [support]) if p.key == "bullish_engulfing")
    assert strong.strength > plain.strength and "desteği" in strong.reason

    # Aynı iki mum yükseliş trendinin ortasında: dönüş formasyonu sayılmaz.
    up = uptrend()
    top = up[-1][4]
    rows = append(up, top + 0.3, top + 0.4, top - 0.4, top - 0.3)
    rows = append(rows, top - 0.4, top + 0.9, top - 0.5, top + 0.8)
    assert "bullish_engulfing" not in keys(candle_patterns(rows, ATR))


def test_hammer_and_shooting_star() -> None:
    base = downtrend()
    last = base[-1][4]
    hammer = append(base, last, last + 0.15, last - 1.2, last + 0.1)
    assert "hammer" in keys(candle_patterns(hammer, ATR))
    up = uptrend()
    top = up[-1][4]
    star = append(up, top, top + 1.2, top - 0.15, top - 0.1)
    found = candle_patterns(star, ATR)
    assert "shooting_star" in keys(found)
    assert next(p for p in found if p.key == "shooting_star").direction == -1
    # Küçük (ATR'ye göre önemsiz) mumda iğne aranmaz.
    tiny = append(base, last, last + 0.02, last - 0.3, last + 0.01)
    assert "hammer" not in keys(candle_patterns(tiny, ATR))


def test_morning_and_evening_star_and_three_soldiers() -> None:
    base = downtrend()
    c = base[-1][4]
    rows = append(base, c, c + 0.1, c - 1.1, c - 1.0)  # güçlü düşüş
    rows = append(rows, c - 1.05, c - 0.9, c - 1.3, c - 1.1)  # kararsız küçük mum
    rows = append(rows, c - 1.1, c - 0.2, c - 1.15, c - 0.3)  # ortanın üstünde kapanış
    assert "morning_star" in keys(candle_patterns(rows, ATR))

    up = uptrend()
    t = up[-1][4]
    rows = append(up, t, t + 1.1, t - 0.1, t + 1.0)
    rows = append(rows, t + 1.05, t + 1.3, t + 0.9, t + 1.1)
    rows = append(rows, t + 1.1, t + 1.15, t + 0.2, t + 0.3)
    assert "evening_star" in keys(candle_patterns(rows, ATR))

    flat = [bar(i, 100, 100.2, 99.8, 100) for i in range(8)]
    rows = append(flat, 100.0, 100.75, 99.95, 100.7)
    rows = append(rows, 100.5, 101.45, 100.45, 101.4)
    rows = append(rows, 101.2, 102.15, 101.15, 102.1)
    found = candle_patterns(rows, ATR)
    assert "three_white_soldiers" in keys(found)


# --- Grafik formasyonları ------------------------------------------------------------------------


def test_double_bottom_fires_only_on_neckline_break() -> None:
    rows = path([112, 100, 104, 100.2, 103.8])
    assert "double_bottom" not in keys(chart_patterns(rows, ATR))  # henüz kırılım yok
    breakout = append(rows, 103.8, 104.9, 103.7, 104.8, v=250)
    found = chart_patterns(breakout, ATR)
    pattern = next(p for p in found if p.key == "double_bottom")
    assert pattern.direction == 1 and pattern.target_price is not None
    assert pattern.target_price > 104.8 + 3  # ölçülen hareket ≈ boyun - dip
    assert pattern.stop_price is not None and pattern.stop_price < 100
    assert "hacmi ortalamanın" in pattern.reason
    # Kırılımdan bir mum sonra aynı formasyon yeniden bildirilmez.
    after = append(breakout, 104.8, 105.3, 104.7, 105.2)
    assert "double_bottom" not in keys(chart_patterns(after, ATR))


def test_double_top_mirror() -> None:
    rows = path([88, 100, 96, 99.8, 96.2])
    rows = append(rows, 96.2, 96.3, 95.1, 95.2)
    found = chart_patterns(rows, ATR)
    assert next(p for p in found if p.key == "double_top").direction == -1


def test_head_and_shoulders_and_inverse() -> None:
    rows = path([96, 105, 102, 109, 102.2, 105.2, 102.4])
    assert "head_shoulders" not in keys(chart_patterns(rows, ATR))
    rows = append(rows, 102.4, 102.5, 101.0, 101.2)
    pattern = next(p for p in chart_patterns(rows, ATR) if p.key == "head_shoulders")
    assert pattern.direction == -1 and pattern.target_price is not None
    assert pattern.target_price < 101.2 - 5

    mirror = path([114, 105, 108, 101, 107.8, 104.8, 107.6])
    mirror = append(mirror, 107.6, 109.0, 107.5, 108.8)
    assert "inverse_head_shoulders" in keys(chart_patterns(mirror, ATR))


def test_ascending_triangle_breakout() -> None:
    rows = path([98, 105, 100, 105, 102.5, 104.6], steps=5)
    assert not {k for k in keys(chart_patterns(rows, ATR)) if k.endswith("triangle")}
    rows = append(rows, 104.6, 106.0, 104.5, 105.9, v=300)
    found = [p for p in chart_patterns(rows, ATR) if p.key.endswith("triangle")]
    assert found and found[0].key == "ascending_triangle" and found[0].direction == 1
    assert "beklenen yönün tersine" not in found[0].reason


def test_bull_and_bear_flag() -> None:
    flat = [bar(i, 100, 100.2, 99.8, 100) for i in range(20)]
    pole = flat[:]
    for k in range(1, 6):
        c = 100 + 1.2 * k
        pole = append(pole, c - 1.2, c + 0.1, c - 1.3, c)
    rest = pole
    for c in (105.7, 105.5, 105.6, 105.3, 105.5, 105.4):
        rest = append(rest, c + 0.1, c + 0.3, c - 0.3, c)
    assert "bull_flag" not in keys(chart_patterns(rest, ATR))
    rows = append(rest, 105.5, 107.0, 105.4, 106.9)
    flag = next(p for p in chart_patterns(rows, ATR) if p.key == "bull_flag")
    assert flag.direction == 1 and flag.target_price is not None and flag.target_price > 112

    down = flat[:]
    for k in range(1, 6):
        c = 100 - 1.2 * k
        down = append(down, c + 1.2, c + 1.3, c - 0.1, c)
    for c in (94.3, 94.5, 94.4, 94.7, 94.5, 94.6):
        down = append(down, c - 0.1, c + 0.3, c - 0.3, c)
    down = append(down, 94.5, 94.6, 93.0, 93.1)
    assert "bear_flag" in keys(chart_patterns(down, ATR))


# --- Stratejiler ve gerçek veri ------------------------------------------------------------------


def test_pattern_strategies_turn_patterns_into_signals() -> None:
    engine = FeatureEngine()
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))["rows"]
    for r in rows[:400]:
        engine.update(Bar(int(r[0]), r[1], r[2], r[3], r[4], r[5], r[6], r[7]))
    assert engine.snapshot is not None
    snap = replace(engine.snapshot, close=104.8, atr=1.0)
    chart = chart_patterns(
        append(path([112, 100, 104, 100.2, 103.8]), 103.8, 104.9, 103.7, 104.8), 1.0
    )
    view = StrategyView(market="spot", symbol="X", now=snap, prev=None, patterns=tuple(chart))
    strategy = next(s for s in ALL_STRATEGIES if s.name == "chart_pattern")
    signal = strategy.evaluate(view)
    assert signal is not None and signal.direction == 1 and signal.tags == ("double_bottom",)
    assert 1.5 <= signal.target_atr <= 8 and 0.8 <= signal.stop_atr <= 3.5
    candle = next(s for s in ALL_STRATEGIES if s.name == "candle_pattern")
    assert candle.evaluate(view) is None  # mum formasyonu yok
    assert {s.category for s in ALL_STRATEGIES if s.name.endswith("_pattern")} == {"pattern"}


def test_real_data_scan_finds_patterns_without_errors() -> None:
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))["rows"]
    book = StrategyBook("spot", "BTCUSDT")
    seen: dict[str, int] = {}
    for r in rows:
        update = book.update(Bar(int(r[0]), r[1], r[2], r[3], r[4], r[5], r[6], r[7]))
        if update is None:
            continue
        for p in update.patterns:
            assert 0 <= p.strength <= 1 and p.reason and p.direction in (1, -1)
            seen[p.key] = seen.get(p.key, 0) + 1
    assert book.errors == 0
    assert len(seen) >= 6, seen  # 1500 saatlik gerçek veride birçok formasyon türü görülür
    # Ne her mumda formasyon var ne de hiç: seçici.
    assert sum(seen.values()) < len(rows) / 2


def test_detect_patterns_accepts_deque() -> None:
    from collections import deque

    rows = deque(
        append(path([112, 100, 104, 100.2, 103.8]), 103.8, 104.9, 103.7, 104.8), maxlen=500
    )
    assert "double_bottom" in keys(detect_patterns(rows, ATR))
