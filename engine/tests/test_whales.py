"""Balina radarı: eşik öğrenme, süpürme birleştirme, kümelenme, duvarlar, tasfiyeler,
fiyat etkisi, büyük oyuncu pozisyonlanması ve zincir üstü sınıflandırma."""

from __future__ import annotations

import asyncio
import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from ati_engine.config import WhaleSettings
from ati_engine.core.bus import EventBus
from ati_engine.core.clock import ManualClock
from ati_engine.core.models import Market, Severity
from ati_engine.exchange.rate_limit import WeightBudget
from ati_engine.exchange.rest import BinanceRestClient
from ati_engine.market.events import AggTrade, Liquidation, Ticker24h
from ati_engine.market.orderbook import BookSynchronizer, DepthSnapshot, SyncState
from ati_engine.storage.database import Database
from ati_engine.whales.clusters import ClusterDetector, base_asset
from ati_engine.whales.events import WhaleAlert, WhaleAlertKind, WhaleTrade
from ati_engine.whales.impact import ImpactTracker
from ati_engine.whales.large_trades import LogHistogram, SweepAggregator, WhaleThresholds
from ati_engine.whales.onchain import (
    AddressLabels,
    BlockchairEthereumProvider,
    FlowType,
    OnchainWatcher,
    RawTransfer,
    classify,
)
from ati_engine.whales.positioning import build_snapshot
from ati_engine.whales.radar import WhaleRadar

FIXTURES = Path(__file__).parent / "fixtures"
T0 = 1_700_000_000_000


# --- Dağılım ve eşik ----------------------------------------------------------------------


def test_log_histogram_quantile_is_within_one_bin() -> None:
    rng = random.Random(11)
    values = [math.exp(rng.gauss(8, 1.2)) for _ in range(50_000)]  # log-normal işlem büyüklüğü
    hist = LogHistogram(half_life=10**9)  # sönüm yok
    for v in values:
        hist.add(v)
    exact = sorted(values)[int(0.999 * len(values))]
    estimate = hist.quantile(0.999)
    assert estimate is not None
    assert exact <= estimate <= exact * 10**LogHistogram.STEP * 1.0001  # kova üst sınırı


def test_log_histogram_forgets_old_regime() -> None:
    hist = LogHistogram(half_life=500)
    for _ in range(5_000):
        hist.add(1_000_000.0)  # eski rejim: büyük işlemler
    for _ in range(10_000):
        hist.add(1_000.0)  # yeni rejim: küçük işlemler
    q = hist.quantile(0.99)
    assert q is not None
    assert q < 2_000  # eski büyük işlemler unutuldu


def test_log_histogram_survives_rescaling() -> None:
    hist = LogHistogram(half_life=10)  # ağırlık hızla büyür → yeniden ölçekleme tetiklenir
    for i in range(20_000):
        hist.add(100.0 + i % 7)
    q = hist.quantile(0.5)
    assert q is not None
    assert 100 <= q <= 120


def test_sweep_aggregator_merges_same_millisecond_fills() -> None:
    agg = SweepAggregator()
    assert agg.add("BTCUSDT", 1000, 100.0, 1.0, taker_buy=True) is None
    assert agg.add("BTCUSDT", 1000, 100.5, 2.0, taker_buy=True) is None
    assert agg.add("BTCUSDT", 1000, 101.0, 1.0, taker_buy=True) is None
    done = agg.add("BTCUSDT", 1001, 101.0, 0.1, taker_buy=False)
    assert done is not None
    assert done.fills == 3
    assert done.notional == pytest.approx(100 + 201 + 101)
    assert done.avg_price == pytest.approx(402 / 4)
    assert done.price_impact_pct == pytest.approx(1.0)
    assert done.side == "buy"
    flushed = agg.flush(older_than_ms=2000)
    assert [o.time_ms for o in flushed] == [1001]


def test_thresholds_learn_per_symbol_with_floor() -> None:
    thr = WhaleThresholds(floor_usd=50_000, min_samples=500, refresh_every=100)
    assert thr.threshold("BTCUSDT") == 50_000
    rng = random.Random(2)
    for _ in range(3_000):
        thr.observe("BTCUSDT", math.exp(rng.gauss(math.log(40_000), 1.0)))  # büyük işlemli coin
        thr.observe("SMALLUSDT", math.exp(rng.gauss(math.log(500), 1.0)))  # küçük coin
    assert thr.learned("BTCUSDT")
    assert thr.threshold("BTCUSDT") > 300_000  # yüksek yüzdelik tabanın üstünde
    assert thr.threshold("SMALLUSDT") == 50_000  # küçük coinde taban geçerli


def test_cluster_detector_and_cross_market() -> None:
    det = ClusterDetector(window_s=300, min_count=3, min_notional=500_000)
    assert det.add(Market.SPOT, "SOLUSDT", T0, "buy", 300_000) is None
    assert det.add(Market.SPOT, "SOLUSDT", T0 + 10_000, "buy", 300_000) is None
    cluster = det.add(Market.SPOT, "SOLUSDT", T0 + 20_000, "buy", 300_000)
    assert cluster is not None
    assert cluster.count == 3
    assert cluster.notional == 900_000
    assert not cluster.cross_market
    for i in range(3):
        result = det.add(Market.USDM_FUTURES, "SOLUSDT", T0 + 30_000 + i, "buy", 400_000)
    assert result is not None
    assert result.cross_market  # aynı coin, diğer piyasa, aynı yön
    assert base_asset("SOLUSDT") == "SOL"


def test_cluster_requires_net_flow_and_window() -> None:
    det = ClusterDetector(window_s=60, min_count=3, min_notional=500_000)
    det.add(Market.SPOT, "X", T0, "buy", 300_000)
    det.add(Market.SPOT, "X", T0 + 1, "sell", 800_000)  # ters yönlü büyük satış
    det.add(Market.SPOT, "X", T0 + 2, "buy", 300_000)
    assert det.add(Market.SPOT, "X", T0 + 3, "buy", 300_000) is None  # net 100k < 500k
    det2 = ClusterDetector(window_s=60, min_count=3, min_notional=100_000)
    det2.add(Market.SPOT, "Y", T0, "buy", 300_000)
    det2.add(Market.SPOT, "Y", T0 + 61_000, "buy", 300_000)  # ilk emir pencere dışında
    assert det2.add(Market.SPOT, "Y", T0 + 62_000, "buy", 300_000) is None


# --- Radar --------------------------------------------------------------------------------


def trade(
    symbol: str, time_ms: int, price: float, qty: float, *, buy: bool, market: Market = Market.SPOT
) -> AggTrade:
    return AggTrade(
        market=market,
        event_time_ms=time_ms,
        symbol=symbol,
        trade_id=time_ms,
        price=price,
        qty=qty,
        trade_time_ms=time_ms,
        buyer_is_maker=not buy,
    )


class Harness:
    def __init__(self, radar: WhaleRadar, bus: EventBus, clock: ManualClock) -> None:
        self.radar, self.bus, self.clock = radar, bus, clock
        self.trades: list[WhaleTrade] = []
        self.alerts: list[WhaleAlert] = []
        bus.subscribe(WhaleTrade, self.trades.append, name="t-whale-trades")
        bus.subscribe(WhaleAlert, self.alerts.append, name="t-whale-alerts")

    async def settle(self) -> None:
        for _ in range(30):
            await asyncio.sleep(0)

    async def order(
        self,
        symbol: str,
        time_ms: int,
        notional: float,
        *,
        buy: bool,
        fills: int = 1,
        market: Market = Market.SPOT,
    ) -> None:
        price = 100.0
        for i in range(fills):
            await self.radar.on_trade(
                trade(
                    symbol,
                    time_ms,
                    price + i * 0.01,
                    notional / fills / price,
                    buy=buy,
                    market=market,
                )
            )
        await self.radar.tick(now_ms=time_ms + 2_000)  # bekleyen süpürmeyi tamamla


@pytest.fixture
async def harness(db: Database) -> Harness:
    bus = EventBus()
    clock = ManualClock(T0)
    radar = WhaleRadar(settings=WhaleSettings(), bus=bus, db=db, clock=clock)
    return Harness(radar, bus, clock)


async def test_whale_trade_detection_and_persistence(harness: Harness, db: Database) -> None:
    await harness.order("SOLUSDT", T0, 40_000, buy=True)  # taban (50k) altında
    await harness.order("SOLUSDT", T0 + 5_000, 120_000, buy=True, fills=5)  # 5 kademelik süpürme
    await harness.settle()
    assert len(harness.trades) == 1
    whale = harness.trades[0]
    assert whale.side == "buy"
    assert whale.fills == 5
    assert whale.notional == pytest.approx(120_000, rel=1e-3)  # kademeler 0,01 artan fiyatlı
    assert whale.threshold == 50_000
    rows = await db.fetchall("SELECT source, symbol, side, notional_usd, details FROM whale_events")
    assert rows[0][:3] == ("binance_trade", "SOLUSDT", "buy")
    assert float(rows[0][3]) == pytest.approx(120_000, rel=1e-3)
    assert json.loads(rows[0][4])["fills"] == 5
    assert harness.alerts == []  # mega eşiğin (1M) altında


async def test_mega_trade_alert_and_cooldown(harness: Harness) -> None:
    await harness.order("BTCUSDT", T0, 2_000_000, buy=False, fills=3)
    await harness.order("BTCUSDT", T0 + 10_000, 3_000_000, buy=False)
    await harness.settle()
    kinds = [a.kind for a in harness.alerts]
    assert kinds == [WhaleAlertKind.MEGA_TRADE]  # ikincisi bekleme süresinde
    assert "satış" in harness.alerts[0].message
    assert harness.alerts[0].severity is Severity.WARNING


async def test_accumulation_alert(harness: Harness) -> None:
    for i in range(3):
        await harness.order("ETHUSDT", T0 + i * 30_000, 300_000, buy=True)
    await harness.settle()
    alert = next(a for a in harness.alerts if a.kind is WhaleAlertKind.ACCUMULATION)
    assert alert.notional == pytest.approx(900_000)
    assert "birikim" in alert.message
    assert alert.severity is Severity.INFO
    summary = harness.radar.summary(Market.SPOT, window_s=3600)
    harness.clock.set(T0 + 120_000)
    summary = harness.radar.summary(Market.SPOT, window_s=3600)
    assert summary[0]["symbol"] == "ETHUSDT"
    assert summary[0]["net_usd"] == pytest.approx(900_000)


async def test_liquidation_cascade(harness: Harness, db: Database) -> None:
    for i in range(3):
        await harness.radar.on_liquidation(
            Liquidation(
                market=Market.USDM_FUTURES,
                event_time_ms=T0 + i * 10_000,
                symbol="DOGEUSDT",
                side="SELL",
                price=0.1,
                avg_price=0.1,
                qty=5_000_000,
                filled_qty=5_000_000,
                status="FILLED",
                trade_time_ms=T0 + i * 10_000,
            )
        )
    await harness.radar.tick(now_ms=T0 + 30_000)
    await harness.settle()
    alert = next(a for a in harness.alerts if a.kind is WhaleAlertKind.LIQUIDATION_CASCADE)
    assert alert.side == "long"
    assert alert.notional == pytest.approx(1_500_000)
    rows = await db.fetchall("SELECT source, side FROM whale_events")
    assert rows == [("binance_liquidation", "sell")] * 3
    totals = harness.radar.liquidations.totals(T0 + 30_000)
    assert totals["long"] == pytest.approx(1_500_000)


# --- Duvarlar --------------------------------------------------------------------------------


@dataclass
class FakeBooks:
    syncs: dict[str, BookSynchronizer] = field(default_factory=dict)

    @property
    def symbols(self) -> list[str]:
        return list(self.syncs)

    def get(self, symbol: str) -> BookSynchronizer | None:
        return self.syncs.get(symbol)


@dataclass
class FakeService:
    market: Market
    books: FakeBooks = field(default_factory=FakeBooks)


def book_sync(bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> BookSynchronizer:
    sync = BookSynchronizer(market=Market.SPOT, symbol="BTCUSDT")
    sync.book.reset(DepthSnapshot(last_update_id=1, bids=bids, asks=asks))
    sync.state = SyncState.SYNCED
    return sync


def levels(start: float, step: float, n: int, qty: float = 0.5) -> list[tuple[float, float]]:
    return [(start + i * step, qty) for i in range(n)]


async def test_wall_pulled_and_eaten(harness: Harness) -> None:
    service = FakeService(Market.SPOT)
    bids = levels(99_990.0, -1.0, 40)
    bids[5] = (bids[5][0], 20.0)  # ~2M dolarlık alış duvarı (diğerleri ~50k)
    asks = levels(100_000.0, 1.0, 40)
    service.books.syncs["BTCUSDT"] = book_sync(bids, asks)
    await harness.radar.tick([service], now_ms=T0)
    await harness.radar.tick([service], now_ms=T0 + 6_000)  # 5 sn'den uzun yaşadı
    assert [c.kind for c in harness.radar.wall_changes] == ["appeared"]
    # Fiyat duvara ulaşmadan duvar kalktı → çekildi
    bids[5] = (bids[5][0], 0.5)
    service.books.syncs["BTCUSDT"] = book_sync(bids, asks)
    await harness.radar.tick([service], now_ms=T0 + 8_000)
    await harness.settle()
    assert harness.radar.wall_changes[-1].kind == "pulled"
    assert harness.alerts[-1].kind is WhaleAlertKind.WALL_PULLED

    # Yeni bir satış duvarı; fiyat duvarın üstüne çıkınca → eritildi
    asks2 = levels(100_000.0, 1.0, 40)
    asks2[3] = (asks2[3][0], 25.0)
    service.books.syncs["BTCUSDT"] = book_sync(bids, asks2)
    await harness.radar.tick([service], now_ms=T0 + 20_000)
    await harness.radar.tick([service], now_ms=T0 + 30_000)
    eaten_asks = levels(100_010.0, 1.0, 40)  # en iyi satış duvar fiyatının üstünde
    eaten_bids = levels(100_005.0, -1.0, 40)
    service.books.syncs["BTCUSDT"] = book_sync(eaten_bids, eaten_asks)
    await harness.radar.tick([service], now_ms=T0 + 31_000)
    await harness.settle()
    assert harness.radar.wall_changes[-1].kind == "eaten"
    assert harness.radar.wall_changes[-1].side == "ask"


async def test_short_lived_wall_is_ignored(harness: Harness) -> None:
    service = FakeService(Market.SPOT)
    bids = levels(99_990.0, -1.0, 40)
    bids[2] = (bids[2][0], 30.0)
    service.books.syncs["BTCUSDT"] = book_sync(bids, levels(100_000.0, 1.0, 40))
    await harness.radar.tick([service], now_ms=T0)
    service.books.syncs["BTCUSDT"] = book_sync(
        levels(99_990.0, -1.0, 40), levels(100_000.0, 1.0, 40)
    )
    await harness.radar.tick([service], now_ms=T0 + 2_000)
    assert list(harness.radar.wall_changes) == []


# --- Fiyat etkisi -----------------------------------------------------------------------------


def test_impact_tracker_computes_directional_returns() -> None:
    tracker = ImpactTracker(horizons=(60, 300))
    tracker.register("whale_trade", 1, Market.SPOT, "A", T0, 100.0)  # alış: yükseliş beklenir
    tracker.register("whale_trade", -1, Market.SPOT, "B", T0, 50.0)  # satış: düşüş beklenir
    prices = {"A": 101.0, "B": 49.0}
    results = tracker.due(T0 + 60_000, lambda m, s: prices[s])
    assert {(r.symbol, r.horizon_s) for r in results} == {("A", 60), ("B", 60)}
    a = next(r for r in results if r.symbol == "A")
    b = next(r for r in results if r.symbol == "B")
    assert a.directional_pct == pytest.approx(1.0)
    assert b.return_pct == pytest.approx(-2.0)
    assert b.directional_pct == pytest.approx(2.0)  # düşüş beklentisi doğrulandı
    prices = {"A": 99.0, "B": 51.0}
    results = tracker.due(T0 + 300_000, lambda m, s: prices[s])
    assert len(results) == 2
    assert tracker.pending == 0
    stats = {(r["horizon_s"], r["expected_direction"]): r for r in tracker.summary()}
    assert stats[(60, "up")]["hit_rate"] == 1.0
    assert stats[(300, "up")]["mean_directional_pct"] == pytest.approx(-1.0)


async def test_impact_is_persisted_and_restored(harness: Harness, db: Database) -> None:
    await harness.order("SOLUSDT", T0, 200_000, buy=True)
    harness.radar._prices[(Market.SPOT, "SOLUSDT")] = 102.0  # 60 sn sonra fiyat
    await harness.radar.tick(now_ms=T0 + 61_000)
    rows = await db.fetchall("SELECT kind, direction, horizon_s, return_pct FROM whale_impacts")
    assert rows == [("whale_trade", 1, 60, pytest.approx(2.0))]
    fresh = WhaleRadar(settings=WhaleSettings(), bus=EventBus(), db=db)
    assert await fresh.restore_impact() == 1
    stat = fresh.impact.summary()[0]
    assert stat["samples"] == 1
    assert stat["mean_directional_pct"] == pytest.approx(2.0)


# --- Büyük oyuncu pozisyonlanması --------------------------------------------------------------


def ratio_rows(longs: list[float]) -> list[dict[str, Any]]:
    return [
        {
            "symbol": "X",
            "longAccount": str(v),
            "shortAccount": str(1 - v),
            "longShortRatio": str(v / (1 - v)),
            "timestamp": T0 + i * 300_000,
        }
        for i, v in enumerate(longs)
    ]


def oi_rows(values: list[float]) -> list[dict[str, Any]]:
    return [
        {
            "symbol": "X",
            "sumOpenInterest": "1",
            "sumOpenInterestValue": str(v),
            "timestamp": T0 + i * 300_000,
        }
        for i, v in enumerate(values)
    ]


def test_positioning_snapshot_and_divergence() -> None:
    snap = build_snapshot(
        "X",
        ratio_rows([0.50, 0.53, 0.56]),
        ratio_rows([0.70, 0.67, 0.64]),
        oi_rows([1e9, 1.05e9, 1.1e9]),
    )
    assert snap is not None
    assert snap.top_long_change_pts == pytest.approx(6.0)
    assert snap.global_long_change_pts == pytest.approx(-6.0)
    assert snap.divergence  # büyük oyuncular long'a, kalabalık short'a
    assert snap.open_interest_change_pct == pytest.approx(10.0)
    assert build_snapshot("X", [], ratio_rows([0.5]), oi_rows([1.0])) is None


async def test_positioning_poll_emits_shift_alert(harness: Harness) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("topLongShortPositionRatio"):
            return httpx.Response(200, json=ratio_rows([0.50, 0.52, 0.58]))
        if path.endswith("globalLongShortAccountRatio"):
            return httpx.Response(200, json=ratio_rows([0.60, 0.60, 0.61]))
        return httpx.Response(200, json=oi_rows([1e9, 1e9, 1.02e9]))

    rest = BinanceRestClient(
        "https://example.test",
        budget=WeightBudget(2400),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    class Service:
        market = Market.USDM_FUTURES

        def __init__(self) -> None:
            self.rest = rest
            self.focus = ["BTCUSDT"]

        def tickers(self, limit: int) -> list[Ticker24h]:
            return [
                Ticker24h(
                    symbol="ETHUSDT",
                    last=1,
                    open=1,
                    high=1,
                    low=1,
                    base_volume=1,
                    quote_volume=1,
                    event_time_ms=0,
                )
            ]

    snaps = await harness.radar.poll_positioning(Service())  # type: ignore[arg-type]
    await harness.settle()
    assert {s.symbol for s in snaps} == {"BTCUSDT", "ETHUSDT"}
    shifts = [a for a in harness.alerts if a.kind is WhaleAlertKind.POSITIONING_SHIFT]
    assert {a.symbol for a in shifts} == {"BTCUSDT", "ETHUSDT"}
    assert shifts[0].side == "long"


# --- Zincir üstü --------------------------------------------------------------------------------


def test_labels_and_classification() -> None:
    labels = AddressLabels({"ethereum": {"0xABCDEF": "Binance"}, "bitcoin": {"bc1qXYZ": "Kraken"}})
    assert labels.lookup("ethereum", "0xabcdef") == "Binance"  # EVM: büyük/küçük harf duyarsız
    assert labels.lookup("bitcoin", "bc1qxyz") is None  # BTC adresi olduğu gibi
    assert len(labels) == 2
    assert classify(None, "Binance") is FlowType.EXCHANGE_INFLOW
    assert classify("Binance", None) is FlowType.EXCHANGE_OUTFLOW
    assert classify("Binance", "Kraken") is FlowType.EXCHANGE_INTERNAL
    assert classify(None, None) is FlowType.TRANSFER


def test_blockchair_parser_with_real_response() -> None:
    payload = json.loads((FIXTURES / "onchain_blockchair_eth.json").read_text())
    transfers = BlockchairEthereumProvider.parse(payload)
    assert len(transfers) == len(payload["data"])
    first, raw = transfers[0], payload["data"][0]
    assert first.tx_hash == raw["hash"]
    assert first.amount == pytest.approx(int(raw["value"]) / 1e18)
    assert first.amount_usd == pytest.approx(raw["value_usd"])
    assert first.time_ms > 1_700_000_000_000
    with pytest.raises(RuntimeError, match="430"):
        BlockchairEthereumProvider.parse({"context": {"code": 430}, "data": None})


class FakeProvider:
    name = "fake"

    def __init__(self, transfers: list[RawTransfer]) -> None:
        self.transfers = transfers

    async def fetch(self) -> list[RawTransfer]:
        return list(self.transfers)


async def test_onchain_watcher_classifies_and_dedupes(db: Database) -> None:
    raw = RawTransfer(
        chain="ethereum",
        tx_hash="0x1",
        time_ms=T0,
        asset="ETH",
        amount=4000,
        amount_usd=9_000_000,
        sender="0xAAA",
        recipient="0xEXCH",
    )
    labels = AddressLabels({"ethereum": {"0xexch": "Binance"}})
    watcher = OnchainWatcher(FakeProvider([raw]), labels)
    bus = EventBus()
    alerts: list[WhaleAlert] = []
    bus.subscribe(WhaleAlert, alerts.append, name="t")
    radar = WhaleRadar(settings=WhaleSettings(), bus=bus, db=db, onchain=watcher)
    first = await radar.poll_onchain()
    second = await radar.poll_onchain()  # aynı işlem tekrar gelmez
    await radar.flush()
    for _ in range(20):
        await asyncio.sleep(0)
    assert [t.flow for t in first] == [FlowType.EXCHANGE_INFLOW]
    assert second == []
    assert "Binance borsasına giriş" in alerts[0].message
    rows = await db.fetchall("SELECT source, side, market FROM whale_events")
    assert rows == [("onchain", "inflow", None)]
