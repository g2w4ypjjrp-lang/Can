"""Aşama 9: emir defteri tabanlı dolum simülasyonu, sanal işlem yarışması (bağımsız hesaplar,
tick düzeyinde çıkış, funding, kalıcılık, sıralama, likidite filtresi) ve terfi hattı."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest

from ati_engine.analysis.features import Bar, FeatureEngine, Snapshot
from ati_engine.app import Engine
from ati_engine.backtest.service import ensure_strategies, strategy_id
from ati_engine.config import EngineSettings, LocalApiSettings, PaperSettings
from ati_engine.core.bus import EventBus
from ati_engine.core.clock import ManualClock
from ati_engine.core.models import Market
from ati_engine.execution.fills import FillSimulator
from ati_engine.market.events import AggTrade
from ati_engine.market.orderbook import OrderBook
from ati_engine.paper.competition import PaperCompetition, PaperTradeEvent
from ati_engine.scoring.live import LiveBarScore
from ati_engine.scoring.score import OpportunityScorer, ScoreInputs
from ati_engine.storage.database import Database
from ati_engine.strategies.base import StrategySignal

HOUR = 3_600_000
T0 = 1_794_000_000_000 - 1_794_000_000_000 % (8 * HOUR)  # 8 saatin katı
FIXTURE = Path(__file__).parent / "fixtures" / "binance" / "spot_btcusdt_1h_1500.json"


def warm_snapshot() -> Snapshot:
    engine = FeatureEngine()
    for r in json.loads(FIXTURE.read_text(encoding="utf-8"))["rows"][:300]:
        engine.update(Bar(int(r[0]), *r[1:8]))
    assert engine.snapshot is not None
    return engine.snapshot


SNAP = warm_snapshot()


# --- Dolum simülasyonu ----------------------------------------------------------------------


def book(asks: list[tuple[float, float]], bids: list[tuple[float, float]]) -> OrderBook:
    b = OrderBook()
    b.asks = dict(asks)
    b.bids = dict(bids)
    return b


def test_market_buy_walks_the_book() -> None:
    ob = book([(100.0, 1.0), (100.5, 2.0), (101.0, 5.0)], [(99.5, 3.0)])
    sim = FillSimulator(books=lambda m, s: ob, spot_fee=0.001)
    fill = sim.market("spot", "X", 1, 2.5, reference_price=100.0)
    expected = (1.0 * 100.0 + 1.5 * 100.5) / 2.5
    assert fill.price == pytest.approx(expected)
    assert fill.levels == 2 and fill.source == "book"
    assert fill.fee == pytest.approx(expected * 2.5 * 0.001)
    assert fill.slippage_bps == pytest.approx((expected / 100 - 1) * 10_000)
    sell = sim.market("spot", "X", -1, 1.0, reference_price=100.0)
    assert sell.price == 99.5


def test_depth_exhaustion_is_penalized_and_flagged() -> None:
    ob = book([(100.0, 1.0)], [(99.0, 1.0)])
    fill = FillSimulator(books=lambda m, s: ob, exhausted_penalty=0.01).market(
        "spot", "X", 1, 2.0, reference_price=100.0
    )
    assert fill.depth_exhausted
    assert fill.price == pytest.approx((100.0 + 101.0) / 2)


def test_estimate_without_book() -> None:
    sim = FillSimulator(books=lambda m, s: None)
    liquid = sim.market("spot", "X", 1, 1.0, reference_price=100.0, quote_volume_24h=2e9)
    thin = sim.market("spot", "X", 1, 1.0, reference_price=100.0, quote_volume_24h=5e5)
    assert liquid.source == "estimate"
    assert 100 < liquid.price < thin.price  # likidite azaldıkça maliyet artar
    with pytest.raises(ValueError, match="pozitif"):
        sim.market("spot", "X", 1, 0.0, reference_price=100.0)


# --- Yarışma ------------------------------------------------------------------------------------


class ExactFills(FillSimulator):
    """Kaymasız, ücretsiz dolum (bilinen sonuçlu testler için)."""

    def __init__(self) -> None:
        super().__init__(books=lambda m, s: None, spot_fee=0.0, futures_fee=0.0)

    def round_trip_cost(self, market: str, quote_volume_24h: float | None) -> float:
        return 0.0

    def market(self, market: str, symbol: str, side: int, qty: float, **kw: Any):  # type: ignore[no-untyped-def, override]
        from ati_engine.execution.fills import SimulatedFill

        price = kw["reference_price"]
        return SimulatedFill(price, qty, 0.0, "test", 0, 0.0)


def bar_update(
    symbol: str,
    signals: list[StrategySignal],
    *,
    t: int,
    market: Market = Market.SPOT,
    close: float = 100.0,
    atr: float = 1.0,
    volume: float = 1e9,
    funding: float | None = None,
) -> LiveBarScore:
    snapshot = replace(SNAP, open_time_ms=t, close=close, atr=atr, funding_rate=funding)
    inputs = ScoreInputs(
        market=market.value,
        symbol=symbol,
        interval="1h",
        interval_hours=1.0,
        horizon_bars=4,
        snapshot=snapshot,
        signals=signals,
        quote_volume_24h=volume,
    )
    return LiveBarScore(market, symbol, inputs, OpportunityScorer().score(inputs))


def ema(direction: int = 1, strength: float = 0.8) -> StrategySignal:
    return StrategySignal("ema_trend", direction, strength, "test", stop_atr=1.0, target_atr=2.0)


async def make(
    tmp_path: Path, *, clock: ManualClock | None = None, funding: Any = None, **settings: Any
) -> tuple[PaperCompetition, Database, EventBus, list[PaperTradeEvent]]:
    db = Database(tmp_path / "engine.db")
    await db.open()
    await db.migrate()
    bus = EventBus()
    events: list[PaperTradeEvent] = []

    async def collect(event: PaperTradeEvent) -> None:
        events.append(event)

    bus.subscribe(PaperTradeEvent, collect, name="test")
    competition = PaperCompetition(
        settings=PaperSettings(**settings),
        db=db,
        bus=bus,
        fills=ExactFills(),
        clock=clock or ManualClock(T0),
        funding_of=funding,
    )
    await competition.load([Market.SPOT, Market.USDM_FUTURES])
    return competition, db, bus, events


async def trade(
    competition: PaperCompetition,
    symbol: str,
    price: float,
    t: int,
    *,
    market: Market = Market.SPOT,
) -> None:
    await competition.on_trade(
        AggTrade(
            market=market,
            event_time_ms=t,
            symbol=symbol,
            trade_id=t,
            price=price,
            qty=1.0,
            trade_time_ms=t,
            buyer_is_maker=False,
        )
    )


async def test_accounts_are_independent_per_strategy_and_market(tmp_path: Path) -> None:
    competition, db, bus, _ = await make(tmp_path)
    spot = {name for name, m in competition.accounts if m is Market.SPOT}
    futures = {name for name, m in competition.accounts if m is Market.USDM_FUTURES}
    assert "opportunity_score" in spot and "opportunity_score" in futures
    assert "funding_contrarian" in futures and "funding_contrarian" not in spot
    assert len(spot) >= 12
    await competition.on_bars([bar_update("BTCUSDT", [ema()], t=T0)])
    owners = [k for k, a in competition.accounts.items() if a.positions]
    assert owners == [("ema_trend", Market.SPOT)]  # yalnızca sinyal veren strateji açtı
    position = competition.accounts[("ema_trend", Market.SPOT)].positions["BTCUSDT"]
    # Risk 10.000 x %1 = 100, stop 1 → 100 adet (değer 10.000 = sermaye sınırı).
    assert position.qty == pytest.approx(100)
    assert (position.stop, position.target) == (99.0, 102.0)
    await bus.close()
    await db.close()


async def test_tick_level_target_exit_and_persistence(tmp_path: Path) -> None:
    competition, db, bus, events = await make(tmp_path)
    await competition.on_bars([bar_update("BTCUSDT", [ema()], t=T0)])
    await trade(competition, "BTCUSDT", 101.0, T0 + HOUR + 1)
    account = competition.accounts[("ema_trend", Market.SPOT)]
    assert account.positions  # hedef henüz değmedi
    await trade(competition, "BTCUSDT", 102.3, T0 + HOUR + 2)
    assert not account.positions
    (closed,) = account.trades
    assert closed.exit_reason == "target" and closed.exit_price == 102.3
    assert closed.net_pnl == pytest.approx(230)
    await asyncio.sleep(0.05)
    assert [e.action for e in events] == ["opened", "closed"]
    rows = await db.fetchall("SELECT exit_reason, net_pnl FROM paper_trades")
    assert rows == [("target", pytest.approx(230))]
    await bus.close()
    await db.close()

    # Yeniden başlatma: hesap ve işlemler veritabanından geri gelir.
    restarted, db2, bus2, _ = await make(tmp_path)
    again = restarted.accounts[("ema_trend", Market.SPOT)]
    assert again.realized == pytest.approx(230)
    assert len(again.trades) == 1
    await bus2.close()
    await db2.close()


async def test_open_position_survives_restart_and_stop_hits(tmp_path: Path) -> None:
    competition, db, bus, _ = await make(tmp_path)
    await competition.on_bars([bar_update("ETHUSDT", [ema()], t=T0)])
    await bus.close()
    await db.close()
    restarted, db2, bus2, _ = await make(tmp_path)
    account = restarted.accounts[("ema_trend", Market.SPOT)]
    assert "ETHUSDT" in account.positions
    await trade(restarted, "ETHUSDT", 98.9, T0 + 2 * HOUR)
    assert account.trades[-1].exit_reason == "stop"
    assert account.trades[-1].net_pnl == pytest.approx(-110)
    await bus2.close()
    await db2.close()


async def test_strongest_signals_fill_free_slots_and_liquidity_filter(tmp_path: Path) -> None:
    competition, db, bus, _ = await make(tmp_path, max_positions=2, risk_per_trade=0.001)
    updates = [
        bar_update("AAAUSDT", [ema(strength=0.3)], t=T0),
        bar_update("BBBUSDT", [ema(strength=0.9)], t=T0),
        bar_update("CCCUSDT", [ema(strength=0.6)], t=T0),
        bar_update("DDDUSDT", [ema(strength=1.0)], t=T0, volume=1e6),  # likiditesi düşük
    ]
    await competition.on_bars(updates)
    held = set(competition.accounts[("ema_trend", Market.SPOT)].positions)
    assert held == {"BBBUSDT", "CCCUSDT"}
    await bus.close()
    await db.close()


async def test_time_exit_opposite_exit_and_spot_short_ignored(tmp_path: Path) -> None:
    competition, db, bus, _ = await make(tmp_path, max_hold_bars=2)
    account = competition.accounts[("ema_trend", Market.SPOT)]
    await competition.on_bars([bar_update("BTCUSDT", [ema(-1)], t=T0)])
    assert not account.positions  # spot'ta short yok
    await competition.on_bars([bar_update("BTCUSDT", [ema()], t=T0 + HOUR)])
    await competition.on_bars([bar_update("BTCUSDT", [], t=T0 + 2 * HOUR)])
    await competition.on_bars([bar_update("BTCUSDT", [], t=T0 + 3 * HOUR)])
    assert account.trades[-1].exit_reason == "time"
    futures = competition.accounts[("ema_trend", Market.USDM_FUTURES)]
    await competition.on_bars(
        [bar_update("BTCUSDT", [ema()], t=T0 + 4 * HOUR, market=Market.USDM_FUTURES)]
    )
    await competition.on_bars(
        [bar_update("BTCUSDT", [ema(-1)], t=T0 + 5 * HOUR, market=Market.USDM_FUTURES)]
    )
    assert futures.trades[-1].exit_reason == "opposite"
    await bus.close()
    await db.close()


async def test_futures_funding_at_funding_times(tmp_path: Path) -> None:
    competition, db, bus, _ = await make(tmp_path, funding=lambda market, symbol: (100.0, 0.0001))
    account = competition.accounts[("ema_trend", Market.USDM_FUTURES)]
    # T0-2s açılış → mum T0-1s'de kapanır (funding saati değil).
    await competition.on_bars(
        [bar_update("BTCUSDT", [ema()], t=T0 - 2 * HOUR, market=Market.USDM_FUTURES)]
    )
    trade_ = account.positions["BTCUSDT"]
    assert trade_.funding == 0
    # Sonraki mum T0'da kapanır (8 saatin katı) → long pozitif funding öder: 100 x 100 x 0,0001.
    await competition.on_bars([bar_update("BTCUSDT", [], t=T0 - HOUR, market=Market.USDM_FUTURES)])
    assert trade_.funding == pytest.approx(1.0)
    await bus.close()
    await db.close()


async def test_score_competitor_uses_threshold(tmp_path: Path) -> None:
    competition, db, bus, _ = await make(tmp_path, score_threshold=0.0)
    update = bar_update("BTCUSDT", [ema(strength=1.0)], t=T0)
    await competition.on_bars([update])
    score_account = competition.accounts[("opportunity_score", Market.SPOT)]
    assert update.opportunity.direction == "long"  # sabit veride yönlü puan
    assert "BTCUSDT" in score_account.positions
    strict, db2, bus2, _ = await make(tmp_path / "b", score_threshold=100.0)
    await strict.on_bars([update])
    assert not strict.accounts[("opportunity_score", Market.SPOT)].positions
    for b, d in ((bus, db), (bus2, db2)):
        await b.close()
        await d.close()


async def test_equity_snapshots_metrics_and_promotion(tmp_path: Path) -> None:
    clock = ManualClock(T0)
    db = Database(tmp_path / "engine.db")
    await db.open()
    await db.migrate()
    await ensure_strategies(db)
    await db.execute("UPDATE strategies SET stage = 'walk_forward' WHERE id = 'ema_trend.v1'")
    await db.close()
    competition, db, bus, _ = await make(tmp_path, clock=clock)
    stage = await db.fetchone("SELECT stage FROM strategies WHERE id = 'ema_trend.v1'")
    assert stage == ("paper",)  # yarışmaya girince sanal işlem aşaması
    # 35 gün boyunca her gün bir kazançlı işlem (+2R) ve her 4 günde bir kayıp (-1R).
    t = T0
    for day in range(35):
        await trade(competition, "BTCUSDT", 100.0, t + HOUR - 1)  # piyasa 100'de
        await competition.on_bars([bar_update("BTCUSDT", [ema()], t=t)])
        win = day % 4 != 3
        await trade(competition, "BTCUSDT", 102.5 if win else 98.5, t + HOUR + 1)
        t += 24 * HOUR
        clock.advance(24 * HOUR)
        await competition.on_bars([bar_update("ETHUSDT", [], t=t - HOUR)])
    metrics = competition.combined_metrics("ema_trend")
    assert metrics["trades"] == 35 and metrics["days"] >= 30
    assert metrics["profit_factor"] > 1.1
    stage = await db.fetchone("SELECT stage FROM strategies WHERE id = 'ema_trend.v1'")
    assert stage == ("live_candidate",)  # ölçütleri karşıladı
    paper_row = await db.fetchone(
        "SELECT trades FROM strategy_metrics WHERE strategy_id = ? AND mode = 'paper'",
        (strategy_id("ema_trend"),),
    )
    assert paper_row == (35,)
    # Hiçbir strateji kendiliğinden canlı aşamaya geçmez.
    live = await db.fetchall("SELECT id FROM strategies WHERE stage = 'live'")
    assert live == []
    await bus.close()
    await db.close()


async def test_paper_api(tmp_path: Path) -> None:
    settings = EngineSettings(
        data_dir=tmp_path / "data", log_to_console=False, api=LocalApiSettings(port=0)
    )
    engine = Engine(settings)
    task = asyncio.create_task(engine.run())
    await asyncio.wait_for(engine.ready.wait(), timeout=10)
    runtime = engine.runtime
    assert runtime is not None and runtime.paper is not None
    try:
        paper = runtime.paper
        paper.fills = ExactFills()
        await paper.on_bars([bar_update("BTCUSDT", [ema()], t=T0)])
        headers = {"Authorization": f"Bearer {runtime.api_token}"}
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{engine.bound_port}", headers=headers
        ) as client:
            board = (await client.get("/v1/paper/leaderboard", params={"market": "spot"})).json()
            assert len(board) >= 13
            ema_row = next(r for r in board if r["strategy"] == "ema_trend")
            assert ema_row["open_positions"] == 1 and ema_row["stage"] == "research"
            positions = (await client.get("/v1/paper/positions")).json()
            assert positions[0]["symbol"] == "BTCUSDT" and positions[0]["direction"] == "long"
            assert (await client.get("/v1/paper/trades")).json() == []
            stats = (await client.get("/v1/paper/stats")).json()
            assert stats["opened"] == 1 and "gerçek emir" in stats["disclaimer"]
    finally:
        runtime.request_shutdown()
        assert await asyncio.wait_for(task, timeout=15) == 0


async def test_cost_aware_entry_filter_blocks_stablecoin_like_trades(tmp_path: Path) -> None:
    """Canlı denemedeki gerçek durum: oynaklığı çok düşük bir coinde zarar durdur uzaklığı
    komisyonun altında kaldı ve işlem -40R ile kapandı. Maliyet filtresi böyle girişi engeller."""
    db = Database(tmp_path / "engine.db")
    await db.open()
    await db.migrate()
    bus = EventBus()
    competition = PaperCompetition(
        settings=PaperSettings(),
        db=db,
        bus=bus,
        fills=FillSimulator(books=lambda m, s: None),  # gerçek ücret (%0,10) ve kayma
        clock=ManualClock(T0),
    )
    await competition.load([Market.SPOT])
    stable = bar_update("UUSDT", [ema()], t=T0, close=1.0, atr=0.0001)  # stop %0,01
    normal = bar_update("BTCUSDT", [ema()], t=T0, close=100.0, atr=1.0)  # stop %1
    await competition.on_bars([stable, normal])
    held = set(competition.accounts[("ema_trend", Market.SPOT)].positions)
    assert held == {"BTCUSDT"}
    assert competition.stats["skipped_cost"] >= 1
    await bus.close()
    await db.close()
