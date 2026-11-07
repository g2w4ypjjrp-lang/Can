"""Sembol keşfi: exchangeInfo çözümleme, evren filtresi, yeni listeleme ve kapanma tespiti."""

from __future__ import annotations

import asyncio
import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ati_engine.core.bus import EventBus
from ati_engine.core.events import Event
from ati_engine.core.models import Market
from ati_engine.market.discovery import SymbolRegistry, UniverseFilter, parse_exchange_info
from ati_engine.market.events import SymbolDelisted, SymbolListed
from ati_engine.storage.database import Database

FIXTURES = Path(__file__).parent / "fixtures" / "binance"
SPOT = json.loads((FIXTURES / "spot_exchange_info.json").read_text())
FUTURES = json.loads((FIXTURES / "futures_exchange_info.json").read_text())


def _by_symbol(market: Market, payload: dict[str, Any]) -> dict[str, Any]:
    return {s.symbol: s for s in parse_exchange_info(market, payload)}


def test_spot_filters_are_parsed() -> None:
    symbols = _by_symbol(Market.SPOT, SPOT)
    btc = symbols["BTCUSDT"]
    assert btc.tick_size == Decimal("0.01")
    assert btc.step_size == Decimal("0.00001")
    assert btc.min_qty == Decimal("0.00001")
    assert btc.min_notional == Decimal("5")
    assert btc.contract_type is None
    assert symbols["ETHBTC"].quote_asset == "BTC"


def test_futures_filters_are_parsed() -> None:
    symbols = _by_symbol(Market.USDM_FUTURES, FUTURES)
    btc = symbols["BTCUSDT"]
    assert btc.tick_size == Decimal("0.10")
    assert btc.step_size == Decimal("0.001")
    assert btc.min_notional == Decimal("50")
    assert btc.contract_type == "PERPETUAL"
    assert btc.onboard_date_ms == 1567965300000


def test_universe_filter() -> None:
    universe = UniverseFilter()
    spot = _by_symbol(Market.SPOT, SPOT)
    fut = _by_symbol(Market.USDM_FUTURES, FUTURES)
    assert universe.accepts(spot["BTCUSDT"])
    assert not universe.accepts(spot["ETHBTC"])  # USDT değil
    assert universe.accepts(fut["BTCUSDT"])
    assert not universe.accepts(fut["BTCUSDC"])  # USDC
    assert not universe.accepts(fut["XAUUSDT"])  # altın: TRADIFI_PERPETUAL, coin değil
    only = UniverseFilter(allowlist=frozenset({"ETHUSDT"}))
    assert not only.accepts(spot["BTCUSDT"])
    assert only.accepts(spot["ETHUSDT"])


class _Collector:
    def __init__(self, bus: EventBus) -> None:
        self.events: list[Event] = []
        bus.subscribe(Event, self.events.append, name="collector")

    async def settle(self) -> None:
        for _ in range(20):
            await asyncio.sleep(0)


@pytest.fixture
def registry(db: Database, bus: EventBus) -> SymbolRegistry:
    return SymbolRegistry(db, bus)


async def test_initial_discovery_tracks_trading_usdt_only(
    registry: SymbolRegistry, db: Database, bus: EventBus
) -> None:
    collector = _Collector(bus)
    diff = await registry.apply(Market.SPOT, parse_exchange_info(Market.SPOT, SPOT))
    await collector.settle()
    assert diff.initial
    assert collector.events == []  # ilk keşifte "yeni listeleme" alarmı yok
    tracked = {s.symbol for s in registry.tracked(Market.SPOT)}
    assert "BTCUSDT" in tracked
    assert "ETHBTC" not in tracked
    statuses = {s["symbol"]: s["status"] for s in SPOT["symbols"]}
    assert all(statuses[s] == "TRADING" for s in tracked)
    rows = await db.fetchall("SELECT COUNT(*) FROM exchange_symbols WHERE market = 'spot'")
    assert rows[0][0] == len(SPOT["symbols"])  # tüm semboller kayıtlı (izlenmeyenler dahil)


async def test_new_listing_and_delisting_are_detected(
    registry: SymbolRegistry, db: Database, bus: EventBus
) -> None:
    await registry.apply(Market.SPOT, parse_exchange_info(Market.SPOT, SPOT))
    collector = _Collector(bus)

    changed = copy.deepcopy(SPOT)
    template = next(s for s in changed["symbols"] if s["symbol"] == "BTCUSDT")
    new_coin = {**copy.deepcopy(template), "symbol": "YENICOINUSDT", "baseAsset": "YENICOIN"}
    changed["symbols"].append(new_coin)
    changed["symbols"] = [s for s in changed["symbols"] if s["symbol"] != "ETHUSDT"]
    for s in changed["symbols"]:
        if s["symbol"] == "SOLUSDT":
            s["status"] = "BREAK"

    diff = await registry.apply(Market.SPOT, parse_exchange_info(Market.SPOT, changed))
    await collector.settle()
    assert [s.symbol for s in diff.listed] == ["YENICOINUSDT"]
    assert sorted(s.symbol for s in diff.delisted) == ["ETHUSDT", "SOLUSDT"]
    listed = [e for e in collector.events if isinstance(e, SymbolListed)]
    delisted = [e for e in collector.events if isinstance(e, SymbolDelisted)]
    assert [e.symbol for e in listed] == ["YENICOINUSDT"]
    assert {(e.symbol, e.status) for e in delisted} == {
        ("ETHUSDT", "REMOVED"),
        ("SOLUSDT", "BREAK"),
    }

    tracked = {s.symbol for s in registry.tracked(Market.SPOT)}
    assert "YENICOINUSDT" in tracked
    assert "ETHUSDT" not in tracked
    assert "SOLUSDT" not in tracked
    row = await db.fetchone(
        "SELECT delisted_at FROM exchange_symbols WHERE market='spot' AND symbol='ETHUSDT'"
    )
    assert row is not None
    assert row[0] is not None

    # SOLUSDT tekrar işleme açılınca yeniden listelenmiş sayılır.
    reopened = copy.deepcopy(changed)
    for s in reopened["symbols"]:
        if s["symbol"] == "SOLUSDT":
            s["status"] = "TRADING"
    diff = await registry.apply(Market.SPOT, parse_exchange_info(Market.SPOT, reopened))
    assert [s.symbol for s in diff.listed] == ["SOLUSDT"]


async def test_registry_survives_restart(db: Database, bus: EventBus) -> None:
    first = SymbolRegistry(db, bus)
    await first.apply(Market.USDM_FUTURES, parse_exchange_info(Market.USDM_FUTURES, FUTURES))
    second = SymbolRegistry(db, bus)  # yeniden başlatma: bellek boş, veritabanı dolu
    collector = _Collector(bus)
    diff = await second.apply(
        Market.USDM_FUTURES, parse_exchange_info(Market.USDM_FUTURES, FUTURES)
    )
    await collector.settle()
    assert not diff.initial
    assert not diff.changed
    assert collector.events == []
    assert {s.symbol for s in second.tracked(Market.USDM_FUTURES)} >= {"BTCUSDT", "ETHUSDT"}


async def test_max_symbols_limits_universe(db: Database, bus: EventBus) -> None:
    registry = SymbolRegistry(db, bus, universe=UniverseFilter(max_symbols=2))
    await registry.apply(Market.SPOT, parse_exchange_info(Market.SPOT, SPOT))
    assert len(registry.tracked(Market.SPOT)) == 2
