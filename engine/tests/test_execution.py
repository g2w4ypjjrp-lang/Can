"""Aşama 10: emir yöneticisi (idempotentlik, kısmi dolum, dolum tekilleştirme), pozisyon
defteri ve işlem motoru (giriş, zarar durdur, kademeli hedef, başa baş, iz süren stop, OCO,
kapatma) — sanal yürütücüyle uçtan uca."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ati_engine.core.models import (
    EngineState,
    Market,
    OrderStatus,
    OrderType,
    Side,
    SymbolInfo,
    TradingMode,
)
from ati_engine.execution.engine import ExecutionBlocked, TakeProfit, TradeIntent, TradingEngine
from ati_engine.execution.fills import FillSimulator
from ati_engine.execution.orders import OrderManager, make_client_id
from ati_engine.execution.paper_venue import PaperVenue
from ati_engine.execution.positions import PositionBook
from ati_engine.execution.venue import (
    CLIENT_ID_RE,
    ExchangeOrder,
    Fill,
    OrderRequest,
    VenueError,
    VenueEvent,
)
from ati_engine.storage.database import Database
from risk_helpers import approve, make_gate

D = Decimal


class ExactFills(FillSimulator):
    def __init__(self) -> None:
        super().__init__(books=lambda m, s: None, spot_fee=0.0, futures_fee=0.0)

    def market(self, market: str, symbol: str, side: int, qty: float, **kw: Any):  # type: ignore[no-untyped-def, override]
        from ati_engine.execution.fills import SimulatedFill

        return SimulatedFill(kw["reference_price"], qty, 0.0, "test", 0, 0.0)


def info(symbol: str = "BTCUSDT", market: Market = Market.USDM_FUTURES) -> SymbolInfo:
    return SymbolInfo(
        market=market,
        symbol=symbol,
        base_asset=symbol.removesuffix("USDT"),
        quote_asset="USDT",
        status="TRADING",
        tick_size=D("0.1"),
        step_size=D("0.001"),
        min_qty=D("0.001"),
        min_notional=D("5"),
    )


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(tmp_path / "engine.db")
    await database.open()
    await database.migrate()
    yield database
    await database.close()


async def make_engine(
    db: Database,
    market: Market = Market.USDM_FUTURES,
    *,
    state: EngineState = EngineState.RUNNING,
    venue: PaperVenue | None = None,
) -> tuple[TradingEngine, PaperVenue]:
    venue = venue or PaperVenue(market, fills=ExactFills(), initial_quote=D(100_000))
    holder: list[TradingEngine] = []
    engine = TradingEngine(
        venue=venue,
        db=db,
        symbols=lambda s: info(s, market),
        risk_gate=make_gate(db, venue.mode, holder, state=lambda: state),
        engine_state=lambda: state,
        fill_timeout_s=2.0,
    )
    holder.append(engine)
    await engine.start()
    return engine, venue


async def tick(engine: TradingEngine, venue: PaperVenue, symbol: str, price: str) -> None:
    """Fiyatı uygular ve doğan tüm olaylar ile koruma işlemleri bitene kadar bekler. Sabit uyku
    süreleri yavaş CI makinelerinde yetmeyebiliyordu (Windows'ta aralıklı hata)."""
    await venue.on_price(symbol, D(price))
    for _ in range(20):
        await asyncio.wait_for(venue.drained(), timeout=10)
        await engine.settle()
        await asyncio.sleep(0)
        if venue._queue.empty():
            await asyncio.wait_for(venue.drained(), timeout=10)
            return
    raise AssertionError("Olaylar durulmadı")


# --- İstemci kimliği ---------------------------------------------------------------------------


def test_client_ids_are_deterministic_and_binance_compatible() -> None:
    a = make_client_id(TradingMode.TESTNET, "entry", "karar-1")
    assert a == make_client_id(TradingMode.TESTNET, "entry", "karar-1")
    assert a != make_client_id(TradingMode.TESTNET, "entry", "karar-2")
    assert a != make_client_id(TradingMode.LIVE, "entry", "karar-1")
    for purpose in (
        "entry",
        "stop_loss",
        "take_profit",
        "trailing_stop",
        "exit",
        "emergency_close",
    ):
        cid = make_client_id(TradingMode.LIVE, purpose, "x" * 200, 99)
        assert CLIENT_ID_RE.match(cid) and len(cid) <= 36
    with pytest.raises(ValueError, match="kimliği"):
        OrderRequest("geçersiz kimlik!", "BTCUSDT", Side.BUY, OrderType.MARKET, D(1))


# --- İdempotentlik ------------------------------------------------------------------------------


class FlakyVenue(PaperVenue):
    """İlk ``place`` çağrısında hata: ``after`` ise emir borsaya ulaşır sonra bağlantı kopar,
    değilse hiç ulaşmaz."""

    def __init__(self, *, after: bool, error: VenueError | None = None) -> None:
        super().__init__(Market.USDM_FUTURES, fills=ExactFills(), initial_quote=D(100_000))
        self.after = after
        self.error = error or VenueError("zaman aşımı", unknown=True)
        self.place_calls = 0
        self.prices["BTCUSDT"] = D(100)

    async def place(self, request: OrderRequest) -> ExchangeOrder:
        self.place_calls += 1
        if self.place_calls == 1:
            if self.after:
                await super().place(request)
            raise self.error
        return await super().place(request)


def market_request(cid: str = "atitenTEST00") -> OrderRequest:
    return OrderRequest(cid, "BTCUSDT", Side.BUY, OrderType.MARKET, D("1"))


async def test_timeout_after_acceptance_does_not_duplicate(db: Database) -> None:
    venue = FlakyVenue(after=True)
    gate = make_gate(db, venue.mode)
    manager = OrderManager(db, venue, verifier=gate, backoff_s=0.01)
    request = market_request()
    record = await manager.submit(request, approval=approve(gate, request, venue))
    assert record.status is OrderStatus.FILLED
    assert venue.place_calls == 1  # sorgu emri buldu: yeniden gönderilmedi
    assert len(venue._orders) == 1


async def test_timeout_before_acceptance_retries_same_id(db: Database) -> None:
    venue = FlakyVenue(after=False)
    gate = make_gate(db, venue.mode)
    manager = OrderManager(db, venue, verifier=gate, backoff_s=0.01)
    request = market_request()
    record = await manager.submit(request, approval=approve(gate, request, venue))
    assert record.status is OrderStatus.FILLED
    assert venue.place_calls == 2  # bulunamadı → aynı kimlikle bir kez daha
    assert list(venue._orders) == ["atitenTEST00"]
    assert manager.stats["retries"] == 1


async def test_rejection_is_final_and_resubmission_is_ignored(db: Database) -> None:
    venue = PaperVenue(Market.SPOT, fills=ExactFills(), initial_quote=D(10))
    venue.prices["BTCUSDT"] = D(100)
    gate = make_gate(db, venue.mode)
    manager = OrderManager(db, venue, verifier=gate)
    request = market_request()
    record = await manager.submit(request, approval=approve(gate, request, venue))
    assert record.status is OrderStatus.REJECTED and "-2010" in (record.last_error or "")
    again = await manager.submit(request, approval=approve(gate, request, venue))
    assert again is record  # aynı karar ikinci kez gönderilmez
    row = await db.fetchone("SELECT status FROM orders WHERE id = 'atitenTEST00'")
    assert row == ("REJECTED",)


async def test_unknown_state_left_for_reconciliation(db: Database) -> None:
    class AlwaysDown(FlakyVenue):
        async def place(self, request: OrderRequest) -> ExchangeOrder:
            self.place_calls += 1
            raise VenueError("bağlantı yok", unknown=True)

    venue = AlwaysDown(after=False)
    gate = make_gate(db, venue.mode)
    manager = OrderManager(db, venue, verifier=gate, max_attempts=3, backoff_s=0.01)
    request = market_request()
    record = await manager.submit(request, approval=approve(gate, request, venue))
    assert record.status is OrderStatus.PENDING_NEW and record.unresolved
    assert venue.place_calls == 3 and manager.stats["unknown"] == 1
    reloaded = OrderManager(db, venue, verifier=gate)
    (open_record,) = await reloaded.load_open()
    assert open_record.client_id == "atitenTEST00" and open_record.unresolved


async def test_duplicate_fills_counted_once_and_orphans_linked(db: Database) -> None:
    venue = PaperVenue(Market.USDM_FUTURES, fills=ExactFills(), initial_quote=D(100_000))
    venue.prices["BTCUSDT"] = D(100)
    seen: list[Fill] = []

    async def on_fill(record: Any, fill: Fill) -> None:
        seen.append(fill)

    manager = OrderManager(db, venue, verifier=make_gate(db, venue.mode), on_fill=on_fill)
    request = OrderRequest(
        "atitslTEST00",
        "BTCUSDT",
        Side.SELL,
        OrderType.STOP_MARKET,
        D(1),
        trigger_price=D(90),
        reduce_only=True,
        purpose="stop_loss",
    )
    await manager.submit(request)
    fill = Fill("", "999", "T1", "BTCUSDT", Side.SELL, D(90), D(1), D(0), "USDT", False, 1)
    # Koşullu emrin tetiklenen gerçek emri (999) henüz bağlanmadan dolum geldi: bekletilir.
    assert await manager.apply_fill(fill) is False and seen == []
    order = manager.records["atitslTEST00"]
    linked = ExchangeOrder(
        order.client_id,
        order.exchange_id or "",
        "BTCUSDT",
        Side.SELL,
        OrderType.STOP_MARKET,
        OrderStatus.FILLED,
        D(1),
        D(1),
        actual_order_id="999",
    )
    await manager.apply_order(linked)
    assert len(seen) == 1  # bağlantı gelince işlendi
    assert await manager.apply_fill(fill) is False  # ikinci kez sayılmaz
    assert manager.stats["dup_fills"] == 1


# --- Pozisyon defteri ---------------------------------------------------------------------------


async def test_position_book_average_price_partial_close_and_flip(db: Database) -> None:
    book = PositionBook(db, mode=TradingMode.PAPER, market=Market.USDM_FUTURES)
    common = {"symbol": "BTCUSDT", "base_asset": "BTC", "commission_asset": "USDT", "ts": 1}
    await book.apply_fill(side=Side.BUY, qty=D(1), price=D(100), commission=D("0.1"), **common)
    await book.apply_fill(side=Side.BUY, qty=D(1), price=D(110), commission=D("0.1"), **common)
    position = book.positions["BTCUSDT"]
    assert position.entry_price == D(105) and position.quantity == D(2)
    change = await book.apply_fill(
        side=Side.SELL, qty=D("0.5"), price=D(120), commission=D(0), **common
    )
    assert change.realized == D("7.5")  # (120-105) x 0,5
    flip = await book.apply_fill(side=Side.SELL, qty=D(3), price=D(100), commission=D(0), **common)
    assert flip.closed is not None and flip.closed.realized_pnl == D("7.5") + D("-7.5")
    assert book.positions["BTCUSDT"].quantity == D(-1.5)
    assert book.positions["BTCUSDT"].side == "SHORT"
    rows = await db.fetchall("SELECT side, status FROM positions ORDER BY opened_at, status")
    assert sorted(rows) == [("LONG", "closed"), ("SHORT", "open")]


async def test_spot_commission_in_base_reduces_quantity(db: Database) -> None:
    book = PositionBook(db, mode=TradingMode.PAPER, market=Market.SPOT)
    change = await book.apply_fill(
        symbol="BTCUSDT",
        base_asset="BTC",
        side=Side.BUY,
        qty=D(1),
        price=D(100),
        commission=D("0.001"),
        commission_asset="BTC",
        ts=1,
    )
    assert change.position is not None
    assert change.position.quantity == D("0.999")
    assert change.position.fees == D("0.1")


# --- İşlem motoru: Futures ------------------------------------------------------------------------


def futures_intent(**kw: Any) -> TradeIntent:
    values: dict[str, Any] = {
        "decision_id": "k1",
        "market": Market.USDM_FUTURES,
        "symbol": "BTCUSDT",
        "direction": 1,
        "quantity": D("2"),
        "reference_price": D(100),
        "stop_loss": D("95.03"),
        "take_profits": (TakeProfit(D("110.07"), D("0.5")), TakeProfit(D(120), D("0.5"))),
    }
    values.update(kw)
    return TradeIntent(**values)


async def test_futures_long_tp1_moves_stop_to_breakeven(db: Database) -> None:
    engine, venue = await make_engine(db)
    await venue.on_price("BTCUSDT", D(100))
    managed = await engine.open(futures_intent())
    assert managed.state == "open" and managed.filled_qty == D(2)
    open_orders = await venue.open_orders("BTCUSDT")
    kinds = sorted((o.type.value, o.trigger_price, o.quantity) for o in open_orders)
    # Stop yukarı (fiyata doğru) 95,1'e, hedef aşağı 110,0'a yuvarlandı.
    assert kinds == [
        ("STOP_MARKET", D("95.1"), D(2)),
        ("TAKE_PROFIT_MARKET", D("110.0"), D(1)),
        ("TAKE_PROFIT_MARKET", D(120), D(1)),
    ]
    await tick(engine, venue, "BTCUSDT", "110.5")  # ilk hedef
    position = engine.positions.positions["BTCUSDT"]
    assert position.quantity == D(1)
    stops = [o for o in await venue.open_orders("BTCUSDT") if o.type is OrderType.STOP_MARKET]
    assert [s.trigger_price for s in stops] == [D(100)]  # başa baş
    await tick(engine, venue, "BTCUSDT", "99.9")  # başa baş stop
    assert "BTCUSDT" not in engine.positions.positions
    assert await venue.open_orders("BTCUSDT") == []  # kalan hedef iptal edildi
    row = await db.fetchone("SELECT realized_pnl, status FROM positions WHERE symbol = 'BTCUSDT'")
    assert row is not None and D(row[0]) == D("10.5") + D("-0.1") and row[1] == "closed"
    await engine.stop()


async def test_futures_short_stop_loss(db: Database) -> None:
    engine, venue = await make_engine(db)
    await venue.on_price("ETHUSDT", D(100))
    await engine.open(
        futures_intent(symbol="ETHUSDT", direction=-1, stop_loss=D(105), take_profits=())
    )
    assert engine.positions.positions["ETHUSDT"].quantity == D(-2)
    await tick(engine, venue, "ETHUSDT", "106")
    assert "ETHUSDT" not in engine.positions.positions
    row = await db.fetchone("SELECT realized_pnl FROM positions WHERE symbol = 'ETHUSDT'")
    assert row is not None and D(row[0]) == D(-12)  # (100-106) x 2
    await engine.stop()


async def test_futures_trailing_stop(db: Database) -> None:
    engine, venue = await make_engine(db)
    await venue.on_price("BTCUSDT", D(100))
    await engine.open(
        futures_intent(
            stop_loss=D(90),  # risk kapısı: zarar durdur zorunlu (iz süren stop ek korumadır)
            take_profits=(),
            trailing_callback_pct=D(2),
            trailing_activation=D(105),
        )
    )
    for price in ("104", "106", "110", "108.5"):
        await tick(engine, venue, "BTCUSDT", price)
    assert "BTCUSDT" in engine.positions.positions  # 110'dan %2 geri çekilme 107,8
    await tick(engine, venue, "BTCUSDT", "107.7")
    assert "BTCUSDT" not in engine.positions.positions
    await engine.stop()


async def test_runner_trails_after_first_target_from_current_price(db: Database) -> None:
    """Bot düzeni: yarısı ilk hedefte, kalan yarı iz süren stopla. İlk hedef dolunca zarar durdur
    girişe çekilir ve iz süren stop etkinleştirme fiyatı olmadan (hemen) yeniden kurulur."""
    engine, venue = await make_engine(db)
    await venue.on_price("BTCUSDT", D(100))
    await engine.open(
        futures_intent(
            stop_loss=D(95),
            take_profits=(TakeProfit(D(105), D("0.5")),),
            trailing_callback_pct=D(2),
            trailing_activation=D(105),
        )
    )
    await tick(engine, venue, "BTCUSDT", "105.5")  # ilk hedef doldu
    position = engine.positions.positions["BTCUSDT"]
    assert position.quantity == D(1)
    orders = await venue.open_orders()
    assert [o.type for o in orders if o.type is OrderType.TRAILING_STOP_MARKET] == [
        OrderType.TRAILING_STOP_MARKET
    ]
    stops = [o.trigger_price for o in orders if o.type is OrderType.STOP_MARKET]
    assert stops == [D(100)]  # zarar durdur girişte
    rebuilt = [r.request for r in venue._resting.values() if r.request is not None
               and r.request.type is OrderType.TRAILING_STOP_MARKET]  # fmt: skip
    assert [r.activation_price for r in rebuilt] == [None]  # hemen, güncel fiyattan
    for price in ("108", "112"):
        await tick(engine, venue, "BTCUSDT", price)
    assert "BTCUSDT" in engine.positions.positions
    await tick(engine, venue, "BTCUSDT", "109.7")  # 112'den %2 geri çekilme: 109,76
    assert "BTCUSDT" not in engine.positions.positions
    await engine.stop()


async def test_manual_close_cancels_protection(db: Database) -> None:
    engine, venue = await make_engine(db)
    await venue.on_price("BTCUSDT", D(100))
    await engine.open(futures_intent())
    record = await engine.close("BTCUSDT", reason="kullanıcı")
    assert record is not None and record.status is OrderStatus.FILLED
    await engine.settle()
    assert await venue.open_orders() == []
    assert "BTCUSDT" not in engine.positions.positions
    await engine.stop()


async def test_preconditions_block_unsafe_entries(db: Database) -> None:
    halted, _ = await make_engine(db, state=EngineState.SAFE_MODE)
    with pytest.raises(ExecutionBlocked, match="safe_mode"):
        await halted.open(futures_intent())
    await halted.stop()
    spot, venue = await make_engine(db, Market.SPOT)
    await venue.on_price("BTCUSDT", D(100))
    with pytest.raises(ExecutionBlocked, match="short"):
        await spot.open(futures_intent(market=Market.SPOT, direction=-1))
    with pytest.raises(ExecutionBlocked, match="en düşük"):
        await spot.open(futures_intent(market=Market.SPOT, quantity=D("0.01")))
    await spot.stop()
    futures, venue = await make_engine(db)
    await venue.on_price("BTCUSDT", D(100))
    await futures.open(futures_intent())
    with pytest.raises(ExecutionBlocked, match="zaten"):
        await futures.open(futures_intent(decision_id="k2"))
    await futures.stop()


# --- İşlem motoru: Spot OCO ------------------------------------------------------------------------


async def test_spot_oco_take_profit_cancels_sibling_and_breakeven(db: Database) -> None:
    engine, venue = await make_engine(db, Market.SPOT)
    await venue.on_price("BTCUSDT", D(100))
    await engine.open(futures_intent(market=Market.SPOT))
    orders = await venue.open_orders("BTCUSDT")
    assert len(orders) == 4  # iki OCO (hedef + stop)
    assert len({o.list_id for o in orders}) == 2
    await tick(engine, venue, "BTCUSDT", "110.5")
    assert engine.positions.positions["BTCUSDT"].quantity == D(1)
    remaining = await venue.open_orders("BTCUSDT")
    stops = [o.trigger_price for o in remaining if o.type is OrderType.STOP_MARKET]
    assert stops == [D(100)]  # kalan OCO başa baş stopla yeniden kuruldu
    await tick(engine, venue, "BTCUSDT", "99")
    assert "BTCUSDT" not in engine.positions.positions
    assert await venue.open_orders("BTCUSDT") == []
    assert venue.wallet["BTC"] == 0
    await engine.stop()


async def test_restart_restores_positions_and_open_orders(db: Database) -> None:
    engine, venue = await make_engine(db)
    await venue.on_price("BTCUSDT", D(100))
    await engine.open(futures_intent())
    await engine.stop()
    restarted, _ = await make_engine(db, venue=venue)
    assert restarted.positions.positions["BTCUSDT"].quantity == D(2)
    assert len(restarted.orders.open_records()) == 3
    await restarted.stop()


async def test_events_flow_into_order_manager(db: Database) -> None:
    engine, venue = await make_engine(db)
    await venue.on_price("BTCUSDT", D(100))
    await engine.open(futures_intent(take_profits=(), stop_loss=D(90)))
    (stop,) = [r for r in engine.orders.open_records() if r.purpose == "stop_loss"]
    canceled = ExchangeOrder(
        stop.client_id,
        stop.exchange_id or "",
        "BTCUSDT",
        Side.SELL,
        OrderType.STOP_MARKET,
        OrderStatus.CANCELED,
        D(2),
    )
    await venue._queue.put(VenueEvent(kind="order", order=canceled))
    await asyncio.sleep(0.05)
    assert engine.orders.records[stop.client_id].status is OrderStatus.CANCELED
    await engine.stop()


async def test_settle_returns_when_background_task_already_finished(db: Database) -> None:
    """Gerileme: görev bitmiş ama kümeden çıkaran geri çağrısı henüz çalışmamışken ``settle``
    olay döngüsüne dönmeden sonsuza dek dönüyordu (Windows CI'da takılma)."""
    engine, _venue = await make_engine(db)

    async def quick() -> None:
        return None

    engine._spawn(quick())
    task = next(iter(engine._background))
    # Görevi bitir ama discard geri çağrısının çalışacağı döngü adımına geçme.
    while not task.done():
        await asyncio.sleep(0)
    if task not in engine._background:  # geri çağrı yine de çalıştıysa pencereyi yeniden kur
        engine._background.add(task)
    await asyncio.wait_for(engine.settle(), timeout=5)
    assert engine._background == set()
    await engine.stop()


async def test_trade_notices_carry_stop_target_score_and_close_details(db: Database) -> None:
    """Bildirimler (telefon, Telegram) için: açılışta stop/hedef/puan/gerekçe, kapanışta giriş
    fiyatı, yüzde kâr/zarar, kapanış nedeni ve süre."""
    engine, venue = await make_engine(db)
    notices: list[Any] = []

    async def record(notice: Any) -> None:
        notices.append(notice)

    engine.on_trade = record
    await venue.on_price("ETHUSDT", D(100))
    await engine.open(
        futures_intent(
            symbol="ETHUSDT", direction=-1, stop_loss=D(105), take_profits=(),
            opportunity_score=81.5, reason="Düşüş kırılımı",
        )
    )  # fmt: skip
    await tick(engine, venue, "ETHUSDT", "106")
    opened, closed = notices
    assert opened.action == "opened" and opened.side == "short"
    assert opened.stop_loss == "105" and opened.take_profit is None
    assert opened.score == 81.5 and opened.reason == "Düşüş kırılımı"
    assert closed.action == "closed" and closed.entry_price == "100"
    assert closed.close_reason == "zarar durdur (stop)"
    assert closed.pnl_pct is not None and closed.pnl_pct < -5.9  # -12 / (100 x 2)
    assert closed.duration_s is not None and closed.duration_s >= 0
    await engine.stop()
