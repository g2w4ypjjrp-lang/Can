"""Coin tarayıcı: artımlı istatistikler, sinyal kuralları, ısınma ve performans."""

from __future__ import annotations

import asyncio
import json
import math
import random
import statistics
import time
from pathlib import Path

import pytest

from ati_engine.config import ScannerSettings
from ati_engine.core.bus import EventBus
from ati_engine.core.clock import ManualClock
from ati_engine.core.models import Market, Severity
from ati_engine.market.events import (
    AggTrade,
    Kline,
    OrderBookTop,
    SymbolListed,
    Ticker24h,
    TickerBatch,
)
from ati_engine.scanner.features import FlowWindows, PriceTrail, RollingStats, imbalance, pct_change
from ati_engine.scanner.scanner import MarketScanner, MarketSignal, SignalKind
from ati_engine.storage.database import Database

FIXTURES = Path(__file__).parent / "fixtures" / "binance"
T0 = 1_700_000_000_000  # dakika başı (ms)


# --- Artımlı yapılar ----------------------------------------------------------------------


def test_rolling_stats_matches_statistics_module() -> None:
    rng = random.Random(1)
    values = [rng.uniform(0, 100) for _ in range(500)]
    stats = RollingStats(50)
    for v in values:
        stats.push(v)
    window = values[-50:]
    assert len(stats) == 50
    assert stats.mean == pytest.approx(statistics.fmean(window))
    assert stats.std == pytest.approx(statistics.stdev(window))
    assert stats.zscore(stats.mean + stats.std) == pytest.approx(1.0)


def test_flow_windows_expire_old_seconds() -> None:
    flow = FlowWindows()
    flow.add(1000, 100.0, taker_buy=True)
    flow.add(1030, 50.0, taker_buy=False)
    flow.advance(1030)
    assert flow.totals(60) == (100.0, 50.0)
    flow.advance(1060)  # 1000. saniye 60 sn penceresinden çıktı
    assert flow.totals(60) == (0.0, 50.0)
    assert flow.totals(300) == (100.0, 50.0)
    flow.advance(1400)  # her şey 300 sn penceresinden de çıktı
    assert flow.totals(300) == (0.0, 0.0)


def test_flow_windows_ignore_too_old_trades_and_count_late_ones() -> None:
    flow = FlowWindows()
    flow.add(2000, 10.0, taker_buy=True)
    flow.advance(2000)
    flow.add(1600, 99.0, taker_buy=True)  # 300 sn'den eski: yok sayılır
    flow.add(1900, 5.0, taker_buy=True)  # geri alınmış geç işlem: yalnızca 300 sn'ye girer
    assert flow.totals(60) == (10.0, 0.0)
    assert flow.totals(300) == (15.0, 0.0)


def test_flow_windows_match_brute_force() -> None:
    rng = random.Random(7)
    flow = FlowWindows()
    trades: list[tuple[int, float, bool]] = []
    for now in range(5000, 5600):
        for _ in range(rng.randint(0, 3)):
            sec = now - rng.randint(0, 5)
            quote, buy = rng.uniform(1, 100), rng.random() < 0.5
            flow.add(sec, quote, taker_buy=buy)
            trades.append((sec, quote, buy))
        flow.advance(now)
        if now % 37 == 0:
            for window in (60, 300):
                live = [t for t in trades if now - window < t[0] <= now]
                buy = sum(q for s, q, b in live if b)
                sell = sum(q for s, q, b in live if not b)
                got = flow.totals(window)
                assert got[0] == pytest.approx(buy, abs=1e-6)
                assert got[1] == pytest.approx(sell, abs=1e-6)


def test_price_trail_lookup() -> None:
    trail = PriceTrail(keep_seconds=100)
    trail.update(10, 1.0)
    trail.update(20, 2.0)
    trail.update(20, 2.5)  # aynı saniyede son fiyat
    trail.update(15, 9.0)  # sırası dışı: yok sayılır
    assert trail.price_at(9) is None
    assert trail.price_at(10) == 1.0
    assert trail.price_at(19) == 1.0
    assert trail.price_at(25) == 2.5
    for sec in range(21, 2000):
        trail.update(sec, float(sec))
    assert trail.price_at(1000) is None  # tutulan pencerenin dışında
    assert trail.price_at(1950) == 1950.0


def test_helpers() -> None:
    assert pct_change(110, 100) == pytest.approx(10.0)
    assert pct_change(1, None) is None
    assert imbalance(75, 25) == pytest.approx(0.5)
    assert imbalance(0, 0) is None


# --- Tarayıcı kuralları ----------------------------------------------------------------------


def trade(
    sec: int,
    price: float,
    qty: float,
    *,
    buy: bool = True,
    symbol: str = "SOLUSDT",
    trade_id: int = 0,
) -> AggTrade:
    return AggTrade(
        market=Market.SPOT,
        event_time_ms=sec * 1000,
        symbol=symbol,
        trade_id=trade_id,
        price=price,
        qty=qty,
        trade_time_ms=sec * 1000,
        buyer_is_maker=not buy,
    )


def candle(minute: int, close: float, quote_volume: float, symbol: str = "SOLUSDT") -> Kline:
    open_ms = T0 + minute * 60_000
    return Kline(
        market=Market.SPOT,
        event_time_ms=open_ms + 59_999,
        symbol=symbol,
        interval="1m",
        open_time_ms=open_ms,
        close_time_ms=open_ms + 59_999,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=quote_volume / close,
        quote_volume=quote_volume,
        trades=10,
        taker_buy_volume=0.0,
        taker_buy_quote_volume=0.0,
        closed=True,
    )


class Harness:
    def __init__(self, scanner: MarketScanner, bus: EventBus, clock: ManualClock) -> None:
        self.scanner, self.bus, self.clock = scanner, bus, clock
        self.signals: list[MarketSignal] = []
        bus.subscribe(MarketSignal, self.signals.append, name="test-signals")

    def calm_history(self, minutes: int = 240, *, symbol: str = "SOLUSDT", seed: int = 3) -> None:
        """Sakin geçmiş: dakikalık hacim ~20 bin, getiri oynaklığı ~%0.05."""
        rng = random.Random(seed)
        price = 100.0
        for m in range(minutes):
            price *= math.exp(rng.gauss(0, 0.0005))
            self.scanner.on_kline(candle(m, price, rng.uniform(15_000, 25_000), symbol))
            sec = (T0 + m * 60_000) // 1000 + 59
            self.scanner.on_trade(trade(sec, price, 1.0, symbol=symbol))
        # Geçmişin son işlemlerinden 15 dk sonrası: test işlemleri onlarla karışmasın.
        self.clock.set(max(self.clock.now_ms(), T0 + (minutes + 15) * 60_000))

    @property
    def now_sec(self) -> int:
        return self.clock.now_ms() // 1000

    async def settle(self) -> None:
        for _ in range(20):
            await asyncio.sleep(0)

    def kinds(self) -> list[SignalKind]:
        return [s.kind for s in self.signals]


@pytest.fixture
async def harness(db: Database) -> Harness:
    bus = EventBus()
    clock = ManualClock(T0)
    scanner = MarketScanner(settings=ScannerSettings(), bus=bus, db=db, clock=clock)
    scanner.attach()
    return Harness(scanner, bus, clock)


async def test_quiet_market_produces_no_signals(harness: Harness) -> None:
    harness.calm_history()
    s = harness.now_sec
    for i in range(60):
        harness.scanner.on_trade(trade(s - 60 + i, 100.0, 3.0, buy=i % 2 == 0))
    await harness.scanner.tick(harness.clock.now_ms())
    await harness.settle()
    assert harness.signals == []
    row = harness.scanner.rows[(Market.SPOT, "SOLUSDT")]
    assert row.baseline_minutes == 240
    assert row.volume_z_60s is not None
    assert abs(row.volume_z_60s) < 3


async def test_volume_spike_is_detected_once_and_persisted(harness: Harness, db: Database) -> None:
    harness.calm_history()
    s = harness.now_sec
    for i in range(30):  # 30 sn'de ~600 bin USDT (normal dakikanın ~30 katı)
        harness.scanner.on_trade(trade(s - 30 + i, 100.0, 200.0, buy=i % 2 == 0))
    await harness.scanner.tick(harness.clock.now_ms())
    await harness.scanner.tick(harness.clock.now_ms() + 1000)  # bekleme süresi: tekrar yok
    await harness.settle()
    assert harness.kinds() == [SignalKind.VOLUME_SPIKE]
    signal = harness.signals[0]
    assert signal.symbol == "SOLUSDT"
    assert signal.severity is Severity.CRITICAL
    assert signal.value > 8
    rows = await db.fetchall("SELECT kind, symbol, details FROM market_signals")
    assert rows[0][0] == "volume_spike"
    assert json.loads(rows[0][2])["quote_volume_60s"] > 500_000
    assert "volume_spike" in harness.scanner.rows[(Market.SPOT, "SOLUSDT")].signals


async def test_sudden_price_move_is_detected(harness: Harness) -> None:
    harness.calm_history()
    s = harness.now_sec
    harness.scanner.on_trade(trade(s - 61, 100.0, 1.0))
    harness.scanner.on_trade(trade(s - 1, 103.0, 1.0))  # 60 sn'de %3 (~60 standart sapma)
    await harness.scanner.tick(harness.clock.now_ms())
    await harness.settle()
    assert SignalKind.PRICE_MOVE in harness.kinds()
    signal = next(x for x in harness.signals if x.kind is SignalKind.PRICE_MOVE)
    assert "yükseliş" in signal.message
    row = harness.scanner.rows[(Market.SPOT, "SOLUSDT")]
    assert row.change_1m_pct == pytest.approx(3.0)


async def test_aggressive_buying_is_detected(harness: Harness) -> None:
    harness.calm_history()
    s = harness.now_sec
    for i in range(200):  # 5 dk'ya yayılmış, %95'i agresif alış, toplam ~150 bin
        harness.scanner.on_trade(trade(s - 299 + i, 100.0, 7.5, buy=i % 20 != 0))
    await harness.scanner.tick(harness.clock.now_ms())
    await harness.settle()
    assert SignalKind.FLOW_IMBALANCE in harness.kinds()
    row = harness.scanner.rows[(Market.SPOT, "SOLUSDT")]
    assert row.imbalance_300s == pytest.approx(0.9)


async def test_imbalance_waits_for_full_window(harness: Harness) -> None:
    """Motor yeni açıldığında 5 dk'lık pencere dolmadan dengesizlik sinyali üretilmez."""
    s = harness.now_sec
    for i in range(90):  # yalnızca son 90 sn'lik veri, %95 alış
        harness.scanner.on_trade(trade(s - 90 + i, 100.0, 50.0, buy=i % 20 != 0))
    await harness.scanner.tick(harness.clock.now_ms())
    await harness.settle()
    assert harness.signals == []
    row = harness.scanner.rows[(Market.SPOT, "SOLUSDT")]
    assert row.imbalance_300s == pytest.approx(0.9, abs=0.02)  # değer gösterilir, sinyal yok
    assert row.volume_z_60s is None  # temel çizgi de yok


async def test_liquidity_drop_is_detected(harness: Harness) -> None:
    def book(notional: float) -> OrderBookTop:
        return OrderBookTop(
            market=Market.SPOT,
            event_time_ms=0,
            symbol="BTCUSDT",
            update_id=1,
            best_bid=100.0,
            best_ask=100.1,
            bid_notional_10=notional / 2,
            ask_notional_10=notional / 2,
            imbalance_10=0.0,
        )

    harness.scanner.on_book(book(1_000_000))
    for k in range(5):
        await harness.scanner.tick(harness.clock.now_ms() + k * 1000)
    harness.scanner.on_book(book(300_000))
    await harness.scanner.tick(harness.clock.now_ms() + 5000)
    await harness.settle()
    assert harness.signals == []  # temel çizgi henüz oturmadı (açılış anı)
    harness.scanner.on_book(book(1_000_000))
    for k in range(6, 70):
        await harness.scanner.tick(harness.clock.now_ms() + k * 1000)
    harness.scanner.on_book(book(300_000))
    for k in range(70, 75):  # 5 sn'lik çekilme: anlık titreşim sayılır
        await harness.scanner.tick(harness.clock.now_ms() + k * 1000)
    harness.scanner.on_book(book(1_000_000))
    await harness.scanner.tick(harness.clock.now_ms() + 75_000)
    await harness.settle()
    assert harness.signals == []
    harness.scanner.on_book(book(300_000))
    for k in range(76, 90):  # 14 sn süren çekilme: sinyal
        await harness.scanner.tick(harness.clock.now_ms() + k * 1000)
    await harness.settle()
    assert harness.kinds() == [SignalKind.LIQUIDITY_DROP]
    row = harness.scanner.rows[(Market.SPOT, "BTCUSDT")]
    assert row.spread_bps == pytest.approx(9.995, rel=1e-3)


async def test_new_listing_signal(harness: Harness) -> None:
    await harness.bus.publish(
        SymbolListed(market=Market.USDM_FUTURES, symbol="YENIUSDT", onboard_date_ms=123)
    )
    await harness.settle()
    assert harness.kinds() == [SignalKind.NEW_LISTING]
    assert harness.signals[0].severity is Severity.INFO


async def test_no_signals_without_enough_history(harness: Harness) -> None:
    harness.calm_history(minutes=10)  # en az 30 dk gerekli
    s = harness.now_sec
    for i in range(30):  # dengeli alış/satış: yalnızca geçmişe dayalı kurallar sınanır
        harness.scanner.on_trade(trade(s - 30 + i, 100.0, 500.0, buy=i % 2 == 0))
    harness.scanner.on_trade(trade(s - 1, 110.0, 1.0))
    await harness.scanner.tick(harness.clock.now_ms())
    await harness.settle()
    assert harness.signals == []
    row = harness.scanner.rows[(Market.SPOT, "SOLUSDT")]
    assert row.volume_z_60s is None
    assert row.price_z_60s is None


async def test_recovered_trades_count_in_volume_but_not_price(harness: Harness) -> None:
    harness.calm_history()
    s = harness.now_sec
    harness.scanner.on_trade(trade(s - 5, 100.0, 1.0))
    late = AggTrade(
        market=Market.SPOT,
        event_time_ms=(s - 10) * 1000,
        symbol="SOLUSDT",
        trade_id=1,
        price=50.0,
        qty=10.0,
        trade_time_ms=(s - 10) * 1000,
        buyer_is_maker=True,
        recovered=True,
    )
    harness.scanner.on_trade(late)
    await harness.scanner.tick(harness.clock.now_ms())
    row = harness.scanner.rows[(Market.SPOT, "SOLUSDT")]
    assert row.last_price == 100.0  # geç gelen işlem son fiyatı bozmaz
    assert row.sell_quote_300s == pytest.approx(500.0)


async def test_tickers_update_only_tracked_symbols(harness: Harness) -> None:
    harness.scanner.on_trade(trade(100, 10.0, 1.0, symbol="ETHUSDT"))
    ticker = Ticker24h(
        symbol="ETHUSDT",
        last=11.0,
        open=10.0,
        high=12,
        low=9,
        base_volume=5,
        quote_volume=55,
        event_time_ms=1,
    )
    unknown = Ticker24h(
        symbol="XAUUSDT",
        last=1,
        open=1,
        high=1,
        low=1,
        base_volume=1,
        quote_volume=1,
        event_time_ms=1,
    )
    harness.scanner.on_tickers(
        TickerBatch(market=Market.SPOT, event_time_ms=1, tickers=[ticker, unknown])
    )
    await harness.scanner.tick(harness.clock.now_ms())
    assert (Market.SPOT, "XAUUSDT") not in harness.scanner.rows
    row = harness.scanner.rows[(Market.SPOT, "ETHUSDT")]
    assert row.change_24h_pct == pytest.approx(10.0)
    assert row.quote_volume_24h == 55


async def test_top_sorting(harness: Harness) -> None:
    harness.calm_history(symbol="AAAUSDT", seed=1)
    harness.calm_history(symbol="BBBUSDT", seed=2)
    s = harness.now_sec
    for i in range(20):
        harness.scanner.on_trade(trade(s - 20 + i, 100.0, 100.0, symbol="BBBUSDT"))
    await harness.scanner.tick(harness.clock.now_ms())
    top = harness.scanner.top(Market.SPOT, sort="volume_z_60s", limit=5)
    assert [r.symbol for r in top][:1] == ["BBBUSDT"]
    assert harness.scanner.top(Market.USDM_FUTURES) == []


def test_history_warmup_skips_open_candle_and_dedupes(db: Database) -> None:
    scanner = MarketScanner(settings=ScannerSettings(), bus=EventBus())
    now = T0 + 3 * 60_000 + 30_000
    rows = [
        [
            T0 + m * 60_000,
            "1",
            "1",
            "1",
            str(100 + m),
            "1",
            T0 + m * 60_000 + 59_999,
            "5000",
            3,
            "0",
            "0",
            "0",
        ]
        for m in range(4)  # sonuncusu henüz kapanmadı
    ]
    assert scanner.load_history(Market.SPOT, "SOLUSDT", rows, now) == 3
    state = scanner.state(Market.SPOT, "SOLUSDT")
    assert len(state.vol_stats) == 3
    scanner.on_kline(candle(2, 102.0, 5000))  # canlı akıştan aynı mum: tekrar sayılmaz
    assert len(state.vol_stats) == 3
    assert state.last_close == 102.0


def test_real_klines_replay_flags_largest_move() -> None:
    """Gerçek Binance 1 dk mumlarında en büyük getirili dakika en yüksek |z| değerini alır."""
    rows = json.loads((FIXTURES / "spot_klines_1m.json").read_text())
    closes = [float(r[4]) for r in rows]
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    warm = 240
    scanner = MarketScanner(settings=ScannerSettings(), bus=EventBus())
    scanner.load_history(Market.SPOT, "BTCUSDT", rows[:warm], now_ms=10**15)
    state = scanner.state(Market.SPOT, "BTCUSDT")
    best_z, best_idx = 0.0, -1
    for i in range(warm, len(rows)):
        z = math.log(closes[i] / closes[i - 1]) / max(state.ret_stats.std, 1e-5)
        if abs(z) > abs(best_z):
            best_z, best_idx = z, i
        state.add_closed_candle(int(rows[i][0]), closes[i], float(rows[i][7]))
    expected = max(range(warm, len(rows)), key=lambda i: abs(returns[i - 1]))
    assert best_idx == expected
    assert abs(best_z) > 2


async def test_tick_performance_for_full_universe() -> None:
    """Tüm evren (~1040 sembol) için saniyelik tur 50 ms'nin altında kalmalı."""
    clock = ManualClock(T0)
    scanner = MarketScanner(settings=ScannerSettings(), bus=EventBus(), clock=clock)
    rng = random.Random(5)
    symbols = [f"C{i:04d}USDT" for i in range(1040)]
    for m in range(60):
        for sym in symbols:
            scanner.on_kline(candle(m, 100.0 + rng.random(), rng.uniform(1e4, 2e4), sym))
    clock.set(T0 + 60 * 60_000)
    now_sec = clock.now_ms() // 1000
    for sym in symbols:
        for k in range(10):
            scanner.on_trade(trade(now_sec - k * 20, 100.0, 1.0, symbol=sym))
    durations = []
    for k in range(5):
        start = time.perf_counter()
        await scanner.tick(clock.now_ms() + k * 1000)
        durations.append((time.perf_counter() - start) * 1000)
    print(
        f"tarayıcı turu (1040 sembol): en iyi {min(durations):.1f} ms, en kötü {max(durations):.1f} ms"
    )
    assert len(scanner.rows) == 1040
    assert min(durations) < 50
