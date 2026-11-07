"""Binance birleşik akış (combined stream) mesajlarının çözümlenmesi.

Gelen her mesaj ``{"stream": "<ad>", "data": {...}}`` biçimindedir. Akış adı türü belirler;
``data`` önce ``msgspec.Raw`` olarak tutulur ve yalnızca türüne uygun yapıya bir kez çözülür
(çift ayrıştırma yok). Abonelik yanıtları (``{"result": null, "id": 1}``) ve hatalar ayrıca
döndürülür.

Bilinmeyen alanlar yok sayılır: Binance zaman zaman yeni alanlar ekler (ör. Futures'ta ``st``,
``nq``); bu durum motoru bozmaz.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Any

import msgspec

from ati_engine.core.models import Market
from ati_engine.market.events import (
    AggTrade,
    BookTicker,
    DepthDiff,
    Kline,
    Liquidation,
    MarketDataEvent,
    MarkPrice,
    MarkPriceBatch,
    Ticker24h,
    TickerBatch,
)


class StreamKind(StrEnum):
    AGG_TRADE = "agg_trade"
    KLINE = "kline"
    MINI_TICKER_ARR = "mini_ticker_arr"
    TICKER_ARR = "ticker_arr"
    MARK_PRICE_ARR = "mark_price_arr"
    FORCE_ORDER = "force_order"
    BOOK_TICKER = "book_ticker"
    DEPTH_DIFF = "depth_diff"
    PARTIAL_DEPTH = "partial_depth"
    SERVER_SHUTDOWN = "server_shutdown"
    UNKNOWN = "unknown"


@lru_cache(maxsize=16_384)
def classify_stream(name: str) -> StreamKind:
    if name == "!serverShutdown":
        return StreamKind.SERVER_SHUTDOWN
    if name.startswith("!"):
        if name.startswith("!miniTicker@arr"):
            return StreamKind.MINI_TICKER_ARR
        if name.startswith("!ticker@arr"):
            return StreamKind.TICKER_ARR
        if name.startswith("!markPrice@arr"):
            return StreamKind.MARK_PRICE_ARR
        if name.startswith("!forceOrder@arr"):
            return StreamKind.FORCE_ORDER
        if name == "!bookTicker":
            return StreamKind.BOOK_TICKER
        return StreamKind.UNKNOWN
    _, _, rest = name.partition("@")
    if rest == "aggTrade":
        return StreamKind.AGG_TRADE
    if rest.startswith("kline_"):
        return StreamKind.KLINE
    if rest in ("depth", "depth@100ms", "depth@250ms", "depth@500ms"):
        return StreamKind.DEPTH_DIFF
    if rest.startswith("depth"):
        return StreamKind.PARTIAL_DEPTH
    if rest == "bookTicker":
        return StreamKind.BOOK_TICKER
    if rest == "forceOrder":
        return StreamKind.FORCE_ORDER
    return StreamKind.UNKNOWN


# --- Ham Binance yapıları ---------------------------------------------------------------


class _Envelope(msgspec.Struct):
    stream: str | None = None
    data: msgspec.Raw = msgspec.field(default_factory=msgspec.Raw)
    result: Any = None
    id: int | str | None = None
    error: dict[str, Any] | None = None


class _AggTrade(msgspec.Struct):
    E: int
    s: str
    a: int
    p: str
    q: str
    T: int
    m: bool


class _KlineBody(msgspec.Struct):
    t: int
    T: int
    i: str
    o: str
    c: str
    h: str
    l: str  # noqa: E741 - Binance alan adı
    v: str
    n: int
    x: bool
    q: str
    V: str
    Q: str


class _Kline(msgspec.Struct):
    E: int
    s: str
    k: _KlineBody


class _MiniTicker(msgspec.Struct):
    E: int
    s: str
    c: str
    o: str
    h: str
    l: str  # noqa: E741
    v: str
    q: str


class _MarkPrice(msgspec.Struct):
    E: int
    s: str
    p: str
    i: str
    r: str
    T: int


class _ForceOrderBody(msgspec.Struct):
    s: str
    S: str
    p: str
    ap: str
    q: str
    z: str
    X: str
    T: int


class _ForceOrder(msgspec.Struct):
    E: int
    o: _ForceOrderBody


class _BookTicker(msgspec.Struct):
    s: str
    b: str
    B: str
    a: str
    A: str
    u: int
    E: int = 0


class _DepthDiff(msgspec.Struct):
    E: int
    s: str
    U: int
    u: int
    b: list[tuple[str, str]]
    a: list[tuple[str, str]]
    pu: int | None = None


class _ServerShutdown(msgspec.Struct):
    E: int = 0


_envelope_decoder = msgspec.json.Decoder(_Envelope)
_decoders: dict[StreamKind, msgspec.json.Decoder[Any]] = {
    StreamKind.AGG_TRADE: msgspec.json.Decoder(_AggTrade),
    StreamKind.KLINE: msgspec.json.Decoder(_Kline),
    StreamKind.MINI_TICKER_ARR: msgspec.json.Decoder(list[_MiniTicker]),
    StreamKind.TICKER_ARR: msgspec.json.Decoder(list[_MiniTicker]),
    StreamKind.MARK_PRICE_ARR: msgspec.json.Decoder(list[_MarkPrice]),
    StreamKind.FORCE_ORDER: msgspec.json.Decoder(_ForceOrder),
    StreamKind.BOOK_TICKER: msgspec.json.Decoder(_BookTicker),
    StreamKind.DEPTH_DIFF: msgspec.json.Decoder(_DepthDiff),
}


@dataclass(frozen=True)
class ControlMessage:
    """Abonelik yanıtı veya hata."""

    id: int | str | None
    result: Any
    error: dict[str, Any] | None


@dataclass(frozen=True)
class ParsedMessage:
    stream: str
    kind: StreamKind
    events: tuple[MarketDataEvent, ...]


def _levels(raw: list[tuple[str, str]]) -> list[tuple[float, float]]:
    return [(float(p), float(q)) for p, q in raw]


def _convert(market: Market, kind: StreamKind, obj: Any) -> tuple[MarketDataEvent, ...]:
    if kind is StreamKind.AGG_TRADE:
        return (
            AggTrade(
                market=market,
                event_time_ms=obj.E,
                symbol=obj.s,
                trade_id=obj.a,
                price=float(obj.p),
                qty=float(obj.q),
                trade_time_ms=obj.T,
                buyer_is_maker=obj.m,
            ),
        )
    if kind is StreamKind.KLINE:
        k = obj.k
        return (
            Kline(
                market=market,
                event_time_ms=obj.E,
                symbol=obj.s,
                interval=k.i,
                open_time_ms=k.t,
                close_time_ms=k.T,
                open=float(k.o),
                high=float(k.h),
                low=float(k.l),
                close=float(k.c),
                volume=float(k.v),
                quote_volume=float(k.q),
                trades=k.n,
                taker_buy_volume=float(k.V),
                taker_buy_quote_volume=float(k.Q),
                closed=k.x,
            ),
        )
    if kind in (StreamKind.MINI_TICKER_ARR, StreamKind.TICKER_ARR):
        if not obj:
            return ()
        tickers = [
            Ticker24h(
                symbol=t.s,
                last=float(t.c),
                open=float(t.o),
                high=float(t.h),
                low=float(t.l),
                base_volume=float(t.v),
                quote_volume=float(t.q),
                event_time_ms=t.E,
            )
            for t in obj
        ]
        return (
            TickerBatch(
                market=market, event_time_ms=max(t.event_time_ms for t in tickers), tickers=tickers
            ),
        )
    if kind is StreamKind.MARK_PRICE_ARR:
        if not obj:
            return ()
        items = [
            MarkPrice(
                symbol=m.s,
                mark_price=float(m.p),
                index_price=float(m.i),
                funding_rate=float(m.r),
                next_funding_time_ms=m.T,
            )
            for m in obj
        ]
        return (MarkPriceBatch(market=market, event_time_ms=obj[0].E, items=items),)
    if kind is StreamKind.FORCE_ORDER:
        o = obj.o
        return (
            Liquidation(
                market=market,
                event_time_ms=obj.E,
                symbol=o.s,
                side=o.S,
                price=float(o.p),
                avg_price=float(o.ap),
                qty=float(o.q),
                filled_qty=float(o.z),
                status=o.X,
                trade_time_ms=o.T,
            ),
        )
    if kind is StreamKind.BOOK_TICKER:
        return (
            BookTicker(
                market=market,
                event_time_ms=obj.E,
                symbol=obj.s,
                bid=float(obj.b),
                bid_qty=float(obj.B),
                ask=float(obj.a),
                ask_qty=float(obj.A),
                update_id=obj.u,
            ),
        )
    if kind is StreamKind.DEPTH_DIFF:
        return (
            DepthDiff(
                market=market,
                event_time_ms=obj.E,
                symbol=obj.s,
                first_update_id=obj.U,
                final_update_id=obj.u,
                prev_final_update_id=obj.pu,
                bids=_levels(obj.b),
                asks=_levels(obj.a),
            ),
        )
    return ()


def parse_message(market: Market, raw: str | bytes) -> ParsedMessage | ControlMessage | None:
    """Tek bir WebSocket mesajını çözer. Tanınmayan akışlar için ``None`` döner."""
    envelope = _envelope_decoder.decode(raw)
    if envelope.stream is None:
        return ControlMessage(id=envelope.id, result=envelope.result, error=envelope.error)
    kind = classify_stream(envelope.stream)
    if kind is StreamKind.SERVER_SHUTDOWN:
        return ParsedMessage(envelope.stream, kind, ())
    decoder = _decoders.get(kind)
    if decoder is None or not envelope.data:
        return None
    return ParsedMessage(
        envelope.stream, kind, _convert(market, kind, decoder.decode(envelope.data))
    )
