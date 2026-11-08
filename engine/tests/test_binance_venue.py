"""Aşama 10: Binance yürütücüleri, 2026 kurallarını taklit eden sahte borsaya karşı gerçek
HTTP/WebSocket üzerinden (imza, Algo servisi, -4120, kullanıcı akışları, arıza enjeksiyonu) ve
işlem motoru uçtan uca (test ağı modu)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
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
from ati_engine.exchange.rate_limit import WeightBudget
from ati_engine.exchange.rest import BinanceApiError, BinanceRestClient
from ati_engine.exchange.signing import HmacSigner
from ati_engine.execution.binance_venue import (
    BinanceFuturesVenue,
    BinanceSpotVenue,
    map_error,
)
from ati_engine.execution.engine import TakeProfit, TradeIntent, TradingEngine
from ati_engine.execution.orders import OrderManager, make_client_id
from ati_engine.execution.venue import (
    OcoRequest,
    OrderRejected,
    OrderRequest,
    VenueError,
    VenueEvent,
)
from ati_engine.storage.database import Database
from fake_exchange import FakeExchange
from risk_helpers import approve, make_gate

D = Decimal


@pytest.fixture
async def exchange() -> AsyncIterator[FakeExchange]:
    fake = await FakeExchange().start()
    fake.prices.update({"BTCUSDT": D(100), "ETHUSDT": D(100)})
    yield fake
    await fake.stop()


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(tmp_path / "engine.db")
    await database.open()
    await database.migrate()
    yield database
    await database.close()


def rest_client(fake: FakeExchange, secret: str = "test-gizli") -> BinanceRestClient:  # noqa: S107
    return BinanceRestClient(
        fake.rest_url,
        budget=WeightBudget(6000),
        api_key=fake.api_key,
        signer=HmacSigner(secret),
    )


def spot_venue(fake: FakeExchange, secret: str = "test-gizli") -> BinanceSpotVenue:  # noqa: S107
    return BinanceSpotVenue(
        rest_client(fake, secret),
        mode=TradingMode.TESTNET,
        api_key=fake.api_key,
        signer=HmacSigner(secret),
        ws_url=fake.ws_api_url,
    )


def futures_venue(fake: FakeExchange) -> BinanceFuturesVenue:
    return BinanceFuturesVenue(
        rest_client(fake),
        mode=TradingMode.TESTNET,
        api_key=fake.api_key,
        signer=HmacSigner("test-gizli"),
        ws_url=fake.private_ws_url,
    )


def info(symbol: str, market: Market) -> SymbolInfo:
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


async def wait_for(condition: Callable[[], bool], within: float = 5.0) -> None:
    async with asyncio.timeout(within):
        while not condition():
            await asyncio.sleep(0.01)


async def collect(venue: Any, count: int, within: float = 5.0) -> list[VenueEvent]:
    events: list[VenueEvent] = []
    iterator = venue.events()
    async with asyncio.timeout(within):
        while len(events) < count:
            events.append(await anext(iterator))
    return events


def order(
    cid: str,
    otype: OrderType = OrderType.MARKET,
    side: Side = Side.BUY,
    qty: str | None = "1",
    **kw: Any,
) -> OrderRequest:
    return OrderRequest(
        client_id=cid,
        symbol=kw.pop("symbol", "BTCUSDT"),
        side=side,
        type=otype,
        quantity=D(qty) if qty is not None else None,
        purpose=kw.pop("purpose", "entry"),
        **kw,
    )


# --- Spot ------------------------------------------------------------------------------------------


async def test_spot_market_order_signed_and_fills_reported(exchange: FakeExchange) -> None:
    venue = spot_venue(exchange)
    placed = await venue.place(order("atiTspot1"))
    assert placed.status is OrderStatus.FILLED and placed.executed_qty == D(1)
    assert placed.avg_price == D(100)
    method, path, params = exchange.requests[-1]
    assert (method, path) == ("POST", "/api/v3/order")
    assert params["newOrderRespType"] == "FULL" and "timestamp" in params
    events = await collect(venue, 1)
    assert events[0].fill is not None and events[0].fill.qty == D(1)
    fills = await venue.fills("BTCUSDT", placed.exchange_id)
    assert [f.price for f in fills] == [D(100)] and fills[0].commission == D("0.1")
    queried = await venue.query("BTCUSDT", "atiTspot1")
    assert queried is not None and queried.status is OrderStatus.FILLED
    assert await venue.query("BTCUSDT", "yok") is None
    balances = {b.asset: b.free for b in await venue.balances()}
    assert balances["BTC"] == D(1) and balances["USDT"] == D(100_000) - D("100.1")
    await venue.rest.close()
    await venue.close()


async def test_spot_wrong_secret_is_rejected_by_signature_check(exchange: FakeExchange) -> None:
    venue = spot_venue(exchange, secret="yanlis-gizli")
    with pytest.raises(OrderRejected) as caught:
        await venue.place(order("atiTspot2"))
    assert caught.value.code == -1022
    assert exchange.signature_failures == 1 and exchange.spot_orders == {}
    await venue.rest.close()


async def test_spot_oco_and_user_stream_via_websocket_api(exchange: FakeExchange) -> None:
    venue = spot_venue(exchange)
    iterator = venue.events()
    await venue.place(order("atiTbuy", qty="2"))
    first = await anext(iterator)  # REST yanıtındaki dolum
    assert first.fill is not None
    await wait_for(lambda: venue.stream_connected)
    legs = await venue.place_oco(
        OcoRequest(
            list_client_id="atiTlist",
            symbol="BTCUSDT",
            side=Side.SELL,
            quantity=D(2),
            take_profit_price=D(110),
            stop_price=D(95),
            tp_client_id="atiTtp",
            sl_client_id="atiTsl",
        )
    )
    assert {o.type for o in legs} == {OrderType.LIMIT, OrderType.STOP_MARKET}
    assert len({o.list_id for o in legs}) == 1
    _, path, params = exchange.requests[-1]
    assert path == "/api/v3/orderList/oco"
    assert params["aboveType"] == "LIMIT_MAKER" and params["belowType"] == "STOP_LOSS"
    assert "belowTrailingDelta" not in params  # None değerler gönderilmez
    assert len(await venue.open_orders("BTCUSDT")) == 2
    await exchange.set_price("BTCUSDT", D(111))
    events = []
    async with asyncio.timeout(5):
        while len(events) < 2:
            event = await anext(iterator)
            if event.order is not None and event.order.client_id in ("atiTtp", "atiTsl"):
                events.append(event)
    by_id = {e.order.client_id: e for e in events if e.order}
    assert by_id["atiTtp"].order.status is OrderStatus.FILLED  # type: ignore[union-attr]
    assert by_id["atiTtp"].fill is not None and by_id["atiTtp"].fill.price == D(110)
    assert by_id["atiTsl"].order.status is OrderStatus.CANCELED  # type: ignore[union-attr]
    assert await venue.open_orders("BTCUSDT") == []
    await venue.rest.close()
    await venue.close()


async def test_spot_stream_subscription_rejected_with_bad_signature(
    exchange: FakeExchange,
) -> None:
    venue = spot_venue(exchange, secret="yanlis-gizli")
    venue.events()
    await wait_for(lambda: venue.stream_errors >= 1)
    assert not venue.stream_connected and exchange.signature_failures >= 1
    await venue.rest.close()
    await venue.close()


# --- Futures ---------------------------------------------------------------------------------------


async def test_futures_conditional_orders_use_algo_service(exchange: FakeExchange) -> None:
    venue = futures_venue(exchange)
    await venue.set_leverage("BTCUSDT", 3)
    entry = await venue.place(order("atiTfent", qty="2"))
    assert entry.status is OrderStatus.FILLED and entry.avg_price == D(100)
    stop = await venue.place(
        order(
            "atiTfsl",
            OrderType.STOP_MARKET,
            Side.SELL,
            qty=None,
            trigger_price=D(95),
            close_position=True,
            purpose="stop_loss",
        )
    )
    assert stop.status is OrderStatus.NEW and stop.trigger_price == D(95)
    _, path, params = exchange.requests[-1]
    assert path == "/fapi/v1/algoOrder"
    assert params["algoType"] == "CONDITIONAL" and params["closePosition"] == "true"
    assert "quantity" not in params and "reduceOnly" not in params
    assert params["triggerPrice"] == "95" and params["clientAlgoId"] == "atiTfsl"
    open_orders = await venue.open_orders("BTCUSDT")
    assert [o.client_id for o in open_orders] == ["atiTfsl"]
    positions = await venue.positions()
    assert [(p.symbol, p.quantity) for p in positions] == [("BTCUSDT", D(2))]
    cancelled = await venue.cancel("BTCUSDT", "atiTfsl", conditional=True)
    assert cancelled.status is OrderStatus.CANCELED
    assert await venue.open_orders() == []
    await venue.rest.close()


async def test_old_order_endpoint_rejects_conditional_types(exchange: FakeExchange) -> None:
    """Belge doğrulaması: koşullu tür eski uç noktaya giderse -4120 alınır."""
    rest = rest_client(exchange)
    with pytest.raises(BinanceApiError) as caught:
        await rest.request(
            "POST",
            "/fapi/v1/order",
            params={"symbol": "BTCUSDT", "side": "SELL", "type": "STOP_MARKET", "quantity": 1},
            weight=1,
            signed=True,
        )
    error = map_error(caught.value)
    assert isinstance(error, OrderRejected) and error.code == -4120
    await rest.close()


async def test_futures_listen_key_stream_reports_trigger(exchange: FakeExchange) -> None:
    venue = futures_venue(exchange)
    iterator = venue.events()
    await wait_for(lambda: venue.stream_connected)
    await venue.place(order("atiTfe2", qty="1"))
    await venue.place(
        order(
            "atiTfs2",
            OrderType.STOP_MARKET,
            Side.SELL,
            qty=None,
            trigger_price=D(95),
            close_position=True,
            purpose="stop_loss",
        )
    )
    await exchange.set_price("BTCUSDT", D(94))
    seen: list[VenueEvent] = []
    async with asyncio.timeout(5):
        while not any(e.fill and e.fill.side is Side.SELL for e in seen):
            seen.append(await anext(iterator))
    assert any(e.kind == "account" and "algo" in e.raw for e in seen)
    algo = await venue.query("BTCUSDT", "atiTfs2", conditional=True)
    assert algo is not None and algo.status is OrderStatus.FILLED
    assert algo.actual_order_id is not None
    sell = next(e for e in seen if e.fill and e.fill.side is Side.SELL)
    assert sell.fill is not None and sell.fill.exchange_order_id == algo.actual_order_id
    assert sell.fill.realized_pnl == D(-6)
    await venue.rest.close()
    await venue.close()


# --- Arıza enjeksiyonu: idempotent gönderim ----------------------------------------------------------


@pytest.mark.parametrize("failure", ["503_after", "1007_after"])
async def test_unknown_outcome_after_acceptance_is_not_resent(
    exchange: FakeExchange, db: Database, failure: str
) -> None:
    venue = futures_venue(exchange)
    gate = make_gate(db, venue.mode)
    manager = OrderManager(db, venue, verifier=gate, backoff_s=0.01)
    exchange.fail_next.append(failure)
    cid = make_client_id(TradingMode.TESTNET, "entry", f"karar-{failure}")
    request = order(cid, qty="1")
    record = await manager.submit(request, approval=approve(gate, request, venue))
    assert record.status is OrderStatus.FILLED
    places = [r for r in exchange.requests if r[:2] == ("POST", "/fapi/v1/order")]
    assert len(places) == 1  # ikinci kez gönderilmedi; istemci kimliğiyle sorgulandı
    assert exchange.futures_positions["BTCUSDT"][0] == D(1)
    await venue.rest.close()


async def test_failure_before_acceptance_is_retried_with_same_id(
    exchange: FakeExchange, db: Database
) -> None:
    venue = spot_venue(exchange)
    gate = make_gate(db, venue.mode)
    manager = OrderManager(db, venue, verifier=gate, backoff_s=0.01)
    exchange.fail_next.append("503_before")
    cid = make_client_id(TradingMode.TESTNET, "entry", "karar-once")
    request = order(cid)
    record = await manager.submit(request, approval=approve(gate, request, venue))
    assert record.status is OrderStatus.FILLED
    places = [r for r in exchange.requests if r[:2] == ("POST", "/api/v3/order")]
    assert [p[2]["newClientOrderId"] for p in places] == [cid, cid]
    assert exchange.spot_balances["BTC"] == D(1)
    await venue.rest.close()


def test_error_mapping() -> None:
    import httpx

    from ati_engine.execution.venue import DuplicateOrder

    assert map_error(httpx.ReadTimeout("zaman")).unknown
    assert map_error(BinanceApiError(503, -1001, "iç hata")).unknown
    assert map_error(BinanceApiError(408, -1007, "zaman aşımı")).unknown
    assert map_error(BinanceApiError(400, -1021, "zaman damgası")).retryable
    assert isinstance(map_error(BinanceApiError(400, -4116, "x")), DuplicateOrder)
    assert isinstance(
        map_error(BinanceApiError(400, -2010, "Duplicate order sent.")), DuplicateOrder
    )
    rejected = map_error(BinanceApiError(400, -2010, "Account has insufficient balance"))
    assert isinstance(rejected, OrderRejected) and not rejected.unknown
    assert not isinstance(map_error(BinanceApiError(400, -1022, "imza")), DuplicateOrder)
    assert isinstance(map_error(RuntimeError("?")), VenueError)


def test_binance_venue_refuses_paper_mode(exchange: FakeExchange) -> None:
    with pytest.raises(ValueError, match="sanal"):
        BinanceSpotVenue(
            rest_client(exchange),
            mode=TradingMode.PAPER,
            api_key="a",
            signer=HmacSigner("b"),
            ws_url="ws://x",
        )


# --- İşlem motoru uçtan uca (test ağı modu, sahte borsa) ----------------------------------------------


def intent(market: Market, **kw: Any) -> TradeIntent:
    values: dict[str, Any] = {
        "decision_id": "uc-uca-1",
        "market": market,
        "symbol": "BTCUSDT",
        "direction": 1,
        "quantity": D("2"),
        "reference_price": D(100),
        "stop_loss": D(95),
        "take_profits": (TakeProfit(D(110), D("0.5")), TakeProfit(D(120), D("0.5"))),
        "leverage": 2,
    }
    values.update(kw)
    return TradeIntent(**values)


async def settle(engine: TradingEngine, condition: Callable[[], bool]) -> None:
    async with asyncio.timeout(5):
        while True:
            await engine.settle()
            if condition():
                return
            await asyncio.sleep(0.02)


async def test_engine_futures_end_to_end_tp1_breakeven_then_stop(
    exchange: FakeExchange, db: Database
) -> None:
    venue = futures_venue(exchange)
    holder: list[TradingEngine] = []
    engine = TradingEngine(
        venue=venue,
        db=db,
        risk_gate=make_gate(db, venue.mode, holder),
        symbols=lambda s: info(s, Market.USDM_FUTURES),
        engine_state=lambda: EngineState.RUNNING,
        fill_timeout_s=3.0,
    )
    holder.append(engine)
    await engine.start()
    await wait_for(lambda: venue.stream_connected)
    managed = await engine.open(intent(Market.USDM_FUTURES))
    assert managed.state == "open" and managed.filled_qty == D(2)
    assert exchange.futures_positions["BTCUSDT"][0] == D(2)
    algos = sorted(
        (a["type"], a["triggerPrice"])
        for a in exchange.algo_orders.values()
        if a["algoStatus"] == "NEW"
    )
    assert algos == [
        ("STOP_MARKET", "95"),
        ("TAKE_PROFIT_MARKET", "110"),
        ("TAKE_PROFIT_MARKET", "120"),
    ]
    assert not any(r[1] == "/fapi/v1/order" and r[2]["type"] != "MARKET" for r in exchange.requests)

    await exchange.set_price("BTCUSDT", D(111))  # ilk hedef
    await settle(
        engine,
        lambda: (
            engine.positions.positions.get("BTCUSDT") is not None
            and engine.positions.positions["BTCUSDT"].quantity == D(1)
            and any(
                a["type"] == "STOP_MARKET"
                and a["algoStatus"] == "NEW"
                and a["triggerPrice"] == "100"
                for a in exchange.algo_orders.values()
            )
        ),
    )
    await exchange.set_price("BTCUSDT", D("99.9"))  # başa baş stop
    await settle(engine, lambda: "BTCUSDT" not in engine.positions.positions)
    assert "BTCUSDT" not in exchange.futures_positions
    assert not [a for a in exchange.algo_orders.values() if a["algoStatus"] == "NEW"]
    row = await db.fetchone(
        "SELECT realized_pnl, status, mode FROM positions WHERE symbol = 'BTCUSDT'"
    )
    assert row is not None and row[1] == "closed" and row[2] == "testnet"
    assert D(row[0]) == D(11) + D("-0.1")  # (111-100)x1 + (99.9-100)x1
    await engine.stop()
    await venue.rest.close()


async def test_engine_spot_end_to_end_oco(exchange: FakeExchange, db: Database) -> None:
    venue = spot_venue(exchange)
    holder: list[TradingEngine] = []
    engine = TradingEngine(
        venue=venue,
        db=db,
        risk_gate=make_gate(db, venue.mode, holder),
        symbols=lambda s: info(s, Market.SPOT),
        engine_state=lambda: EngineState.RUNNING,
        fill_timeout_s=3.0,
    )
    holder.append(engine)
    await engine.start()
    await wait_for(lambda: venue.stream_connected)
    await engine.open(intent(Market.SPOT, leverage=1))
    assert exchange.spot_balances["BTC"] == D(2)
    lists = {o["orderListId"] for o in exchange.spot_orders.values() if o["status"] == "NEW"}
    assert len(lists) == 2
    await exchange.set_price("BTCUSDT", D(110))
    await settle(
        engine,
        lambda: (
            engine.positions.positions.get("BTCUSDT") is not None
            and engine.positions.positions["BTCUSDT"].quantity == D(1)
            and any(
                o["type"] == "STOP_LOSS" and o["status"] == "NEW" and D(o["stopPrice"]) == D(100)
                for o in exchange.spot_orders.values()
            )
        ),
    )
    await exchange.set_price("BTCUSDT", D(99))
    await settle(engine, lambda: "BTCUSDT" not in engine.positions.positions)
    assert exchange.spot_balances["BTC"] == D(0)
    assert not [o for o in exchange.spot_orders.values() if o["status"] == "NEW"]
    await engine.stop()
    await venue.rest.close()
