"""Gerçek Binance mesajlarıyla (fikstür) çözümleme testleri."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ati_engine.core.models import Market
from ati_engine.market.events import (
    AggTrade,
    BookTicker,
    DepthDiff,
    Kline,
    Liquidation,
    MarkPriceBatch,
    TickerBatch,
)
from ati_engine.market.parsing import (
    ControlMessage,
    ParsedMessage,
    StreamKind,
    classify_stream,
    parse_message,
)

FIXTURES = Path(__file__).parent / "fixtures" / "binance"
SPOT = json.loads((FIXTURES / "spot_ws_messages.json").read_text())
FUTURES = json.loads((FIXTURES / "futures_ws_messages.json").read_text())


def _parse(market: Market, message: dict[str, Any]) -> ParsedMessage:
    result = parse_message(market, json.dumps(message))
    assert isinstance(result, ParsedMessage)
    return result


@pytest.mark.parametrize(
    ("stream", "kind"),
    [
        ("btcusdt@aggTrade", StreamKind.AGG_TRADE),
        ("btcusdt@kline_1m", StreamKind.KLINE),
        ("btcusdt@kline_4h", StreamKind.KLINE),
        ("btcusdt@depth@100ms", StreamKind.DEPTH_DIFF),
        ("btcusdt@depth", StreamKind.DEPTH_DIFF),
        ("btcusdt@depth20@100ms", StreamKind.PARTIAL_DEPTH),
        ("btcusdt@bookTicker", StreamKind.BOOK_TICKER),
        ("!bookTicker", StreamKind.BOOK_TICKER),
        ("!miniTicker@arr", StreamKind.MINI_TICKER_ARR),
        ("!ticker@arr", StreamKind.TICKER_ARR),
        ("!markPrice@arr@1s", StreamKind.MARK_PRICE_ARR),
        ("!forceOrder@arr", StreamKind.FORCE_ORDER),
        ("btcusdt@forceOrder", StreamKind.FORCE_ORDER),
        ("!serverShutdown", StreamKind.SERVER_SHUTDOWN),
        ("btcusdt@rpiDepth@500ms", StreamKind.UNKNOWN),
    ],
)
def test_classify_stream(stream: str, kind: StreamKind) -> None:
    assert classify_stream(stream) is kind


def test_spot_agg_trade() -> None:
    raw = SPOT["btcusdt@aggTrade"][0]
    (event,) = _parse(Market.SPOT, raw).events
    assert isinstance(event, AggTrade)
    data = raw["data"]
    assert event.market is Market.SPOT
    assert event.symbol == "BTCUSDT"
    assert event.trade_id == data["a"]
    assert event.price == float(data["p"])
    assert event.qty == float(data["q"])
    assert event.trade_time_ms == data["T"]
    assert event.taker_side == ("SELL" if data["m"] else "BUY")
    assert event.quote_qty == pytest.approx(float(data["p"]) * float(data["q"]))


def test_futures_agg_trade_ignores_new_fields() -> None:
    raw = FUTURES["btcusdt@aggTrade"][0]
    assert "nq" in raw["data"]  # Binance'in 2026'da eklediği alan
    (event,) = _parse(Market.USDM_FUTURES, raw).events
    assert isinstance(event, AggTrade)
    assert event.market is Market.USDM_FUTURES


@pytest.mark.parametrize(
    ("market", "source"), [(Market.SPOT, SPOT), (Market.USDM_FUTURES, FUTURES)]
)
def test_kline(market: Market, source: dict[str, Any]) -> None:
    raw = source["btcusdt@kline_1m"][0]
    (event,) = _parse(market, raw).events
    assert isinstance(event, Kline)
    k = raw["data"]["k"]
    assert event.interval == "1m"
    assert event.open_time_ms == k["t"]
    assert event.close_time_ms == k["T"]
    assert (event.open, event.high, event.low, event.close) == tuple(
        float(k[x]) for x in ("o", "h", "l", "c")
    )
    assert event.trades == k["n"]
    assert event.closed is k["x"]
    assert event.taker_buy_quote_volume == float(k["Q"])


def test_spot_mini_ticker_array() -> None:
    raw = SPOT["!miniTicker@arr"][0]
    (event,) = _parse(Market.SPOT, raw).events
    assert isinstance(event, TickerBatch)
    assert len(event.tickers) == len(raw["data"])
    first = event.tickers[0]
    assert first.symbol == raw["data"][0]["s"]
    assert first.quote_volume == float(raw["data"][0]["q"])
    assert first.change_pct == pytest.approx(
        (float(raw["data"][0]["c"]) / float(raw["data"][0]["o"]) - 1) * 100
    )


def test_futures_ticker_array() -> None:
    (event,) = _parse(Market.USDM_FUTURES, FUTURES["!ticker@arr"][0]).events
    assert isinstance(event, TickerBatch)
    assert event.tickers


def test_futures_mark_price_and_funding() -> None:
    raw = FUTURES["!markPrice@arr@1s"][0]
    (event,) = _parse(Market.USDM_FUTURES, raw).events
    assert isinstance(event, MarkPriceBatch)
    item = event.items[0]
    assert item.symbol == raw["data"][0]["s"]
    assert item.funding_rate == float(raw["data"][0]["r"])
    assert item.next_funding_time_ms == raw["data"][0]["T"]


def test_futures_liquidation() -> None:
    raw = FUTURES["!forceOrder@arr"][0]
    (event,) = _parse(Market.USDM_FUTURES, raw).events
    assert isinstance(event, Liquidation)
    o = raw["data"]["o"]
    assert event.symbol == o["s"]
    assert event.side == o["S"]
    assert event.notional == pytest.approx(float(o["ap"]) * float(o["z"]))


def test_futures_book_ticker() -> None:
    (event,) = _parse(Market.USDM_FUTURES, FUTURES["btcusdt@bookTicker"][0]).events
    assert isinstance(event, BookTicker)
    assert event.bid < event.ask


def test_depth_diffs_carry_sequence_ids() -> None:
    (spot,) = _parse(Market.SPOT, SPOT["btcusdt@depth@100ms"][0]).events
    (fut,) = _parse(Market.USDM_FUTURES, FUTURES["btcusdt@depth@100ms"][0]).events
    assert isinstance(spot, DepthDiff)
    assert isinstance(fut, DepthDiff)
    assert spot.prev_final_update_id is None  # Spot'ta pu yok
    assert fut.prev_final_update_id is not None  # Futures'ta pu zorunlu
    assert spot.first_update_id <= spot.final_update_id
    assert all(isinstance(p, float) and isinstance(q, float) for p, q in spot.bids)


def test_control_and_shutdown_messages() -> None:
    ack = parse_message(Market.SPOT, b'{"result":null,"id":7}')
    assert ack == ControlMessage(id=7, result=None, error=None)
    err = parse_message(Market.SPOT, b'{"error":{"code":2,"msg":"Invalid request"},"id":8}')
    assert isinstance(err, ControlMessage)
    assert err.error == {"code": 2, "msg": "Invalid request"}
    shutdown = parse_message(
        Market.SPOT, b'{"stream":"!serverShutdown","data":{"e":"serverShutdown","E":1}}'
    )
    assert isinstance(shutdown, ParsedMessage)
    assert shutdown.kind is StreamKind.SERVER_SHUTDOWN


def test_unknown_stream_is_ignored() -> None:
    assert parse_message(Market.SPOT, b'{"stream":"btcusdt@rpiDepth@500ms","data":{}}') is None
