"""Binance Spot ve USDⓈ-M Futures yürütücüleri (test ağı ve gerçek hesap aynı kod).

2026-11 itibarıyla Binance belgelerinden doğrulanan kurallar:

* **Futures koşullu emirler** (STOP_MARKET, TAKE_PROFIT_MARKET, TRAILING_STOP_MARKET)
  2025-12-09'dan beri Algo servisindedir: ``POST/DELETE/GET /fapi/v1/algoOrder``,
  ``GET /fapi/v1/openAlgoOrders`` (``algoType=CONDITIONAL``, ``triggerPrice``,
  ``clientAlgoId``, ``closePosition``, ``callbackRate``, ``activatePrice``). Eski emir uç noktası
  bu türleri reddeder (-4120).
* **Futures kullanıcı akışı:** ``POST/PUT /fapi/v1/listenKey`` (60 dk geçerli) ve
  ``wss://fstream.binance.com/private/ws/<listenKey>``. Olaylar: ``ORDER_TRADE_UPDATE``,
  ``ACCOUNT_UPDATE``, ``ALGO_UPDATE``, ``listenKeyExpired``.
* **Spot kullanıcı akışı:** REST listenKey 2026-02-20'de kaldırıldı; WebSocket API'de
  imzalı ``userDataStream.subscribe.signature`` kullanılır.
* **Spot imzası:** parametreler imzadan önce yüzde-kodlanır (2026-01-15'ten beri zorunlu).

``ALGO_UPDATE`` olayının alan adları belgelerden doğrulanamadığı için bu olay yalnızca
tetikleyici olarak kullanılır: koşullu emrin gerçek durumu belgelenmiş REST sorgusuyla alınır.
Spot OCO parametreleri ve bazı olay alanları ilk test ağı denemesinde ayrıca doğrulanacaktır;
tüm adresler ayarlardan değiştirilebilir.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Mapping
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

import httpx
import websockets

from ati_engine.core.models import Market, OrderStatus, OrderType, Side, TradingMode
from ati_engine.exchange.rate_limit import Priority, RateLimitError
from ati_engine.exchange.rest import BinanceApiError, BinanceRestClient
from ati_engine.exchange.signing import RequestSigner, build_query
from ati_engine.execution.venue import (
    Balance,
    DuplicateOrder,
    ExchangeOrder,
    Fill,
    OcoRequest,
    OrderRejected,
    OrderRequest,
    VenueError,
    VenueEvent,
    VenuePosition,
)
from ati_engine.safety.trading_mode import LIVE_LOCKED_MESSAGE, LiveTradingLocked

logger = logging.getLogger(__name__)

# Gerçek hesap adresleri: test ağı modunda bunlara bağlanmak reddedilir.
PRODUCTION_HOST_RE = re.compile(
    r"^(api\d*|fapi|dapi|papi|www|ws-api|ws-fapi|stream|fstream|dstream)\.binance\.com$"
)

NOT_FOUND_CODES = {-2013, -2011}  # emir yok / iptal edilecek emir yok
UNKNOWN_CODES = {-1007, -1006}  # borsa yanıt vermedi: durum bilinmiyor
RETRYABLE_CODES = {-1021, -1003, -1015, -1008}  # zaman / hız sınırı


def _dec(value: Any) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else Decimal(0)


def _status(value: str) -> OrderStatus:
    mapping = {
        "NEW": OrderStatus.NEW,
        "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
        "FILLED": OrderStatus.FILLED,
        "CANCELED": OrderStatus.CANCELED,
        "PENDING_CANCEL": OrderStatus.NEW,
        "REJECTED": OrderStatus.REJECTED,
        "EXPIRED": OrderStatus.EXPIRED,
        "EXPIRED_IN_MATCH": OrderStatus.EXPIRED,
        # Algo (koşullu) emir durumları
        "TRIGGERING": OrderStatus.NEW,
        "TRIGGERED": OrderStatus.NEW,  # gerçek emir oluştu; dolumu ayrıca gelir
        "FINISHED": OrderStatus.FILLED,
    }
    return mapping.get(value, OrderStatus.NEW)


def map_error(exc: Exception) -> VenueError:
    """Taşıma ve borsa hatalarını yürütme hatalarına çevirir."""
    if isinstance(exc, RateLimitError):
        return VenueError(str(exc), retryable=True)
    if isinstance(exc, httpx.TimeoutException | httpx.TransportError):
        return VenueError(f"bağlantı/zaman aşımı: {exc!r}", unknown=True)
    if isinstance(exc, BinanceApiError):
        message = str(exc)
        if exc.status >= 500:
            return VenueError(message, code=exc.code, unknown=True)
        if exc.code in UNKNOWN_CODES:
            return VenueError(message, code=exc.code, unknown=True)
        if exc.code in RETRYABLE_CODES:
            return VenueError(message, code=exc.code, retryable=True)
        if "Duplicate" in message or exc.code == -4116:
            return DuplicateOrder(message, code=exc.code)
        return OrderRejected(message, code=exc.code)
    return VenueError(repr(exc), unknown=True)


class _BaseBinanceVenue:
    market: Market
    mode: TradingMode
    quote: str

    def __init__(
        self,
        rest: BinanceRestClient,
        *,
        mode: TradingMode,
        api_key: str,
        signer: RequestSigner,
        ws_url: str,
        quote_asset: str = "USDT",
    ) -> None:
        if mode is TradingMode.PAPER:
            raise ValueError("Binance yürütücüsü sanal modda kullanılmaz")
        if mode is TradingMode.LIVE:
            raise LiveTradingLocked(LIVE_LOCKED_MESSAGE)
        for url in (rest.base_url, ws_url):
            host = urlsplit(url).hostname or ""
            if PRODUCTION_HOST_RE.match(host):
                raise ValueError(f"Test ağı modunda gerçek Binance adresine ({host}) bağlanılamaz")
        self.rest = rest
        self.mode = mode
        self._api_key = api_key
        self._signer = signer
        self._ws_url = ws_url.rstrip("/")
        self.quote = quote_asset
        self._queue: asyncio.Queue[VenueEvent] = asyncio.Queue()
        self._stream_task: asyncio.Task[None] | None = None
        self._stopping = False
        self.stream_connected = False
        self.stream_errors = 0

    async def _call(
        self, method: str, path: str, params: Mapping[str, Any], *, weight: int = 1
    ) -> Any:
        try:
            return await self.rest.request(
                method, path, params=params, weight=weight, priority=Priority.HIGH, signed=True
            )
        except Exception as exc:
            raise map_error(exc) from exc

    async def _query_or_none(
        self, path: str, params: Mapping[str, Any], *, weight: int = 1
    ) -> Any | None:
        try:
            return await self._call("GET", path, params, weight=weight)
        except OrderRejected as exc:
            if exc.code in NOT_FOUND_CODES:
                return None
            raise

    def events(self) -> AsyncIterator[VenueEvent]:
        if self._stream_task is None:
            self._stream_task = asyncio.create_task(self._stream_loop())
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[VenueEvent]:
        while True:
            yield await self._queue.get()

    async def _stream_loop(self) -> None:
        backoff = 1.0
        first = True
        while not self._stopping:
            try:
                await self._stream_once(reconnected=not first)
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.stream_errors += 1
                logger.warning(
                    "Kullanıcı veri akışı koptu",
                    extra={"market": self.market.value, "error": repr(exc)},
                )
            finally:
                self.stream_connected = False
            first = False
            if self._stopping:
                return
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    async def _stream_once(self, *, reconnected: bool) -> None:  # pragma: no cover - soyut
        raise NotImplementedError

    async def close(self) -> None:
        self._stopping = True
        if self._stream_task is not None:
            self._stream_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._stream_task


# --- Spot ---------------------------------------------------------------------------------------

_SPOT_TYPES = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.STOP_MARKET: "STOP_LOSS",
    OrderType.TAKE_PROFIT_MARKET: "TAKE_PROFIT",
}
_SPOT_TYPES_BACK = {
    "MARKET": OrderType.MARKET,
    "LIMIT": OrderType.LIMIT,
    "LIMIT_MAKER": OrderType.LIMIT,
    "STOP_LOSS": OrderType.STOP_MARKET,
    "STOP_LOSS_LIMIT": OrderType.STOP_LOSS_LIMIT,
    "TAKE_PROFIT": OrderType.TAKE_PROFIT_MARKET,
    "TAKE_PROFIT_LIMIT": OrderType.TAKE_PROFIT_LIMIT,
}


def spot_order(data: Mapping[str, Any], *, symbol: str | None = None) -> ExchangeOrder:
    qty = _dec(data.get("origQty"))
    executed = _dec(data.get("executedQty"))
    quote = _dec(data.get("cummulativeQuoteQty"))
    order = ExchangeOrder(
        client_id=str(data.get("clientOrderId", "")),
        exchange_id=str(data.get("orderId", "")),
        symbol=str(data.get("symbol", symbol or "")),
        side=Side(str(data.get("side", "BUY"))),
        type=_SPOT_TYPES_BACK.get(str(data.get("type", "MARKET")), OrderType.MARKET),
        status=_status(str(data.get("status", "NEW"))),
        quantity=qty,
        executed_qty=executed,
        avg_price=(quote / executed) if executed > 0 and quote > 0 else None,
        price=_dec(data.get("price")) or None,
        trigger_price=_dec(data.get("stopPrice")) or None,
        update_ms=int(data.get("updateTime") or data.get("transactTime") or 0),
        list_id=str(data["orderListId"]) if data.get("orderListId", -1) not in (-1, None) else None,
    )
    return order


def spot_fills(data: Mapping[str, Any], order: ExchangeOrder) -> list[Fill]:
    """``newOrderRespType=FULL`` yanıtındaki dolumlar."""
    fills = []
    for f in data.get("fills") or []:
        fills.append(
            Fill(
                client_id=order.client_id,
                exchange_order_id=order.exchange_id,
                trade_id=str(f["tradeId"]),
                symbol=order.symbol,
                side=order.side,
                price=_dec(f["price"]),
                qty=_dec(f["qty"]),
                commission=_dec(f.get("commission")),
                commission_asset=str(f.get("commissionAsset", "")),
                is_maker=False,
                ts=order.update_ms,
            )
        )
    return fills


def parse_execution_report(e: Mapping[str, Any]) -> VenueEvent:
    """Spot ``executionReport`` → emir anlık görüntüsü (+ işlem varsa dolum)."""
    execution = str(e.get("x", ""))
    client_id = str(e.get("c", ""))
    original = str(e.get("C") or "")
    if execution == "CANCELED" and original:
        client_id = original  # iptalde ``c`` iptal isteğinin kimliğidir
    executed = _dec(e.get("z"))
    quote = _dec(e.get("Z"))
    order = ExchangeOrder(
        client_id=client_id,
        exchange_id=str(e.get("i", "")),
        symbol=str(e.get("s", "")),
        side=Side(str(e.get("S", "BUY"))),
        type=_SPOT_TYPES_BACK.get(str(e.get("o", "MARKET")), OrderType.MARKET),
        status=_status(str(e.get("X", "NEW"))),
        quantity=_dec(e.get("q")),
        executed_qty=executed,
        avg_price=(quote / executed) if executed > 0 and quote > 0 else None,
        price=_dec(e.get("p")) or None,
        trigger_price=_dec(e.get("P")) or None,
        update_ms=int(e.get("T") or e.get("E") or 0),
        list_id=str(e["g"]) if e.get("g", -1) not in (-1, None) else None,
    )
    fill = None
    if execution == "TRADE":
        fill = Fill(
            client_id=client_id,
            exchange_order_id=order.exchange_id,
            trade_id=str(e.get("t")),
            symbol=order.symbol,
            side=order.side,
            price=_dec(e.get("L")),
            qty=_dec(e.get("l")),
            commission=_dec(e.get("n")),
            commission_asset=str(e.get("N") or ""),
            is_maker=bool(e.get("m")),
            ts=order.update_ms,
        )
    return VenueEvent(kind="order", order=order, fill=fill, raw=dict(e))


class BinanceSpotVenue(_BaseBinanceVenue):
    market = Market.SPOT

    async def place(self, request: OrderRequest) -> ExchangeOrder:
        params: dict[str, Any] = {
            "symbol": request.symbol,
            "side": request.side.value,
            "type": _SPOT_TYPES[request.type],
            "quantity": request.quantity,
            "newClientOrderId": request.client_id,
            "newOrderRespType": "FULL",
        }
        if request.type is OrderType.LIMIT:
            params["timeInForce"] = (request.time_in_force or "GTC").__str__()
            params["price"] = request.price
        if request.type in (OrderType.STOP_MARKET, OrderType.TAKE_PROFIT_MARKET):
            params["stopPrice"] = request.trigger_price
        data = await self._call("POST", "/api/v3/order", params)
        order = spot_order(data, symbol=request.symbol)
        for fill in spot_fills(data, order):
            await self._queue.put(VenueEvent(kind="order", fill=fill))
        return order

    async def place_oco(self, request: OcoRequest) -> list[ExchangeOrder]:
        if request.side is not Side.SELL:
            raise OrderRejected("Spot'ta yalnızca long pozisyon korunur (satış OCO)")
        params: dict[str, Any] = {
            "symbol": request.symbol,
            "side": request.side.value,
            "quantity": request.quantity,
            "listClientOrderId": request.list_client_id,
            "aboveType": "LIMIT_MAKER",
            "abovePrice": request.take_profit_price,
            "aboveClientOrderId": request.tp_client_id,
            "belowType": "STOP_LOSS",
            "belowStopPrice": request.stop_price,
            "belowClientOrderId": request.sl_client_id,
            "belowTrailingDelta": request.trailing_delta_bips,
            "newOrderRespType": "FULL",
        }
        data = await self._call("POST", "/api/v3/orderList/oco", params)
        list_id = str(data.get("orderListId", ""))
        orders = []
        for report in data.get("orderReports") or []:
            order = spot_order(report, symbol=request.symbol)
            order.list_id = list_id
            orders.append(order)
        return orders

    async def cancel(
        self, symbol: str, client_id: str, *, conditional: bool = False
    ) -> ExchangeOrder:
        data = await self._call(
            "DELETE", "/api/v3/order", {"symbol": symbol, "origClientOrderId": client_id}
        )
        order = spot_order(data, symbol=symbol)
        order.client_id = str(data.get("origClientOrderId") or client_id)
        return order

    async def query(
        self, symbol: str, client_id: str, *, conditional: bool = False
    ) -> ExchangeOrder | None:
        data = await self._query_or_none(
            "/api/v3/order", {"symbol": symbol, "origClientOrderId": client_id}, weight=4
        )
        return spot_order(data, symbol=symbol) if data else None

    async def open_orders(self, symbol: str | None = None) -> list[ExchangeOrder]:
        params = {"symbol": symbol} if symbol else {}
        data = await self._call("GET", "/api/v3/openOrders", params, weight=6 if symbol else 80)
        return [spot_order(o) for o in data]

    async def fills(self, symbol: str, exchange_order_id: str) -> list[Fill]:
        data = await self._call(
            "GET", "/api/v3/myTrades", {"symbol": symbol, "orderId": exchange_order_id}, weight=20
        )
        result = []
        for t in data:
            result.append(
                Fill(
                    client_id="",
                    exchange_order_id=str(t["orderId"]),
                    trade_id=str(t["id"]),
                    symbol=symbol,
                    side=Side.BUY if t.get("isBuyer") else Side.SELL,
                    price=_dec(t["price"]),
                    qty=_dec(t["qty"]),
                    commission=_dec(t.get("commission")),
                    commission_asset=str(t.get("commissionAsset", "")),
                    is_maker=bool(t.get("isMaker")),
                    ts=int(t.get("time", 0)),
                )
            )
        return result

    async def balances(self) -> list[Balance]:
        data = await self._call("GET", "/api/v3/account", {"omitZeroBalances": "true"}, weight=20)
        return [
            Balance(b["asset"], _dec(b["free"]), _dec(b["locked"]))
            for b in data.get("balances", [])
        ]

    async def positions(self) -> list[VenuePosition]:
        return []

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        return None

    async def _stream_once(self, *, reconnected: bool) -> None:
        async with websockets.connect(self._ws_url, open_timeout=10, ping_interval=20) as ws:
            params: dict[str, Any] = {
                "apiKey": self._api_key,
                "timestamp": int(time.time() * 1000) + self.rest.time_offset_ms,
            }
            # WebSocket API imzası: imza dışındaki parametreler ada göre sıralanır.
            payload = build_query(dict(sorted(params.items())))
            params["signature"] = self._signer.sign(payload)
            request_id = str(uuid.uuid4())
            await ws.send(
                json.dumps(
                    {
                        "id": request_id,
                        "method": "userDataStream.subscribe.signature",
                        "params": params,
                    }
                )
            )
            async for raw in ws:
                message = json.loads(raw)
                if message.get("id") == request_id:
                    if message.get("status") != 200:
                        raise VenueError(f"Kullanıcı akışı aboneliği reddedildi: {message}")
                    self.stream_connected = True
                    if reconnected:
                        await self._queue.put(VenueEvent(kind="stream_reconnected"))
                    continue
                event = message.get("event")
                if not isinstance(event, dict):
                    continue
                kind = event.get("e")
                if kind == "executionReport":
                    await self._queue.put(parse_execution_report(event))
                elif kind in ("outboundAccountPosition", "balanceUpdate"):
                    await self._queue.put(VenueEvent(kind="account", raw=event))
                elif kind == "eventStreamTerminated":
                    await self._queue.put(VenueEvent(kind="stream_expired", raw=event))
                    return


# --- USDⓈ-M Futures ------------------------------------------------------------------------------

_FUT_TYPES_BACK = {
    "MARKET": OrderType.MARKET,
    "LIMIT": OrderType.LIMIT,
    "STOP_MARKET": OrderType.STOP_MARKET,
    "TAKE_PROFIT_MARKET": OrderType.TAKE_PROFIT_MARKET,
    "TRAILING_STOP_MARKET": OrderType.TRAILING_STOP_MARKET,
}


def futures_order(data: Mapping[str, Any]) -> ExchangeOrder:
    return ExchangeOrder(
        client_id=str(data.get("clientOrderId", "")),
        exchange_id=str(data.get("orderId", "")),
        symbol=str(data.get("symbol", "")),
        side=Side(str(data.get("side", "BUY"))),
        type=_FUT_TYPES_BACK.get(str(data.get("type", "MARKET")), OrderType.MARKET),
        status=_status(str(data.get("status", "NEW"))),
        quantity=_dec(data.get("origQty")),
        executed_qty=_dec(data.get("executedQty")),
        avg_price=_dec(data.get("avgPrice")) or None,
        price=_dec(data.get("price")) or None,
        trigger_price=_dec(data.get("stopPrice")) or None,
        update_ms=int(data.get("updateTime") or 0),
    )


def algo_order(data: Mapping[str, Any]) -> ExchangeOrder:
    actual = data.get("actualOrderId")
    return ExchangeOrder(
        client_id=str(data.get("clientAlgoId", "")),
        exchange_id=str(data.get("algoId", "")),
        symbol=str(data.get("symbol", "")),
        side=Side(str(data.get("side", "BUY"))),
        type=_FUT_TYPES_BACK.get(
            str(data.get("orderType") or data.get("type")), OrderType.STOP_MARKET
        ),
        status=_status(str(data.get("algoStatus", "NEW"))),
        quantity=_dec(data.get("quantity")),
        trigger_price=_dec(data.get("triggerPrice")) or None,
        update_ms=int(data.get("updateTime") or 0),
        actual_order_id=str(actual) if actual not in (None, "", 0, "0") else None,
    )


def parse_order_trade_update(message: Mapping[str, Any]) -> VenueEvent:
    o = message.get("o") or {}
    order = ExchangeOrder(
        client_id=str(o.get("c", "")),
        exchange_id=str(o.get("i", "")),
        symbol=str(o.get("s", "")),
        side=Side(str(o.get("S", "BUY"))),
        type=_FUT_TYPES_BACK.get(str(o.get("o", "MARKET")), OrderType.MARKET),
        status=_status(str(o.get("X", "NEW"))),
        quantity=_dec(o.get("q")),
        executed_qty=_dec(o.get("z")),
        avg_price=_dec(o.get("ap")) or None,
        price=_dec(o.get("p")) or None,
        trigger_price=_dec(o.get("sp")) or None,
        update_ms=int(o.get("T") or message.get("T") or 0),
    )
    fill = None
    if str(o.get("x")) == "TRADE":
        fill = Fill(
            client_id=order.client_id,
            exchange_order_id=order.exchange_id,
            trade_id=str(o.get("t")),
            symbol=order.symbol,
            side=order.side,
            price=_dec(o.get("L")),
            qty=_dec(o.get("l")),
            commission=_dec(o.get("n")),
            commission_asset=str(o.get("N") or "USDT"),
            is_maker=bool(o.get("m")),
            ts=order.update_ms,
            realized_pnl=_dec(o.get("rp")),
        )
    return VenueEvent(kind="order", order=order, fill=fill, raw=dict(message))


class BinanceFuturesVenue(_BaseBinanceVenue):
    market = Market.USDM_FUTURES

    def __init__(self, *args: Any, keepalive_s: float = 30 * 60, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._keepalive_s = keepalive_s
        self._algo_symbols: set[str] = set()

    async def place(self, request: OrderRequest) -> ExchangeOrder:
        if request.is_conditional:
            params: dict[str, Any] = {
                "algoType": "CONDITIONAL",
                "symbol": request.symbol,
                "side": request.side.value,
                "type": request.type.value,
                "clientAlgoId": request.client_id,
                "workingType": request.working_type,
                "priceProtect": "TRUE",
            }
            if request.close_position:
                params["closePosition"] = "true"
            else:
                params["quantity"] = request.quantity
                params["reduceOnly"] = "true" if request.reduce_only else None
            if request.type is OrderType.TRAILING_STOP_MARKET:
                params["callbackRate"] = request.callback_rate
                params["activatePrice"] = request.activation_price
            else:
                params["triggerPrice"] = request.trigger_price
            data = await self._call("POST", "/fapi/v1/algoOrder", params)
            self._algo_symbols.add(request.symbol)
            return algo_order({**params, **data})
        params = {
            "symbol": request.symbol,
            "side": request.side.value,
            "type": request.type.value,
            "quantity": request.quantity,
            "newClientOrderId": request.client_id,
            "newOrderRespType": "RESULT",
            "reduceOnly": "true" if request.reduce_only else None,
        }
        if request.type is OrderType.LIMIT:
            params["timeInForce"] = str(request.time_in_force or "GTC")
            params["price"] = request.price
        data = await self._call("POST", "/fapi/v1/order", params)
        return futures_order(data)

    async def place_oco(self, request: OcoRequest) -> list[ExchangeOrder]:
        raise OrderRejected("Futures'ta OCO yok; koruma emirleri ayrı koşullu emirlerdir")

    async def cancel(
        self, symbol: str, client_id: str, *, conditional: bool = False
    ) -> ExchangeOrder:
        if conditional:
            await self._call("DELETE", "/fapi/v1/algoOrder", {"clientAlgoId": client_id})
            found = await self.query(symbol, client_id, conditional=True)
            if found is None:
                raise VenueError("İptal edilen koşullu emir bulunamadı")
            return found
        data = await self._call(
            "DELETE", "/fapi/v1/order", {"symbol": symbol, "origClientOrderId": client_id}
        )
        return futures_order(data)

    async def query(
        self, symbol: str, client_id: str, *, conditional: bool = False
    ) -> ExchangeOrder | None:
        if conditional:
            data = await self._query_or_none("/fapi/v1/algoOrder", {"clientAlgoId": client_id})
            return algo_order(data) if data else None
        data = await self._query_or_none(
            "/fapi/v1/order", {"symbol": symbol, "origClientOrderId": client_id}
        )
        return futures_order(data) if data else None

    async def open_orders(self, symbol: str | None = None) -> list[ExchangeOrder]:
        params = {"symbol": symbol} if symbol else {}
        normal = await self._call("GET", "/fapi/v1/openOrders", params, weight=1 if symbol else 40)
        algos = await self._call("GET", "/fapi/v1/openAlgoOrders", params)
        rows = algos.get("orders", algos) if isinstance(algos, dict) else algos
        return [futures_order(o) for o in normal] + [algo_order(o) for o in rows or []]

    async def fills(self, symbol: str, exchange_order_id: str) -> list[Fill]:
        data = await self._call(
            "GET", "/fapi/v1/userTrades", {"symbol": symbol, "orderId": exchange_order_id}, weight=5
        )
        return [
            Fill(
                client_id="",
                exchange_order_id=str(t["orderId"]),
                trade_id=str(t["id"]),
                symbol=symbol,
                side=Side(str(t["side"])),
                price=_dec(t["price"]),
                qty=_dec(t["qty"]),
                commission=_dec(t.get("commission")),
                commission_asset=str(t.get("commissionAsset", "USDT")),
                is_maker=bool(t.get("maker")),
                ts=int(t.get("time", 0)),
                realized_pnl=_dec(t.get("realizedPnl")),
            )
            for t in data
        ]

    async def balances(self) -> list[Balance]:
        data = await self._call("GET", "/fapi/v3/balance", {}, weight=5)
        return [
            Balance(
                b["asset"],
                _dec(b.get("availableBalance")),
                _dec(b.get("balance")) - _dec(b.get("availableBalance")),
            )
            for b in data
        ]

    async def positions(self) -> list[VenuePosition]:
        data = await self._call("GET", "/fapi/v3/positionRisk", {}, weight=5)
        return [
            VenuePosition(
                symbol=p["symbol"],
                quantity=_dec(p.get("positionAmt")),
                entry_price=_dec(p.get("entryPrice")),
                leverage=int(_dec(p.get("leverage") or 1)),
                unrealized_pnl=_dec(p.get("unRealizedProfit")),
                liquidation_price=_dec(p.get("liquidationPrice")) or None,
            )
            for p in data
            if _dec(p.get("positionAmt")) != 0
        ]

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        await self._call("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})

    async def _listen_key(self, method: str) -> str:
        try:
            data = await self.rest.request(
                method, "/fapi/v1/listenKey", params={}, weight=1, api_key_only=True
            )
        except Exception as exc:
            raise map_error(exc) from exc
        return str(data.get("listenKey", "")) if isinstance(data, dict) else ""

    async def _stream_once(self, *, reconnected: bool) -> None:
        key = await self._listen_key("POST")
        url = f"{self._ws_url}/ws/{key}"
        keepalive = asyncio.create_task(self._keepalive())
        try:
            async with websockets.connect(url, open_timeout=10, ping_interval=20) as ws:
                self.stream_connected = True
                if reconnected:
                    await self._queue.put(VenueEvent(kind="stream_reconnected"))
                async for raw in ws:
                    message = json.loads(raw)
                    kind = message.get("e")
                    if kind == "ORDER_TRADE_UPDATE":
                        await self._queue.put(parse_order_trade_update(message))
                    elif kind == "ALGO_UPDATE":
                        # Alan adları doğrulanamadı: olay tetikleyicidir, gerçek durum REST'ten.
                        await self._queue.put(VenueEvent(kind="account", raw={"algo": message}))
                    elif kind == "ACCOUNT_UPDATE":
                        await self._queue.put(VenueEvent(kind="account", raw=message))
                    elif kind == "listenKeyExpired":
                        await self._queue.put(VenueEvent(kind="stream_expired", raw=message))
                        return
        finally:
            keepalive.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await keepalive

    async def _keepalive(self) -> None:
        while True:
            await asyncio.sleep(self._keepalive_s)
            try:
                await self._listen_key("PUT")
            except VenueError as exc:
                logger.warning("listenKey yenilenemedi", extra={"error": str(exc)})
