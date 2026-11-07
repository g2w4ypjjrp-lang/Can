"""Grafik analizi (destek/direnç, trend kırılımı), benzer koşul arama, balina radarının arşiv
üzerinde yeniden oynatılması ve tarihsel veri API'si."""

from __future__ import annotations

import asyncio
import io
import itertools
import math
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import numpy as np
import pytest

from ati_engine.app import Engine
from ati_engine.config import EngineSettings, LocalApiSettings
from ati_engine.core.models import Market
from ati_engine.history.levels import atr, find_levels, pivots, trend_analysis
from ati_engine.history.replay import BASELINE, WHALE, WhaleReplay, iter_aggtrades
from ati_engine.history.similarity import find_similar
from ati_engine.history.sync import HistorySync
from test_history import FakeArchive

HOUR = 3_600_000


def bars_from_closes(closes: list[float], *, spread: float = 0.2) -> list[tuple[float, ...]]:
    """Kapanış dizisinden mum üretir (açılış = önceki kapanış)."""
    rows = []
    prev = closes[0]
    for i, close in enumerate(closes):
        high = max(prev, close) + spread
        low = min(prev, close) - spread
        rows.append((i * HOUR, prev, high, low, close, 100.0))
        prev = close
    return rows


def zigzag(points: list[float], steps: int = 6) -> list[float]:
    """Verilen dönüş noktaları arasında doğrusal yol."""
    path: list[float] = []
    for a, b in itertools.pairwise(points):
        path.extend(a + (b - a) * k / steps for k in range(steps))
    path.append(points[-1])
    return path


# --- ATR ve dönüş noktaları -------------------------------------------------------------------


def test_atr_of_constant_range() -> None:
    rows = [(i * HOUR, 100.0, 101.0, 99.0, 100.0, 1.0) for i in range(30)]
    values = atr(rows, 14)
    assert values[-1] == pytest.approx(2.0)


def test_pivots_find_peaks_and_troughs() -> None:
    rows = bars_from_closes(zigzag([100, 110, 100, 110, 100]), spread=0.0)
    found = pivots(rows, 3, 3)
    highs = [p for p in found if p.kind == "high"]
    lows = [p for p in found if p.kind == "low"]
    assert [round(p.price) for p in highs] == [110, 110]
    assert [round(p.price) for p in lows] == [100]  # kenardaki dipler kesinleşemez


# --- Destek / direnç -------------------------------------------------------------------------


def test_levels_detect_range_bounds() -> None:
    rng = np.random.default_rng(7)
    turns = [100.0]
    for i in range(12):
        turns.append((110.0 if i % 2 == 0 else 100.0) + float(rng.normal(0, 0.3)))
    path = zigzag(turns)
    path.extend(zigzag([path[-1], 105.0], 3)[1:])  # son kapanış aralığın ortasında
    levels = find_levels(bars_from_closes(path), min_touches=3)
    supports = [lv for lv in levels if lv.kind == "support"]
    resistances = [lv for lv in levels if lv.kind == "resistance"]
    assert supports and resistances
    assert supports[0].price == pytest.approx(100, abs=1.0)
    assert resistances[0].price == pytest.approx(110, abs=1.0)
    assert supports[0].touches >= 4 and resistances[0].touches >= 4
    assert max(lv.strength for lv in levels) == 100
    assert supports[0].distance_pct < 0 < resistances[0].distance_pct


def test_levels_need_enough_data() -> None:
    assert find_levels(bars_from_closes([100.0, 101.0, 102.0])) == []


# --- Trend kırılımı ----------------------------------------------------------------------------


def uptrend_then_crash() -> list[tuple[float, ...]]:
    # Yükselen dipler: 100, 104, 108, 112; ardından sert düşüş.
    path = zigzag([100, 108, 104, 112, 108, 116, 112, 120])
    path.extend(zigzag([120, 100], 8)[1:])
    return bars_from_closes(path)


def test_support_line_break_detected() -> None:
    rows = uptrend_then_crash()
    analysis = trend_analysis(rows)
    downs = [b for b in analysis.breaks if b.direction == "down"]
    assert len(downs) == 1
    brk = downs[0]
    assert brk.line.kind == "support"
    assert brk.close < brk.line_value
    assert brk.index > len(rows) - 9  # düşüş bölümünde
    assert brk.line.b_index + 3 <= brk.index  # çizgi kırılımdan önce kesinleşmiş dönüşlerden


def test_resistance_line_break_detected() -> None:
    path = zigzag([120, 112, 116, 108, 112, 104, 108, 100])
    path.extend(zigzag([100, 120], 8)[1:])
    analysis = trend_analysis(bars_from_closes(path))
    ups = [b for b in analysis.breaks if b.direction == "up"]
    assert len(ups) == 1
    assert ups[0].line.kind == "resistance"


def test_clean_uptrend_has_no_break() -> None:
    path = zigzag([100, 108, 104, 112, 108, 116, 112, 120, 116, 124])
    analysis = trend_analysis(bars_from_closes(path))
    assert analysis.breaks == []
    assert any(line.kind == "support" for line in analysis.active)


def test_trend_breaks_do_not_look_ahead() -> None:
    """Tam veride bulunan her kırılım, verinin yalnızca o muma kadarki kısmıyla da bulunur
    (canlıda aynı anda üretilebilir) — ileriye bakma yoktur."""
    rng = np.random.default_rng(3)
    closes = list(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 1500))))
    rows = bars_from_closes([float(c) for c in closes], spread=0.3)
    full = trend_analysis(rows).breaks
    assert len(full) >= 5
    for brk in full:
        partial = trend_analysis(rows[: brk.index + 1]).breaks
        assert partial and partial[-1].index == brk.index
        assert partial[-1].line == brk.line


# --- Benzer piyasa koşulu ---------------------------------------------------------------------


def test_similar_finds_planted_pattern() -> None:
    rng = np.random.default_rng(11)
    n, window = 4000, 48
    log_p = np.cumsum(rng.normal(0, 0.004, n))
    pattern = np.sin(np.linspace(0, 3 * math.pi, window)) * 0.05
    planted_end = 1500
    log_p[planted_end - window + 1 : planted_end + 1] = log_p[planted_end - window] + pattern
    log_p[planted_end + 1 :] += log_p[planted_end] - log_p[planted_end + 1] + 0.002
    log_p[-window:] = log_p[-window - 1] + pattern  # sorgu: aynı şekil en sonda
    closes = list(np.exp(log_p) * 100)
    times = [i * HOUR for i in range(n)]
    result = find_similar(times, closes, window=window, top_k=5, horizons=(6, 24))
    best = result.matches[0]
    assert abs(best.end_index - planted_end) <= 2
    expected = (closes[best.end_index + 6] / closes[best.end_index] - 1) * 100
    assert best.forward_pct[6] == pytest.approx(expected, abs=1e-3)
    ends = [m.end_index for m in result.matches]
    assert all(abs(a - b) >= window for i, a in enumerate(ends) for b in ends[i + 1 :])
    query_start = n - window
    assert all(e < query_start and e + 24 <= n - 1 for e in ends)
    assert [f.horizon for f in result.forward] == [6, 24]
    assert result.forward[0].n == len(result.matches)


def test_similar_flat_query_returns_nothing() -> None:
    closes = [100.0 + i * 0.01 for i in range(500)] + [100.0] * 60
    result = find_similar([i * HOUR for i in range(560)], closes, window=48)
    assert result.matches == []


def test_similar_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="window"):
        find_similar([0, 1], [1.0, 2.0], window=4)
    with pytest.raises(ValueError, match="yeterli"):
        find_similar(list(range(20)), [1.0] * 20, window=48)


# --- Balina radarının arşivde yeniden oynatılması ---------------------------------------------


def make_zip(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("x.csv", text)
    return buffer.getvalue()


def test_iter_aggtrades_spot_and_futures_formats() -> None:
    spot = make_zip(
        "4106938166,80504.01000000,0.00029000,6820762988,6820762988,1793836800262305,False,True\n"
    )
    futures = make_zip(
        "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n"
        "3508075764,80466.4,0.012,8235648673,8235648673,1793836800003,true\n"
    )
    assert list(iter_aggtrades(spot)) == [(1793836800262, 80504.01, 0.00029, False)]
    assert list(iter_aggtrades(futures)) == [(1793836800003, 80466.4, 0.012, True)]


def test_replay_measures_whale_impact_against_baseline() -> None:
    replay = WhaleReplay(
        Market.SPOT, "BTCUSDT", floor_usd=10_000, min_samples=200, horizons=(60,), min_gap_s=300
    )
    t = 1_000_000_000_000
    price = 100.0
    # Isınma: küçük işlemler (eşik öğrenilir), fiyat sabit.
    for i in range(400):
        replay.feed(t, price, 1.0 + (i % 5), buyer_is_maker=i % 2 == 0)
        t += 500
    # Balina alışı, ardından fiyat %1 yükselir.
    replay.feed(t, price, 1_000.0, buyer_is_maker=False)
    t += 1
    for _ in range(10):  # aynı yönde kümelenmiş balinalar bağımsız sayılmaz
        replay.feed(t, price, 1_000.0, buyer_is_maker=False)
        t += 1
    for _ in range(200):
        t += 500
        replay.feed(t, 101.0, 1.0, buyer_is_maker=True)
    report = replay.finish()
    assert report.whales >= 2
    assert report.independent == 1
    stat = replay.impact.stats[(WHALE, 1, 60)]
    assert stat.n == 1
    assert stat.mean == pytest.approx(1.0, abs=1e-6)
    assert (BASELINE, 1, 60) in replay.impact.stats
    comparison = report.comparisons[0]
    assert comparison.direction == 1 and comparison.whale_n == 1


# --- API ---------------------------------------------------------------------------------------


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[Engine]:
    settings = EngineSettings(
        data_dir=tmp_path / "data", log_to_console=False, api=LocalApiSettings(port=0)
    )
    instance = Engine(settings)
    task = asyncio.create_task(instance.run())
    await asyncio.wait_for(instance.ready.wait(), timeout=10)
    yield instance
    assert instance.runtime is not None
    instance.runtime.request_shutdown()
    assert await asyncio.wait_for(task, timeout=10) == 0


async def test_history_api_end_to_end(engine: Engine) -> None:
    runtime = engine.runtime
    assert runtime is not None and runtime.history is not None
    history = runtime.history
    # Ağ yerine sahte arşiv: 3 günlük 1 dakikalık BTCUSDT verisi.
    fake = FakeArchive()
    for day in range(1, 4):
        fake.add_klines(Market.SPOT, "BTCUSDT", f"2026-11-{day:02d}", 1440)
    await history.archive.close()
    history.archive = fake.client()
    history.sync = HistorySync(history.archive, history.store, runtime.db)
    headers = {"Authorization": f"Bearer {runtime.api_token}"}
    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{engine.bound_port}", headers=headers
    ) as client:
        accepted = await client.post(
            "/v1/history/sync", json={"market": "spot", "symbols": ["btcusdt"], "interval": "1m"}
        )
        assert accepted.status_code == 202
        job_id = accepted.json()["id"]
        for _ in range(200):
            status = (await client.get("/v1/history/status")).json()
            job = next(j for j in status["jobs"] if j["id"] == job_id)
            if job["state"] != "running":
                break
            await asyncio.sleep(0.05)
        assert job["state"] == "done", job
        assert job["reports"][0]["rows_inserted"] == 3 * 1440
        assert status["coverage"] == [
            {"market": "spot", "symbol": "BTCUSDT", "interval": "1m", "rows": 4320}
        ]
        # 1 saatlik mumlar 1 dakikalık veriden üretilir.
        candles = (
            await client.get("/v1/history/candles", params={"symbol": "BTCUSDT", "bars": 50})
        ).json()
        assert len(candles["rows"]) == 50
        assert candles["rows"][1][0] - candles["rows"][0][0] == HOUR
        levels = await client.get("/v1/history/levels", params={"symbol": "BTCUSDT"})
        assert levels.status_code == 200 and levels.json()["bars"] == 72
        trend = await client.get(
            "/v1/history/trend", params={"symbol": "BTCUSDT", "interval": "15m"}
        )
        assert trend.status_code == 200 and trend.json()["bars"] == 288
        similar = await client.get(
            "/v1/history/similar",
            params={"symbol": "BTCUSDT", "interval": "5m", "window": 24, "horizons": "3,12"},
        )
        assert similar.status_code == 200, similar.text
        body = similar.json()
        assert body["window"] == 24 and "garanti etmez" in body["disclaimer"]
        bad = await client.get("/v1/history/levels", params={"symbol": "BTCUSDT", "interval": "7m"})
        assert bad.status_code == 422
        bad_sync = await client.post("/v1/history/sync", json={"symbols": ["BTC/USDT"]})
        assert bad_sync.status_code == 422
        assert (
            await client.get("/v1/history/status", headers={"Authorization": ""})
        ).status_code == 401


def test_replay_gap_discards_measurements_spanning_missing_day() -> None:
    replay = WhaleReplay(Market.USDM_FUTURES, "BTCUSDT", floor_usd=10_000, min_samples=200)
    t = 1_000_000_000_000
    for i in range(400):
        replay.feed(t, 100.0, 1.0 + (i % 5), buyer_is_maker=i % 2 == 0)
        t += 1_000
    replay.feed(t, 100.0, 1_000.0, buyer_is_maker=False)
    replay.feed(t + 1, 100.0, 1.0, buyer_is_maker=True)
    assert replay.impact.pending > 0
    replay.gap("2026-10-28")
    assert replay.impact.pending == 0
    # Boşluktan 2 gün sonra fiyat çok farklı: atılan ölçümler istatistiğe girmemeli.
    t += 2 * 86_400_000
    for _ in range(100):
        replay.feed(t, 150.0, 1.0, buyer_is_maker=True)
        t += 1_000
    report = replay.finish()
    assert report.missing_days == ["2026-10-28"]
    assert report.discarded > 0
    assert all(abs(stat.mean) < 1e-9 for stat in replay.impact.stats.values())
