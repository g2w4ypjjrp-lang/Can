"""Artımlı göstergelerin referans uygulamalarla sayısal doğrulaması.

Referans: TA-Lib (sektör standardı C kütüphanesi). TA-Lib'de bulunmayan Ichimoku ve VWAP için
tanımdan doğrudan yazılmış vektörel numpy hesapları. Veri: gerçek Binance BTCUSDT 1 saatlik
mumları + uzun rastgele yürüyüş.

Her gösterge ayrıca **ileriye bakmama** açısından denetlenir: t anındaki değer, yalnızca t'ye
kadarki veriyle hesaplanan değerle aynıdır.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import talib

from ati_engine.analysis.indicators import (
    ATR,
    EMA,
    MACD,
    OBV,
    RSI,
    SMA,
    Bollinger,
    Fibonacci,
    Ichimoku,
    SessionVWAP,
    StochRSI,
)

FIXTURE = Path(__file__).parent / "fixtures" / "binance" / "spot_btcusdt_1h_1500.json"


def real_bars() -> dict[str, np.ndarray]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    arr = np.array(data["rows"], dtype=np.float64)
    names = data["columns"]
    return {name: arr[:, i] for i, name in enumerate(names)}


def random_bars(n: int = 3000, seed: int = 5) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.005, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.005, n))
    volume = rng.uniform(10, 1000, n)
    times = np.arange(n, dtype=np.float64) * 3_600_000 + 1_790_000_000_000
    return {
        "open_time": times,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "quote_volume": volume * (high + low + close) / 3,
    }


DATASETS = {"gercek_btc_1h": real_bars, "rastgele_yuruyus": random_bars}


def stream(make: Callable[[], Any], feed: Callable[[Any, int], Any], n: int) -> list[Any]:
    indicator = make()
    return [feed(indicator, i) for i in range(n)]


def as_array(values: list[float | None]) -> np.ndarray:
    return np.array([np.nan if v is None else v for v in values], dtype=np.float64)


def assert_matches(
    ours: np.ndarray, ref: np.ndarray, *, start: int = 0, rtol: float = 1e-9
) -> None:
    # Isınma bölgesi aynı olmalı (ikisi de NaN), sonrası sayısal olarak eşleşmeli.
    assert np.array_equal(np.isnan(ours[start:]), np.isnan(ref[start:]))
    mask = ~np.isnan(ref)
    mask[:start] = False
    assert mask.sum() > 100
    np.testing.assert_allclose(ours[mask], ref[mask], rtol=rtol, atol=1e-9)


@pytest.fixture(params=sorted(DATASETS))
def bars(request: pytest.FixtureRequest) -> dict[str, np.ndarray]:
    return DATASETS[request.param]()


# --- TA-Lib ile birebir eşleşenler -------------------------------------------------------------


@pytest.mark.parametrize("period", [9, 21, 50, 200])
def test_ema_matches_talib(bars: dict[str, np.ndarray], period: int) -> None:
    close = bars["close"]
    ours = as_array(stream(lambda: EMA(period), lambda e, i: e.update(close[i]), len(close)))
    assert_matches(ours, talib.EMA(close, period))


def test_sma_matches_talib(bars: dict[str, np.ndarray]) -> None:
    close = bars["close"]
    ours = as_array(stream(lambda: SMA(20), lambda s, i: s.update(close[i]), len(close)))
    assert_matches(ours, talib.SMA(close, 20))


def test_rsi_matches_talib(bars: dict[str, np.ndarray]) -> None:
    close = bars["close"]
    ours = as_array(stream(lambda: RSI(14), lambda r, i: r.update(close[i]), len(close)))
    assert_matches(ours, talib.RSI(close, 14))


def test_atr_matches_talib(bars: dict[str, np.ndarray]) -> None:
    h, lo, c = bars["high"], bars["low"], bars["close"]
    ours = as_array(stream(lambda: ATR(14), lambda a, i: a.update(h[i], lo[i], c[i]), len(c)))
    assert_matches(ours, talib.ATR(h, lo, c, 14))


def test_obv_matches_talib(bars: dict[str, np.ndarray]) -> None:
    c, v = bars["close"], bars["volume"]
    ours = as_array(stream(OBV, lambda o, i: o.update(c[i], v[i]), len(c)))
    assert_matches(ours, talib.OBV(c, v), rtol=1e-10)


def test_bollinger_matches_talib(bars: dict[str, np.ndarray]) -> None:
    close = bars["close"]
    values = stream(lambda: Bollinger(20, 2.0), lambda b, i: b.update(close[i]), len(close))
    upper, middle, lower = talib.BBANDS(close, 20, 2.0, 2.0, 0)
    assert_matches(as_array([v.upper if v else None for v in values]), upper)
    assert_matches(as_array([v.middle if v else None for v in values]), middle)
    assert_matches(as_array([v.lower if v else None for v in values]), lower)


def test_stoch_rsi_matches_talib(bars: dict[str, np.ndarray]) -> None:
    close = bars["close"]
    values = stream(lambda: StochRSI(14, 14, 3, 3), lambda s, i: s.update(close[i]), len(close))
    fastk, fastd = talib.STOCHRSI(close, 14, 14, 3, 0)
    ours_raw = as_array([v.raw if v else None for v in values])
    ours_k = as_array([v.k if v else None for v in values])
    # TA-Lib fastk'yı fastd ile aynı anda yayınlar; ham değer karşılaştırması o noktadan sonra.
    start = int(np.argmax(~np.isnan(fastd)))
    assert_matches(ours_raw, fastk, start=start, rtol=1e-7)
    assert_matches(ours_k, fastd, start=start, rtol=1e-7)


# --- Üstel hafızası olan MACD: tohum farkı sönümlendikten sonra eşleşir -----------------------


def test_macd_converges_to_talib(bars: dict[str, np.ndarray]) -> None:
    close = bars["close"]
    values = stream(lambda: MACD(12, 26, 9), lambda m, i: m.update(close[i]), len(close))
    macd, signal, hist = talib.MACD(close, 12, 26, 9)
    start = 400
    assert_matches(as_array([v.macd if v else None for v in values]), macd, start=start)
    assert_matches(as_array([v.signal if v else None for v in values]), signal, start=start)
    assert_matches(as_array([v.hist if v else None for v in values]), hist, start=start)


# --- TA-Lib'de olmayanlar: tanımdan vektörel referans ------------------------------------------


def rolling(arr: np.ndarray, n: int, fn: Callable[..., np.ndarray]) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    windows = np.lib.stride_tricks.sliding_window_view(arr, n)
    out[n - 1 :] = fn(windows, axis=1)
    return out


def test_ichimoku_matches_definition(bars: dict[str, np.ndarray]) -> None:
    h, lo, c = bars["high"], bars["low"], bars["close"]
    values = stream(Ichimoku, lambda x, i: x.update(h[i], lo[i], c[i]), len(c))
    tenkan = (rolling(h, 9, np.max) + rolling(lo, 9, np.min)) / 2
    kijun = (rolling(h, 26, np.max) + rolling(lo, 26, np.min)) / 2
    span_a_raw = (tenkan + kijun) / 2
    span_b_raw = (rolling(h, 52, np.max) + rolling(lo, 52, np.min)) / 2
    # Bugünün bulutu 26 mum önce hesaplanan değerdir.
    span_a = np.concatenate([np.full(26, np.nan), span_a_raw[:-26]])
    span_b = np.concatenate([np.full(26, np.nan), span_b_raw[:-26]])
    ours_t = as_array([v.tenkan if v else None for v in values])
    ours_k = as_array([v.kijun if v else None for v in values])
    ours_a = as_array([v.span_a if v else None for v in values])
    ours_b = as_array([v.span_b if v else None for v in values])
    mask = ~np.isnan(kijun)
    np.testing.assert_allclose(ours_t[mask], tenkan[mask], rtol=1e-12)
    np.testing.assert_allclose(ours_k[mask], kijun[mask], rtol=1e-12)
    for ours, ref in ((ours_a, span_a), (ours_b, span_b)):
        m = ~np.isnan(ref)
        assert m.sum() > 100
        np.testing.assert_allclose(ours[m], ref[m], rtol=1e-12)


def test_session_vwap_matches_definition(bars: dict[str, np.ndarray]) -> None:
    t, v, q = bars["open_time"], bars["volume"], bars["quote_volume"]
    h, lo, c = bars["high"], bars["low"], bars["close"]
    values = stream(
        SessionVWAP, lambda x, i: x.update(int(t[i]), h[i], lo[i], c[i], v[i], q[i]), len(c)
    )
    day = (t // 86_400_000).astype(np.int64)
    ref = np.empty(len(c))
    for d in np.unique(day):
        idx = np.where(day == d)[0]
        ref[idx] = np.cumsum(q[idx]) / np.cumsum(v[idx])
    np.testing.assert_allclose(as_array(values), ref, rtol=1e-10)


def test_vwap_falls_back_to_typical_price() -> None:
    vwap = SessionVWAP()
    vwap.update(0, 12.0, 8.0, 10.0, 1.0)
    assert vwap.update(60_000, 22.0, 18.0, 20.0, 3.0) == pytest.approx((10 * 1 + 20 * 3) / 4)
    assert vwap.update(86_400_000, 6.0, 4.0, 5.0, 2.0) == pytest.approx(5.0)  # yeni gün


def test_fibonacci_levels() -> None:
    fib = Fibonacci(period=5)
    data = [(101, 99, 100), (111, 105, 110), (121, 115, 120), (116, 108, 112), (115, 109, 113)]
    value = None
    for h, lo, c in data:
        value = fib.update(h, lo, c)
    assert value is not None
    assert value.swing_high == 121 and value.swing_low == 99 and value.trend_up
    span = 22
    assert value.levels[0.618] == pytest.approx(121 - 0.618 * span)
    assert value.position == pytest.approx((113 - 99) / span)
    assert value.nearest_ratio == 0.382  # 121 - 0.382*22 = 112.6 en yakın
    down = Fibonacci(period=3)
    for h, lo, c in [(130, 125, 128), (120, 110, 112), (111, 100, 105)]:
        value = down.update(h, lo, c)
    assert value is not None and not value.trend_up
    assert value.levels[0.0] == 100 and value.levels[1.0] == 130


# --- İleriye bakmama ----------------------------------------------------------------------------


def test_indicators_never_look_ahead() -> None:
    """Gösterge değerleri, ileride gelecek mumlar değiştirildiğinde değişmemeli."""
    base = random_bars(800, seed=9)
    altered = {k: v.copy() for k, v in base.items()}
    cut = 500
    rng = np.random.default_rng(1)
    for key in ("open", "high", "low", "close"):
        altered[key][cut:] *= 1 + rng.normal(0, 0.05, len(altered[key]) - cut)
    altered["high"] = np.maximum.reduce([altered["high"], altered["open"], altered["close"]])
    altered["low"] = np.minimum.reduce([altered["low"], altered["open"], altered["close"]])

    def run(b: dict[str, np.ndarray]) -> list[tuple[Any, ...]]:
        rsi, macd, atr, bb, st = RSI(), MACD(), ATR(), Bollinger(), StochRSI()
        ichi, vwap, fib, obv = Ichimoku(), SessionVWAP(), Fibonacci(), OBV()
        out = []
        for i in range(len(b["close"])):
            h, lo, c, v = b["high"][i], b["low"][i], b["close"][i], b["volume"][i]
            out.append(
                (
                    rsi.update(c),
                    macd.update(c),
                    atr.update(h, lo, c),
                    bb.update(c),
                    st.update(c),
                    ichi.update(h, lo, c),
                    vwap.update(int(b["open_time"][i]), h, lo, c, v),
                    fib.update(h, lo, c),
                    obv.update(c, v),
                )
            )
        return out

    original, changed = run(base), run(altered)
    assert original[:cut] == changed[:cut]
    assert original[cut:] != changed[cut:]
