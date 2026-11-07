"""Kaçırılan işlemlerin (aggTrade) tespiti ve REST ile geri doldurulması."""

from __future__ import annotations

import asyncio
import contextlib

import httpx
import pytest

from ati_engine.config import BinanceEndpoints
from ati_engine.core.models import Market
from ati_engine.exchange.endpoints import endpoints_for
from ati_engine.exchange.rate_limit import WeightBudget
from ati_engine.exchange.rest import BinanceRestClient
from ati_engine.market.events import AggTrade
from ati_engine.market.gapfill import TradeGapFiller


def trade(trade_id: int, symbol: str = "BTCUSDT") -> AggTrade:
    return AggTrade(
        market=Market.SPOT,
        event_time_ms=0,
        symbol=symbol,
        trade_id=trade_id,
        price=1.0,
        qty=1.0,
        trade_time_ms=0,
        buyer_is_maker=False,
    )


class Exchange:
    """İşlem kimlikleri ``1..latest`` arasında olan sahte aggTrades uç noktası."""

    def __init__(self, latest: int, *, fail: bool = False) -> None:
        self.latest = latest
        self.fail = fail
        self.calls: list[dict[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.calls.append(params)
        if self.fail:
            return httpx.Response(500, json={"code": -1000, "msg": "hata"})
        start, limit = int(params["fromId"]), int(params["limit"])
        rows = [
            {"a": i, "p": "2.5", "q": "0.1", "f": i, "l": i, "T": 1000 + i, "m": True}
            for i in range(start, min(start + limit, self.latest + 1))
        ]
        return httpx.Response(200, json=rows)


def filler(exchange: Exchange, published: list[AggTrade], **kwargs: int) -> TradeGapFiller:
    rest = BinanceRestClient(
        "https://example.test",
        budget=WeightBudget(6000),
        client=httpx.AsyncClient(transport=httpx.MockTransport(exchange)),
    )

    async def publish(event: AggTrade) -> None:
        published.append(event)

    return TradeGapFiller(
        market=Market.SPOT,
        endpoints=endpoints_for(Market.SPOT, BinanceEndpoints()),
        rest=rest,
        publish=publish,
        **kwargs,
    )


async def drain(gap_filler: TradeGapFiller) -> None:
    task = asyncio.create_task(gap_filler.run())
    for _ in range(200):
        await asyncio.sleep(0.005)
        if gap_filler.stats.pending == 0:
            break
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_contiguous_stream_needs_no_backfill() -> None:
    exchange, published = Exchange(10), []
    gaps = filler(exchange, published)
    assert all(gaps.accept(trade(i)) for i in range(1, 6))
    await drain(gaps)
    assert exchange.calls == []
    assert gaps.stats.detected == 0


async def test_duplicates_are_dropped() -> None:
    gaps = filler(Exchange(10), [])
    assert gaps.accept(trade(5))
    assert not gaps.accept(trade(5))
    assert not gaps.accept(trade(4))
    assert gaps.accept(trade(6))
    assert gaps.stats.duplicates == 2


async def test_gap_is_recovered_in_order() -> None:
    exchange, published = Exchange(100), []
    gaps = filler(exchange, published)
    gaps.accept(trade(10))
    gaps.accept(trade(14))  # 11, 12, 13 kaçırıldı
    await drain(gaps)
    assert [t.trade_id for t in published] == [11, 12, 13]
    assert all(t.recovered for t in published)
    assert published[0].price == 2.5
    assert published[0].buyer_is_maker is True
    assert exchange.calls == [{"symbol": "BTCUSDT", "fromId": "11", "limit": "3"}]
    assert gaps.stats.recovered_trades == 3
    assert gaps.stats.unrecovered_trades == 0
    assert gaps.stats.pending == 0


async def test_gaps_are_tracked_per_symbol() -> None:
    exchange, published = Exchange(100), []
    gaps = filler(exchange, published)
    gaps.accept(trade(1, "BTCUSDT"))
    gaps.accept(trade(50, "ETHUSDT"))  # başka sembolün ilk işlemi: boşluk değil
    gaps.accept(trade(2, "BTCUSDT"))
    await drain(gaps)
    assert published == []


async def test_large_gap_is_paged() -> None:
    exchange, published = Exchange(5000), []
    gaps = filler(exchange, published, page_size=1000)
    gaps.accept(trade(1))
    gaps.accept(trade(2502))
    await drain(gaps)
    assert len(published) == 2500
    assert [c["limit"] for c in exchange.calls] == ["1000", "1000", "500"]


async def test_gap_beyond_cap_recovers_newest_part() -> None:
    exchange, published = Exchange(20_000), []
    gaps = filler(exchange, published, max_trades_per_gap=100)
    gaps.accept(trade(1))
    gaps.accept(trade(1002))  # 1000 işlem kaçırıldı, sınır 100
    await drain(gaps)
    assert [t.trade_id for t in published] == list(range(902, 1002))
    assert gaps.stats.unrecovered_gaps == 1
    assert gaps.stats.unrecovered_trades == 900


async def test_rest_failure_is_counted_and_worker_survives() -> None:
    exchange, published = Exchange(100, fail=True), []
    gaps = filler(exchange, published)
    gaps.accept(trade(1))
    gaps.accept(trade(5))
    await drain(gaps)
    assert published == []
    assert gaps.stats.unrecovered_trades == 3
    assert gaps.stats.pending == 0


async def test_missing_rows_are_reported() -> None:
    exchange, published = Exchange(12), []  # 13 ve 14 borsada da yok
    gaps = filler(exchange, published)
    gaps.accept(trade(10))
    gaps.accept(trade(15))
    await drain(gaps)
    assert [t.trade_id for t in published] == [11, 12]
    assert gaps.stats.unrecovered_trades == 2


@pytest.mark.parametrize(
    ("market", "path", "weight"),
    [
        (Market.SPOT, "/api/v3/aggTrades", 4),
        (Market.USDM_FUTURES, "/fapi/v1/aggTrades", 20),
    ],
)
def test_endpoints(market: Market, path: str, weight: int) -> None:
    endpoints = endpoints_for(market, BinanceEndpoints())
    assert endpoints.agg_trades_path == path
    assert endpoints.agg_trades_weight == weight
