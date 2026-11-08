"""Aşama 10: borsa ↔ yerel mutabakat (sahte borsaya karşı gerçek HTTP/WebSocket)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ati_engine.core.models import EngineState, Market, OrderStatus, OrderType, Side, TradingMode
from ati_engine.execution.engine import TradingEngine
from ati_engine.execution.orders import make_client_id
from ati_engine.execution.reconcile import Reconciler
from ati_engine.execution.venue import OrderRequest
from ati_engine.storage.database import Database
from fake_exchange import FakeExchange
from test_binance_venue import futures_venue, info, intent, spot_venue, wait_for

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


async def start_engine(
    exchange: FakeExchange, db: Database, market: Market = Market.USDM_FUTURES
) -> TradingEngine:
    venue = futures_venue(exchange) if market is Market.USDM_FUTURES else spot_venue(exchange)
    engine = TradingEngine(
        venue=venue,
        db=db,
        symbols=lambda s: info(s, market),
        engine_state=lambda: EngineState.RUNNING,
        fill_timeout_s=3.0,
    )
    await engine.start()
    await wait_for(lambda: venue.stream_connected)  # type: ignore[attr-defined]
    return engine


async def shutdown(engine: TradingEngine) -> None:
    await engine.stop()
    await engine.venue.rest.close()  # type: ignore[attr-defined]


def active_algos(exchange: FakeExchange) -> list[tuple[str, str]]:
    return sorted(
        (a["type"], a["triggerPrice"])
        for a in exchange.algo_orders.values()
        if a["algoStatus"] == "NEW"
    )


async def risk_rules(db: Database) -> list[tuple[str, str]]:
    rows = await db.fetchall("SELECT rule, severity FROM risk_events ORDER BY id")
    return [(r[0], r[1]) for r in rows]


async def test_clean_state_reconciles_without_issues(exchange: FakeExchange, db: Database) -> None:
    engine = await start_engine(exchange, db)
    await engine.open(intent(Market.USDM_FUTURES))
    report = await Reconciler(engine).run("test")
    assert report.ok and report.issues == [] and report.orders_checked == 3
    assert report.orders_updated == 0 and await risk_rules(db) == []
    await shutdown(engine)


async def test_restart_recovers_stop_filled_while_offline(
    exchange: FakeExchange, db: Database
) -> None:
    engine = await start_engine(exchange, db)
    await engine.open(intent(Market.USDM_FUTURES))
    await shutdown(engine)
    await exchange.set_price("BTCUSDT", D(94))  # motor kapalıyken stop tetiklendi
    assert "BTCUSDT" not in exchange.futures_positions

    restarted = await start_engine(exchange, db)
    assert restarted.positions.positions["BTCUSDT"].quantity == D(2)  # henüz eski bilgi
    managed = restarted.managed["BTCUSDT"]
    assert managed.state == "open" and len(managed.protection) == 3
    assert managed.intent.stop_loss == D(95) and len(managed.intent.take_profits) == 2

    report = await Reconciler(restarted).run("startup")
    await restarted.settle()
    assert report.ok, report.as_dict()
    assert report.fills_recovered == 1
    assert "BTCUSDT" not in restarted.positions.positions
    assert active_algos(exchange) == []  # kalan hedefler iptal edildi
    row = await db.fetchone("SELECT realized_pnl, status FROM positions WHERE symbol = 'BTCUSDT'")
    assert row is not None and row[1] == "closed" and D(row[0]) == D(-12)
    again = await Reconciler(restarted).run("tekrar")
    assert again.ok and again.issues == [] and again.fills_recovered == 0
    await shutdown(restarted)


async def test_missing_stop_is_rebuilt(exchange: FakeExchange, db: Database) -> None:
    engine = await start_engine(exchange, db)
    await engine.open(intent(Market.USDM_FUTURES))
    stop = next(a for a in exchange.algo_orders.values() if a["type"] == "STOP_MARKET")
    stop["algoStatus"] = "CANCELED"  # borsa tarafında kayboldu (olay gelmedi)
    report = await Reconciler(engine).run("test")
    assert report.reprotected == 1 and report.ok
    assert active_algos(exchange) == [
        ("STOP_MARKET", "95"),
        ("TAKE_PROFIT_MARKET", "110"),
        ("TAKE_PROFIT_MARKET", "120"),
    ]
    assert ("reconcile.unprotected_position", "warning") in await risk_rules(db)
    await shutdown(engine)


async def test_rebuilt_stop_after_tp1_uses_breakeven_and_fresh_ids(
    exchange: FakeExchange, db: Database
) -> None:
    engine = await start_engine(exchange, db)
    await engine.open(intent(Market.USDM_FUTURES))
    await exchange.set_price("BTCUSDT", D(111))

    async def tp1_done() -> None:
        while not (
            engine.positions.positions["BTCUSDT"].quantity == D(1)
            and ("STOP_MARKET", "100") in active_algos(exchange)
        ):
            await engine.settle()
            await asyncio.sleep(0.02)

    async with asyncio.timeout(5):
        await tp1_done()
    await shutdown(engine)
    restarted = await start_engine(exchange, db)
    assert restarted.managed["BTCUSDT"].tp_filled == 1
    for algo in exchange.algo_orders.values():
        algo["algoStatus"] = "CANCELED" if algo["algoStatus"] == "NEW" else algo["algoStatus"]
    before = set(exchange.algo_orders)
    report = await Reconciler(restarted).run("startup")
    assert report.reprotected == 1, report.as_dict()
    assert active_algos(exchange) == [("STOP_MARKET", "100"), ("TAKE_PROFIT_MARKET", "120")]
    new_ids = {k for k, a in exchange.algo_orders.items() if a["algoStatus"] == "NEW"}
    assert new_ids.isdisjoint(before)  # eski istemci kimlikleri yeniden kullanılmadı
    await shutdown(restarted)


async def test_position_mismatch_and_foreign_orders_are_reported_not_touched(
    exchange: FakeExchange, db: Database
) -> None:
    engine = await start_engine(exchange, db)
    await engine.open(intent(Market.USDM_FUTURES))
    exchange.futures_positions["BTCUSDT"] = (D(1), D(100))  # elle kısmen kapatılmış
    exchange.futures_positions["ETHUSDT"] = (D(-3), D(100))  # kullanıcının kendi pozisyonu
    exchange.futures_orders["web_1"] = {
        "symbol": "ETHUSDT",
        "orderId": 1,
        "clientOrderId": "web_1",
        "price": "90",
        "origQty": "1",
        "executedQty": "0",
        "avgPrice": "0",
        "status": "NEW",
        "type": "LIMIT",
        "side": "BUY",
        "reduceOnly": False,
        "updateTime": 1,
    }
    report = await Reconciler(engine).run("test")
    assert not report.ok
    rules = {(i.rule, i.symbol): i for i in report.issues}
    mismatch = rules[("position_mismatch", "BTCUSDT")]
    assert mismatch.severity == "critical" and mismatch.details == {"local": "2", "exchange": "1"}
    assert rules[("foreign_position", "ETHUSDT")].severity == "warning"
    assert rules[("foreign_order", "ETHUSDT")].severity == "info"
    assert exchange.futures_orders["web_1"]["status"] == "NEW"  # dokunulmadı
    assert ("reconcile.position_mismatch", "critical") in await risk_rules(db)
    await shutdown(engine)


async def test_spot_balance_shortfall_is_critical(exchange: FakeExchange, db: Database) -> None:
    engine = await start_engine(exchange, db, Market.SPOT)
    await engine.open(intent(Market.SPOT, leverage=1))
    exchange.spot_balances["BTC"] = D("0.5")  # başka bir yerden satılmış
    report = await Reconciler(engine).run("test")
    issue = next(i for i in report.issues if i.rule == "balance_shortfall")
    assert issue.severity == "critical" and issue.details["exchange"] == "0.5"
    assert not report.ok
    await shutdown(engine)


async def test_unresolved_submission_closed_after_grace(
    exchange: FakeExchange, db: Database
) -> None:
    engine = await start_engine(exchange, db, Market.SPOT)
    engine.orders.backoff_s = 0.01
    exchange.fail_next.extend(["503_before"] * 3)
    cid = make_client_id(TradingMode.TESTNET, "entry", "belirsiz")
    record = await engine.orders.submit(
        OrderRequest(
            client_id=cid,
            symbol="BTCUSDT",
            side=Side.BUY,
            type=OrderType.MARKET,
            quantity=D(1),
            purpose="entry",
        )
    )
    assert record.unresolved
    waiting = await Reconciler(engine, unknown_grace_s=3600).run("test")
    assert waiting.issues == [] and record.status is OrderStatus.PENDING_NEW
    report = await Reconciler(engine, unknown_grace_s=0).run("test")
    assert record.status is OrderStatus.REJECTED
    assert [i.rule for i in report.issues] == ["order_not_found"]
    row = await db.fetchone("SELECT status, last_error FROM orders WHERE id = ?", (cid,))
    assert row is not None and row[0] == "REJECTED" and "mutabakat" in row[1]
    await shutdown(engine)


async def test_stream_drop_triggers_reconciliation(exchange: FakeExchange, db: Database) -> None:
    engine = await start_engine(exchange, db)
    reconciler = Reconciler(engine)
    triggers: list[str] = []

    async def on_reset() -> Any:
        report = await reconciler.run("stream_reset")
        triggers.append(report.trigger)

    engine.on_stream_reset = on_reset
    await engine.open(intent(Market.USDM_FUTURES))
    await exchange.drop_streams()
    await exchange.set_price("BTCUSDT", D(94))  # akış kopukken stop tetiklendi
    await wait_for(lambda: triggers == ["stream_reset"], within=10)
    await engine.settle()
    assert "BTCUSDT" not in engine.positions.positions
    assert active_algos(exchange) == []
    assert reconciler.last is not None and reconciler.last.fills_recovered >= 1
    await shutdown(engine)
