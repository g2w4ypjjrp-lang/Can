"""Aşama 7: stratejiler, maliyet modeli, açıklanabilir puan, kalibrasyon ve canlı fırsat motoru.

Kabul ölçütleri: puan dökümü puanı birebir vermeli (açıklanabilirlik); kalibrasyon düzeneği
öğrenilebilir sinyalde artan, gürültüde düz bir ilişki göstermeli.
"""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from ati_engine.analysis.features import Bar, FeatureEngine, Snapshot
from ati_engine.app import Engine
from ati_engine.config import EngineSettings, LocalApiSettings, ScoringSettings
from ati_engine.core.bus import EventBus
from ati_engine.core.models import Market
from ati_engine.history.levels import Level
from ati_engine.market.events import Kline
from ati_engine.scoring.calibration import ScoredBar, calibration_table, evaluate_history
from ati_engine.scoring.costs import CostModel
from ati_engine.scoring.live import BarAggregator, OpportunityEngine, OpportunityScored
from ati_engine.scoring.score import (
    BookContext,
    OpportunityScorer,
    ScoreInputs,
    WhaleContext,
)
from ati_engine.storage.database import Database
from ati_engine.strategies.base import ModelView, StrategySignal, StrategyView
from ati_engine.strategies.book import StrategyBook
from ati_engine.strategies.library import ALL_STRATEGIES, strategies_for

HOUR = 3_600_000
FIXTURE = Path(__file__).parent / "fixtures" / "binance" / "spot_btcusdt_1h_1500.json"


def real_rows() -> list[list[float]]:
    return [list(r) for r in json.loads(FIXTURE.read_text(encoding="utf-8"))["rows"]]


def warm_snapshot() -> Snapshot:
    engine = FeatureEngine()
    for r in real_rows()[:400]:
        engine.update(Bar(int(r[0]), r[1], r[2], r[3], r[4], r[5], r[6], r[7]))
    assert engine.snapshot is not None
    return engine.snapshot


def view(now: Snapshot, prev: Snapshot | None = None, **kw: Any) -> StrategyView:
    return StrategyView(market=kw.pop("market", "spot"), symbol="TEST", now=now, prev=prev, **kw)


# --- Stratejiler ---------------------------------------------------------------------------------


def test_catalog_has_at_least_ten_independent_strategies() -> None:
    names = [s.name for s in ALL_STRATEGIES]
    assert len(names) >= 10 and len(set(names)) == len(names)
    assert all(s.description and s.title for s in ALL_STRATEGIES)
    spot = {s.name for s in strategies_for("spot")}
    assert "funding_contrarian" not in spot  # yalnızca vadeli
    assert "funding_contrarian" in {s.name for s in strategies_for("usdm_futures")}


def by_name(name: str) -> Any:
    return next(s for s in ALL_STRATEGIES if s.name == name)


def test_ema_trend_both_directions() -> None:
    base = warm_snapshot()
    up = replace(base, ema9=110, ema21=105, ema50=100, ema200=90, close=111, atr=2)
    down = replace(base, ema9=90, ema21=95, ema50=100, ema200=110, close=89, atr=2)
    flat = replace(base, ema9=100, ema21=101, ema50=99, ema200=100, close=100, atr=2)
    strategy = by_name("ema_trend")
    assert strategy.evaluate(view(up)).direction == 1
    assert strategy.evaluate(view(down)).direction == -1
    assert strategy.evaluate(view(flat)) is None


def test_macd_cross_requires_previous_bar() -> None:
    base = warm_snapshot()
    strategy = by_name("macd_momentum")
    prev = replace(base, macd_hist=-0.1)
    now = replace(base, macd_hist=0.2, macd=0.5, close=base.ema200 + 1)
    signal = strategy.evaluate(view(now, prev))
    assert signal is not None and signal.direction == 1 and 0 <= signal.strength <= 1
    assert strategy.evaluate(view(now)) is None  # önceki mum yoksa kesişim bilinemez


def test_rsi_reversion_and_donchian_and_squeeze() -> None:
    base = warm_snapshot()
    rsi = by_name("rsi_reversion")
    prev = replace(base, rsi=25)
    now = replace(base, rsi=31, close=base.ema200 * 1.05)
    assert rsi.evaluate(view(now, prev)).direction == 1
    donchian = by_name("donchian_breakout")
    breakout = replace(base, donchian_high=100.0, donchian_low=90.0, close=101.0, atr=1.0)
    assert donchian.evaluate(view(breakout)).direction == 1
    squeeze = by_name("squeeze_breakout")
    prev_tight = replace(base, bb_width_rank=0.05)
    out = replace(base, close=base.bb_lower - 1, bb_width_rank=0.2)
    assert squeeze.evaluate(view(out, prev_tight)).direction == -1


def test_level_bounce_and_futures_strategies() -> None:
    base = warm_snapshot()
    level = Level(
        price=base.close - 0.1 * base.atr,
        kind="support",
        touches=4,
        first_time_ms=0,
        last_time_ms=1,
        strength=80,
        distance_pct=-0.1,
    )
    prev = replace(base, rsi=40)
    now = replace(base, rsi=45)
    assert by_name("level_bounce").evaluate(view(now, prev, levels=(level,))).direction == 1
    crowded = replace(base, funding_rate=0.0006, global_long_short=2.5)
    signal = by_name("funding_contrarian").evaluate(view(crowded, market="usdm_futures"))
    assert signal is not None and signal.direction == -1
    model = by_name("model_edge")
    edge = ModelView(p_long=0.55, p_short=0.35, base_long=0.40, base_short=0.38)
    assert model.evaluate(view(base, model=edge)).direction == 1
    assert model.evaluate(view(base)) is None


def test_strategy_book_runs_on_real_data_without_errors() -> None:
    book = StrategyBook("spot", "BTCUSDT")
    fired: dict[str, int] = {}
    updates = 0
    for r in real_rows():
        update = book.update(Bar(int(r[0]), r[1], r[2], r[3], r[4], r[5], r[6], r[7]))
        if update is None:
            continue
        updates += 1
        for signal in update.signals:
            assert signal.direction in (1, -1)
            assert 0 <= signal.strength <= 1
            assert signal.reason
            fired[signal.strategy] = fired.get(signal.strategy, 0) + 1
    assert book.errors == 0
    assert updates > 1000
    assert len(fired) >= 8  # gerçek veride çoğu strateji en az bir kez sinyal verdi
    # Aynı mum tekrar gelirse (ısınma + canlı çakışması) yok sayılır.
    last = real_rows()[-1]
    assert book.update(Bar(int(last[0]), *last[1:])) is None


# --- Maliyet ve puan -----------------------------------------------------------------------------


def test_cost_model() -> None:
    model = CostModel()
    spot = model.estimate("spot", direction=1, holding_hours=4, quote_volume_24h=2e9)
    assert spot.fee_pct == pytest.approx(0.2)
    assert spot.estimated
    real = model.estimate(
        "spot",
        direction=1,
        holding_hours=4,
        quote_volume_24h=2e9,
        spread_bps=1.0,
        book_notional=5e6,
    )
    assert real.spread_pct == pytest.approx(0.01)
    assert not real.estimated
    long_pays = model.estimate(
        "usdm_futures", direction=1, holding_hours=8, quote_volume_24h=1e9, funding_rate=0.0001
    )
    short_gets = model.estimate(
        "usdm_futures", direction=-1, holding_hours=8, quote_volume_24h=1e9, funding_rate=0.0001
    )
    assert long_pays.funding_pct == pytest.approx(0.01)
    assert short_gets.funding_pct == pytest.approx(-0.01)
    assert long_pays.fee_pct == pytest.approx(0.1)


def inputs(snapshot: Snapshot, signals: list[StrategySignal], **kw: Any) -> ScoreInputs:
    return ScoreInputs(
        market=kw.pop("market", "spot"),
        symbol="TEST",
        interval="1h",
        interval_hours=1.0,
        horizon_bars=4,
        snapshot=snapshot,
        signals=signals,
        **kw,
    )


def bullish_snapshot() -> Snapshot:
    base = warm_snapshot()
    return replace(
        base,
        close=110.0,
        ema9=108.0,
        ema21=106.0,
        ema50=100.0,
        ema200=90.0,
        atr=2.0,
        rsi=65.0,
        macd_hist=0.5,
        volume_z=2.5,
        taker_buy_ratio=0.7,
        funding_rate=None,
    )


def test_score_breakdown_adds_up_exactly() -> None:
    """Açıklanabilirlik: bileşen puanlarının toplamı ham puanı, ham puan eksi cezalar nihai
    puanı verir."""
    signals = [
        StrategySignal("ema_trend", 1, 0.8, "trend"),
        StrategySignal("donchian_breakout", 1, 0.6, "kırılım"),
        StrategySignal("rsi_reversion", -1, 0.3, "aşırı alım"),
    ]
    scorer = OpportunityScorer()
    opp = scorer.score(
        inputs(
            bullish_snapshot(),
            signals,
            quote_volume_24h=3e8,
            whale=WhaleContext(net_usd=2e6, threshold_usd=2e5, count=5),
            book=BookContext(imbalance=0.3, spread_bps=1.0, notional=4e6),
        )
    )
    assert opp.direction == "long"
    assert sum(c.points for c in opp.components) == pytest.approx(opp.raw_score, abs=0.05)
    assert opp.raw_score - sum(p.points for p in opp.penalties) == pytest.approx(
        opp.score, abs=0.05
    )
    assert 0 <= opp.score <= 100
    assert sum(c.weight for c in opp.components) == pytest.approx(1.0, abs=1e-3)
    unavailable = {c.key for c in opp.components if not c.available}
    assert unavailable == {"similarity", "model"}
    assert {p.key for p in opp.penalties} >= {"cost"}
    assert opp.stop_price < opp.price < opp.target_price
    assert opp.reward_risk == pytest.approx(
        (opp.target_price - opp.price) / (opp.price - opp.stop_price), rel=1e-3
    )
    assert "garanti" in opp.disclaimer


def test_score_is_symmetric_for_short() -> None:
    bull = bullish_snapshot()
    bear = replace(
        bull,
        close=90.0,
        ema9=92.0,
        ema21=94.0,
        ema50=100.0,
        ema200=110.0,
        rsi=35.0,
        macd_hist=-0.5,
        taker_buy_ratio=0.3,
    )
    scorer = OpportunityScorer()
    long_opp = scorer.score(inputs(bull, [StrategySignal("ema_trend", 1, 0.8, "x")]))
    short_opp = scorer.score(inputs(bear, [StrategySignal("ema_trend", -1, 0.8, "x")]))
    assert long_opp.direction == "long" and short_opp.direction == "short"
    assert short_opp.raw_score == pytest.approx(long_opp.raw_score, abs=0.01)


def test_costs_can_erase_the_score() -> None:
    snapshot = replace(bullish_snapshot(), atr=0.01)  # beklenen hareket çok küçük
    opp = OpportunityScorer().score(
        inputs(snapshot, [StrategySignal("ema_trend", 1, 1.0, "x")], quote_volume_24h=5e5)
    )
    assert opp.raw_score > 0
    assert opp.score == 0  # maliyet hedef hareketten büyük + düşük likidite
    keys = {p.key for p in opp.penalties}
    assert {"cost", "liquidity"} <= keys


def test_target_capped_by_opposing_level() -> None:
    snapshot = bullish_snapshot()
    resistance = Level(
        price=snapshot.close + 1.0,
        kind="resistance",
        touches=5,
        first_time_ms=0,
        last_time_ms=1,
        strength=90,
        distance_pct=0.9,
    )
    opp = OpportunityScorer().score(
        inputs(snapshot, [StrategySignal("ema_trend", 1, 0.8, "x")], levels=[resistance])
    )
    assert opp.target_price == pytest.approx(resistance.price)
    assert any(p.key == "reward_risk" for p in opp.penalties)  # 1 / 3 ATR → düşük ödül/risk


def test_unknown_weight_rejected() -> None:
    with pytest.raises(ValueError, match="Bilinmeyen"):
        OpportunityScorer(weights={"astroloji": 1.0})


# --- Kalibrasyon -------------------------------------------------------------------------------


def test_calibration_table_buckets_and_monotonicity() -> None:
    rng = np.random.default_rng(0)
    bars = []
    for i in range(5000):
        score = float(rng.uniform(0, 100))
        gross = (score - 50) / 100 + float(rng.normal(0, 0.5))  # puan arttıkça getiri artar
        bars.append(ScoredBar(i, "X", 1, score, gross, 0.1))
    table = calibration_table(bars, source="test")
    assert table["n"] == 5000
    nets = [b["mean_net_return_pct"] for b in table["buckets"]]
    assert nets == sorted(nets)
    assert table["spearman"] > 0.2
    noise = [
        ScoredBar(i, "X", 1, float(rng.uniform(0, 100)), float(rng.normal()), 0.1)
        for i in range(5000)
    ]
    assert abs(calibration_table(noise, source="gürültü")["spearman"]) < 0.05


def test_evaluate_history_on_real_data() -> None:
    rows = [tuple(r) for r in real_rows()]
    scored = evaluate_history(
        rows, market="spot", symbol="BTCUSDT", interval="1h", horizon=4, scorer=OpportunityScorer()
    )
    assert len(scored) > 800
    assert all(0 <= b.score <= 100 and b.direction in (1, -1) for b in scored)
    first = scored[0]
    index = next(i for i, r in enumerate(rows) if int(r[0]) == first.time_ms)
    expected = (rows[index + 4][4] / rows[index][4] - 1) * 100 * first.direction
    assert first.gross_return_pct == pytest.approx(expected)
    assert all(math.isfinite(b.cost_pct) and b.cost_pct > 0 for b in scored)


# --- Canlı motor --------------------------------------------------------------------------------


def kline(t: int, close: float, *, market: Market = Market.SPOT, closed: bool = True) -> Kline:
    return Kline(
        market=market,
        event_time_ms=t + 60_000,
        symbol="BTCUSDT",
        interval="1m",
        open_time_ms=t,
        close_time_ms=t + 59_999,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=2.0,
        quote_volume=2.0 * close,
        trades=5,
        taker_buy_volume=1.0,
        taker_buy_quote_volume=1.0 * close,
        closed=closed,
    )


def test_bar_aggregator_emits_on_last_minute() -> None:
    agg = BarAggregator(HOUR)
    out = []
    for m in range(60):
        out += agg.add(kline(m * 60_000, 100.0 + m))
    assert len(out) == 1
    _, _, bar = out[0]
    assert bar.open_time_ms == 0 and bar.open == 100.0 and bar.close == 159.0
    assert bar.high == 160.0 and bar.low == 99.0
    assert bar.volume == pytest.approx(120.0)
    assert agg.add(kline(HOUR, 1.0, closed=False)) == []  # kapanmamış dakika
    # Eksik dakikalarla: bir sonraki saatin ilk dakikası önceki saati kapatır.
    agg.add(kline(HOUR, 200.0))
    out = agg.add(kline(2 * HOUR, 201.0))
    assert len(out) == 1 and out[0][2].open_time_ms == HOUR
    assert agg.incomplete == 1


async def test_live_engine_scores_and_publishes(tmp_path: Path) -> None:
    db = Database(tmp_path / "e.db")
    await db.open()
    await db.migrate()
    bus = EventBus()
    received: list[OpportunityScored] = []

    async def collect(event: OpportunityScored) -> None:
        received.append(event)

    bus.subscribe(OpportunityScored, collect, name="test")
    engine = OpportunityEngine(
        settings=ScoringSettings(publish_min_score=0.0),
        bus=bus,
        db=db,
        calibration_dir=tmp_path / "scoring",
    )
    engine.attach()
    rows = real_rows()
    # Isınma: REST satır biçimi (open_time, o, h, l, c, v, close_time, quote, trades, tbb, tbq).
    rest_rows = [
        [int(r[0]), r[1], r[2], r[3], r[4], r[5], int(r[0]) + HOUR - 1, r[6], 10, 0.0, r[7]]
        for r in rows[:-5]
    ]
    loaded = await engine._load_rows(Market.SPOT, "BTCUSDT", rest_rows, now_ms=int(rows[-1][0]))
    assert loaded == len(rest_rows)
    # Canlı: son 5 saat 1 dakikalık mumlarla gelir.
    for r in rows[-5:]:
        for m in range(60):
            k = kline(int(r[0]) + m * 60_000, float(r[4]))
            await bus.publish(k)
    await asyncio.sleep(0.2)
    opportunities = await engine.process_pending()
    assert len(opportunities) == 5
    latest = engine.latest[(Market.SPOT, "BTCUSDT")]
    assert latest.time_ms == int(rows[-1][0])
    published = [o for o in opportunities if o.direction != "none"]
    await asyncio.sleep(0.1)
    assert len(received) == len(published)
    stored = await db.fetchall("SELECT symbol, score, breakdown FROM opportunities")
    assert len(stored) == len(published)
    assert json.loads(stored[0][2])["components"]
    await engine.close()
    await bus.close()
    await db.close()


# --- API ----------------------------------------------------------------------------------------


async def test_opportunity_api(tmp_path: Path) -> None:
    settings = EngineSettings(
        data_dir=tmp_path / "data", log_to_console=False, api=LocalApiSettings(port=0)
    )
    # Kalibrasyon dosyası motor açılışında okunur.
    calib = settings.paths.scoring_dir / "calibration-spot-1h-h4.json"
    calib.parent.mkdir(parents=True)
    calib.write_text(
        json.dumps(
            {
                "source": "test",
                "buckets": [
                    {
                        "low": lo,
                        "high": lo + 20,
                        "n": 10,
                        "hit_rate": 0.4,
                        "mean_net_return_pct": -0.1,
                        "mean_gross_return_pct": 0.1,
                    }
                    for lo in (0, 20, 40, 60, 80)
                ],
            }
        ),
        encoding="utf-8",
    )
    engine = Engine(settings)
    task = asyncio.create_task(engine.run())
    await asyncio.wait_for(engine.ready.wait(), timeout=10)
    runtime = engine.runtime
    assert runtime is not None and runtime.opportunities is not None and runtime.history
    try:
        rows = real_rows()
        await runtime.history.store.insert(
            "spot",
            "BTCUSDT",
            "1h",
            [
                (
                    int(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    int(r[0]) + HOUR - 1,
                    r[6],
                    10,
                    r[7] / r[4],
                    r[7],
                )
                for r in rows
            ],
        )
        headers = {"Authorization": f"Bearer {runtime.api_token}"}
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{engine.bound_port}", headers=headers
        ) as client:
            strategies = (await client.get("/v1/opportunities/strategies")).json()
            assert len(strategies) >= 10
            detail = await client.get(
                "/v1/opportunities/detail", params={"symbol": "btcusdt", "market": "spot"}
            )
            assert detail.status_code == 200, detail.text
            body = detail.json()
            assert body["source"] == "history"
            assert body["bar_open_time_ms"] == int(rows[-1][0])
            assert len(body["components"]) == 8
            similarity = next(c for c in body["components"] if c["key"] == "similarity")
            if body["direction"] != "none":
                # Depoda 1500 mum var: benzer geçmiş dönemler bulunur ve puana katılır.
                assert similarity["available"], similarity
                assert "benzer geçmiş" in similarity["detail"]
            total = sum(c["points"] for c in body["components"])
            assert total == pytest.approx(body["raw_score"], abs=0.05)
            assert body["calibration"]["source"] == "test"
            assert "garanti" in body["disclaimer"]
            stats = (await client.get("/v1/opportunities/stats")).json()
            assert stats["calibration_loaded"]["spot"] is True
            calibration = (await client.get("/v1/opportunities/calibration")).json()
            assert calibration["markets"]["spot"]["source"] == "test"
            assert (await client.get("/v1/opportunities")).json() == []  # canlı akış kapalı
            missing = await client.get("/v1/opportunities/detail", params={"symbol": "YOKUSDT"})
            assert missing.status_code == 422
    finally:
        runtime.request_shutdown()
        assert await asyncio.wait_for(task, timeout=15) == 0


async def test_warmup_scores_last_closed_bar(tmp_path: Path) -> None:
    from ati_engine.scoring.live import _Context

    db = Database(tmp_path / "e.db")
    await db.open()
    await db.migrate()
    bus = EventBus()
    engine = OpportunityEngine(
        settings=ScoringSettings(publish_min_score=0.0),
        bus=bus,
        db=db,
        calibration_dir=tmp_path / "scoring",
    )
    rows = real_rows()
    rest_rows = [
        [int(r[0]), r[1], r[2], r[3], r[4], r[5], int(r[0]) + HOUR - 1, r[6], 10, 0.0, r[7]]
        for r in rows
    ]
    now = int(rows[-1][0]) + HOUR - 1  # son mum henüz kapanmadı
    await engine._load_rows(Market.SPOT, "BTCUSDT", rest_rows, now, _Context(quote_volume_24h=1e9))
    await engine.process_pending()
    latest = engine.latest[(Market.SPOT, "BTCUSDT")]
    assert latest.time_ms == int(rows[-2][0])  # kapanmış son mum puanlandı
    await engine.close()
    await bus.close()
    await db.close()


async def test_live_candidates_get_similarity_component(tmp_path: Path) -> None:
    """Eşik üstü adaylar için depodaki geçmişten benzerlik eklenir ve puan yeniden hesaplanır;
    benzerlik yalnızca puanlanan mum dahil öncesini kullanır."""
    from ati_engine.scoring.live import _Context

    rows = real_rows()

    class FakeStore:
        def __init__(self) -> None:
            self.calls = 0

        async def candles(self, market: str, symbol: str, interval: str, *, tail: int) -> list:
            self.calls += 1
            return [(int(r[0]), r[1], r[2], r[3], r[4], r[5], 0, r[6], 1, 0.0, r[7]) for r in rows]

    class FakeHistory:
        store = FakeStore()

    db = Database(tmp_path / "e.db")
    await db.open()
    await db.migrate()
    bus = EventBus()
    engine = OpportunityEngine(
        settings=ScoringSettings(publish_min_score=0.0),
        bus=bus,
        db=db,
        calibration_dir=tmp_path / "scoring",
    )
    engine.attach(history=FakeHistory())  # type: ignore[arg-type]
    rest_rows = [
        [int(r[0]), r[1], r[2], r[3], r[4], r[5], int(r[0]) + HOUR - 1, r[6], 10, 0.0, r[7]]
        for r in rows[:1200]
    ]
    await engine._load_rows(
        Market.SPOT, "BTCUSDT", rest_rows, int(rows[1200][0]), _Context(quote_volume_24h=1e9)
    )
    await engine.process_pending()
    latest = engine.latest[(Market.SPOT, "BTCUSDT")]
    assert latest.direction != "none"  # bu veri noktasında yönlü puan var (sabit veri)
    component = next(c for c in latest.components if c.key == "similarity")
    assert component.available
    assert FakeHistory.store.calls == 1
    await engine.close()
    await bus.close()
    await db.close()
