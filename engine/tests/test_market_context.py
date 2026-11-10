"""Piyasa bağlamı: ADX, rejim sınıflandırması, üst zaman dilimi (yalnızca tamamlanmış üst
mumlar), puana etkisi (rejime göre strateji ağırlığı, üst zaman dilimi bileşeni, cezalar) ve
gerçek veride çalışma."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from ati_engine.analysis.context import MarketContext, MarketContextTracker
from ati_engine.analysis.features import Bar
from ati_engine.analysis.indicators import ADX
from ati_engine.scoring.score import OpportunityScorer
from ati_engine.strategies.base import StrategySignal
from ati_engine.strategies.book import StrategyBook
from test_opportunities import bullish_snapshot, inputs

HOUR = 3_600_000
FIXTURE = Path(__file__).parent / "fixtures" / "binance" / "spot_btcusdt_1h_1500.json"


def trending(n: int, step: float = 0.5, start: float = 100.0) -> list[tuple[float, float, float]]:
    rows = []
    for i in range(n):
        c = start + step * i + 0.2 * math.sin(i)
        rows.append((c + 0.4, c - 0.4, c))
    return rows


def choppy(n: int, center: float = 100.0) -> list[tuple[float, float, float]]:
    rows = []
    for i in range(n):
        c = center + (1.0 if i % 2 else -1.0) + 0.3 * math.sin(i / 3)
        rows.append((c + 0.5, c - 0.5, c))
    return rows


def feed(tracker: MarketContextTracker, rows: list[tuple[float, float, float]], start: int = 0):
    ctx = None
    for i, (h, low, c) in enumerate(rows):
        ctx = tracker.update((start + i) * HOUR, c, h, low, c)
    return ctx


def test_adx_separates_trend_from_chop() -> None:
    adx = ADX(14)
    for h, low, c in trending(80):
        value = adx.update(h, low, c)
    assert value is not None and value.adx > 25 and value.plus_di > value.minus_di
    adx = ADX(14)
    for h, low, c in choppy(80):
        value = adx.update(h, low, c)
    assert value is not None and value.adx < 20


def test_regimes() -> None:
    trend = feed(MarketContextTracker(), trending(120))
    assert trend is not None and trend.regime == "trend" and trend.efficiency > 0.3
    flat = feed(MarketContextTracker(), choppy(120))
    assert flat is not None and flat.regime == "range"
    tracker = MarketContextTracker()
    feed(tracker, choppy(150))
    wild = []
    for i in range(6):
        c = 100 + (8 if i % 2 else -8)
        wild.append((c + 6, c - 6, c))
    volatile = feed(tracker, wild, start=150)
    assert volatile is not None and volatile.regime == "volatile"
    assert "Aşırı oynak" in volatile.detail and volatile.to_dict()["regime_title"] == "Aşırı oynak"


def test_higher_timeframe_uses_only_completed_bars() -> None:
    tracker = MarketContextTracker(htf_factor=4)
    rows = trending(4 * 60)
    values = []
    for i, (h, low, c) in enumerate(rows):
        ctx = tracker.update(i * HOUR, c, h, low, c)
        values.append(None if ctx is None else ctx.htf_trend)
    ready = [i for i, v in enumerate(values) if v is not None]
    assert ready and values[-1] is not None and values[-1] > 0.5  # yükselişte pozitif
    # Değer yalnızca 4 saatlik mumun son alt mumunda (i % 4 == 3) değişir.
    for i in range(ready[0] + 1, len(values)):
        if values[i] != values[i - 1]:
            assert i % 4 == 3, i
    assert tracker.value is not None and tracker.value.htf_label == "4 saatlik"


def context(regime: str, htf: float | None = None) -> MarketContext:
    return MarketContext(
        regime=regime,  # type: ignore[arg-type]
        adx=30.0,
        plus_di=25.0,
        minus_di=10.0,
        efficiency=0.5,
        vol_rank=0.5,
        htf_trend=htf,
        htf_label="4 saatlik",
        detail="test",
        htf_detail="EMA21 > EMA50",
    )


def test_regime_reweights_strategies_and_htf_affects_score() -> None:
    scorer = OpportunityScorer()
    snap = bullish_snapshot()
    reversion = [StrategySignal("rsi_reversion", 1, 0.8, "aşırı satım"),
                 StrategySignal("ema_trend", -1, 0.4, "trend")]  # fmt: skip
    in_trend = scorer.score(inputs(snap, reversion, context=context("trend")))
    in_range = scorer.score(inputs(snap, reversion, context=context("range")))
    s_trend = next(c for c in in_trend.components if c.key == "strategies").signal
    s_range = next(c for c in in_range.components if c.key == "strategies").signal
    assert s_range > s_trend  # yatayda ortalamaya dönüş sinyali daha çok sayılır
    assert "yatay rejim" in next(c for c in in_range.components if c.key == "strategies").detail

    trend_signals = [StrategySignal("ema_trend", 1, 0.8, "trend")]
    with_htf = scorer.score(inputs(snap, trend_signals, context=context("trend", 0.8),
                                   quote_volume_24h=3e8))  # fmt: skip
    htf = next(c for c in with_htf.components if c.key == "htf")
    assert htf.available and htf.points > 0 and "4 saatlik" in htf.detail
    assert sum(c.points for c in with_htf.components) == pytest.approx(with_htf.raw_score, abs=0.05)
    assert with_htf.market_context is not None and with_htf.market_context["regime"] == "trend"

    against = scorer.score(inputs(snap, trend_signals, context=context("trend", -0.8),
                                  quote_volume_24h=3e8))  # fmt: skip
    keys = {p.key for p in against.penalties}
    if against.direction == "long":
        assert "htf" in keys
    assert against.score < with_htf.score

    calm = scorer.score(inputs(snap, trend_signals, context=context("trend", 0.8),
                               quote_volume_24h=3e8))  # fmt: skip
    wild = scorer.score(inputs(snap, trend_signals, context=replace(context("volatile", 0.8)),
                               quote_volume_24h=3e8))  # fmt: skip
    assert "regime" in {p.key for p in wild.penalties} and wild.score < calm.score


def test_real_data_contexts() -> None:
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))["rows"]
    book = StrategyBook("spot", "BTCUSDT")
    regimes: dict[str, int] = {}
    htf_ready = 0
    for r in rows:
        update = book.update(Bar(int(r[0]), r[1], r[2], r[3], r[4], r[5], r[6], r[7]))
        if update is None or update.context is None:
            continue
        regimes[update.context.regime] = regimes.get(update.context.regime, 0) + 1
        htf_ready += update.context.htf_trend is not None
        assert 0 <= update.context.efficiency <= 1 and 0 < update.context.vol_rank <= 1
    assert book.errors == 0
    assert len(regimes) >= 3, regimes
    assert htf_ready > 1000
