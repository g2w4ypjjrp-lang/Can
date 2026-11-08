"""Test için sahte Binance işlem sunucusu (Spot + USDⓈ-M Futures, REST + WebSocket).

2026-11 Binance kurallarını taklit eder:

* HMAC imzası doğrulanır (yanlış imza → -1022); imza, yüzde-kodlanmış sorgu dizesi üzerinden.
* Futures koşullu emirleri yalnızca ``/fapi/v1/algoOrder``'da kabul edilir; eski emir uç noktası
  bunları -4120 ile reddeder. Tetiklenen koşullu emir, bizim bilmediğimiz bir istemci
  kimliğiyle gerçek bir piyasa emri oluşturur (``actualOrderId``).
* Spot kullanıcı akışı WebSocket API ``userDataStream.subscribe.signature`` ile; Futures
  ``/fapi/v1/listenKey`` + ``/private/ws/<listenKey>``.
* Arıza enjeksiyonu: emir borsaya ulaştıktan sonra 503 (durum bilinmiyor), -1007, yetersiz
  bakiye, mükerrer istemci kimliği.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import itertools
import json
import time
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl

import websockets
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from websockets.asyncio.server import ServerConnection

from ati_engine.api.server import EmbeddedServer, bind_socket

D = Decimal


def _now() -> int:
    return int(time.time() * 1000)


def _err(code: int, msg: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"code": code, "msg": msg}, status_code=status)


class FakeExchange:
    def __init__(self, api_key: str = "test-anahtar", secret: str = "test-gizli") -> None:  # noqa: S107
        self.api_key = api_key
        self.secret = secret.encode()
        self.prices: dict[str, Decimal] = {}
        self.spot_balances: dict[str, Decimal] = {"USDT": D(100_000)}
        self.futures_wallet = D(100_000)
        self.futures_positions: dict[str, tuple[Decimal, Decimal]] = {}
        self.spot_orders: dict[str, dict[str, Any]] = {}
        self.futures_orders: dict[str, dict[str, Any]] = {}
        self.algo_orders: dict[str, dict[str, Any]] = {}
        self.trades: list[dict[str, Any]] = []
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.fail_next: list[str] = []  # "503_after", "1007_after", "503_before"
        self.signature_failures = 0
        self.listen_keys: set[str] = set()
        self.restrictions: dict[str, Any] = {
            "ipRestrict": True,
            "enableReading": True,
            "enableWithdrawals": False,
            "enableInternalTransfer": False,
            "permitsUniversalTransfer": False,
            "enableSpotAndMarginTrading": True,
            "enableFutures": True,
            "enableMargin": False,
        }
        self._ids = itertools.count(1000)
        self._spot_ws: set[ServerConnection] = set()
        self._futures_ws: set[ServerConnection] = set()
        self._tasks: list[asyncio.Task[None]] = []
        self._rest: EmbeddedServer | None = None
        self._ws_server: Any = None
        self.rest_port = 0
        self.ws_port = 0

    # --- Adresler ------------------------------------------------------------------------

    @property
    def rest_url(self) -> str:
        return f"http://127.0.0.1:{self.rest_port}"

    @property
    def ws_api_url(self) -> str:
        return f"ws://127.0.0.1:{self.ws_port}/ws-api/v3"

    @property
    def private_ws_url(self) -> str:
        return f"ws://127.0.0.1:{self.ws_port}/private"

    async def start(self) -> FakeExchange:
        self._ws_server = await websockets.serve(self._ws_handler, "127.0.0.1", 0)
        self.ws_port = self._ws_server.sockets[0].getsockname()[1]
        sock = bind_socket("127.0.0.1", 0)
        self.rest_port = sock.getsockname()[1]
        from uvicorn import Config

        self._rest = EmbeddedServer(
            Config(self._app(), log_config=None, access_log=False, lifespan="off")
        )
        self._tasks.append(asyncio.create_task(self._rest.serve(sockets=[sock])))
        for _ in range(100):
            if self._rest.started:
                break
            await asyncio.sleep(0.01)
        return self

    async def stop(self) -> None:
        if self._rest is not None:
            self._rest.should_exit = True
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(task, 5)
        if self._ws_server is not None:
            self._ws_server.close()
            await self._ws_server.wait_closed()

    # --- İmza --------------------------------------------------------------------------

    def _verify(self, raw_query: str) -> dict[str, str] | None:
        payload, _, signature = raw_query.rpartition("&signature=")
        expected = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            self.signature_failures += 1
            return None
        return dict(parse_qsl(payload, keep_blank_values=True))

    # --- Eşleştirme -----------------------------------------------------------------------

    def _spot_fill(self, order: dict[str, Any], price: Decimal) -> dict[str, Any]:
        qty = D(order["origQty"])
        base = order["symbol"].removesuffix("USDT")
        fee = (qty * price * D("0.001")).quantize(D("0.00000001"))
        if order["side"] == "BUY":
            self.spot_balances["USDT"] -= qty * price + fee
            self.spot_balances[base] = self.spot_balances.get(base, D(0)) + qty
        else:
            self.spot_balances[base] = self.spot_balances.get(base, D(0)) - qty
            self.spot_balances["USDT"] += qty * price - fee
        trade = {
            "id": next(self._ids),
            "orderId": order["orderId"],
            "price": str(price),
            "qty": str(qty),
            "commission": str(fee),
            "commissionAsset": "USDT",
            "isBuyer": order["side"] == "BUY",
            "isMaker": False,
            "time": _now(),
            "market": "spot",
            "symbol": order["symbol"],
        }
        self.trades.append(trade)
        order.update(
            status="FILLED",
            executedQty=str(qty),
            cummulativeQuoteQty=str(qty * price),
            updateTime=_now(),
        )
        return trade

    def _futures_fill(self, order: dict[str, Any], price: Decimal) -> dict[str, Any]:
        qty = D(order["origQty"])
        signed = qty if order["side"] == "BUY" else -qty
        current, entry = self.futures_positions.get(order["symbol"], (D(0), D(0)))
        realized = D(0)
        if current == 0 or (current > 0) == (signed > 0):
            entry = (abs(current) * entry + qty * price) / (abs(current) + qty)
        else:
            realized = (price - entry) * min(qty, abs(current)) * (1 if current > 0 else -1)
        current += signed
        if current == 0:
            self.futures_positions.pop(order["symbol"], None)
        else:
            self.futures_positions[order["symbol"]] = (current, entry)
        fee = (qty * price * D("0.0005")).quantize(D("0.00000001"))
        self.futures_wallet += realized - fee
        trade = {
            "id": next(self._ids),
            "orderId": order["orderId"],
            "side": order["side"],
            "price": str(price),
            "qty": str(qty),
            "commission": str(fee),
            "commissionAsset": "USDT",
            "realizedPnl": str(realized),
            "maker": False,
            "time": _now(),
            "market": "futures",
            "symbol": order["symbol"],
        }
        self.trades.append(trade)
        order.update(status="FILLED", executedQty=str(qty), avgPrice=str(price), updateTime=_now())
        return trade

    async def set_price(self, symbol: str, price: Decimal) -> None:
        """Fiyatı günceller; tetiklenen emirleri doldurur ve kullanıcı akışına yayınlar."""
        self.prices[symbol] = price
        for order in list(self.spot_orders.values()):
            if order["symbol"] != symbol or order["status"] != "NEW":
                continue
            stop = order["type"] in ("STOP_LOSS",) and price <= D(order["stopPrice"])
            limit = order["type"] in ("LIMIT", "LIMIT_MAKER") and price >= D(order["price"])
            if stop or limit:
                trade = self._spot_fill(order, price if stop else D(order["price"]))
                await self._push_spot(order, trade)
                sibling = order.get("_sibling")
                if sibling and self.spot_orders[sibling]["status"] == "NEW":
                    self.spot_orders[sibling]["status"] = "CANCELED"
                    await self._push_spot(self.spot_orders[sibling], None)
        for algo in list(self.algo_orders.values()):
            if algo["symbol"] != symbol or algo["algoStatus"] != "NEW":
                continue
            if algo["type"] not in ("STOP_MARKET", "TAKE_PROFIT_MARKET"):
                continue  # iz süren stop sahte sunucuda tetiklenmez
            trigger = D(algo["triggerPrice"])
            sell = algo["side"] == "SELL"
            hit = (
                (price <= trigger if sell else price >= trigger)
                if algo["type"] == "STOP_MARKET"
                else (price >= trigger if sell else price <= trigger)
            )
            if not hit:
                continue
            current = self.futures_positions.get(symbol, (D(0), D(0)))[0]
            qty = abs(current) if algo.get("closePosition") == "true" else D(algo["quantity"])
            actual_id = next(self._ids)
            actual = {
                "orderId": actual_id,
                "clientOrderId": f"autoclose-{actual_id}",
                "symbol": symbol,
                "side": algo["side"],
                "type": "MARKET",
                "origQty": str(qty),
                "price": "0",
                "status": "NEW",
                "reduceOnly": True,
            }
            self.futures_orders[actual["clientOrderId"]] = actual
            trade = self._futures_fill(actual, price)
            algo.update(algoStatus="FINISHED", actualOrderId=actual_id, updateTime=_now())
            await self._push_futures({"e": "ALGO_UPDATE", "E": _now(), "o": {"st": "FINISHED"}})
            await self._push_futures(self._order_update(actual, trade))

    async def drop_streams(self) -> None:
        """Tüm kullanıcı akışı bağlantılarını koparır (yeniden bağlanma testi)."""
        for ws in list(self._spot_ws | self._futures_ws):
            with contextlib.suppress(Exception):
                await ws.close(code=1011, reason="test kopması")

    # --- Kullanıcı akışı ------------------------------------------------------------------

    async def _push_spot(self, order: dict[str, Any], trade: dict[str, Any] | None) -> None:
        event = {
            "e": "executionReport",
            "E": _now(),
            "s": order["symbol"],
            "c": order["clientOrderId"],
            "S": order["side"],
            "o": order["type"],
            "q": order["origQty"],
            "p": order.get("price", "0"),
            "P": order.get("stopPrice", "0"),
            "x": "TRADE" if trade else order["status"],
            "X": order["status"],
            "i": order["orderId"],
            "l": trade["qty"] if trade else "0",
            "z": order.get("executedQty", "0"),
            "L": trade["price"] if trade else "0",
            "n": trade["commission"] if trade else "0",
            "N": trade["commissionAsset"] if trade else None,
            "T": _now(),
            "t": trade["id"] if trade else -1,
            "m": False,
            "Z": order.get("cummulativeQuoteQty", "0"),
            "g": order.get("orderListId", -1),
            "C": "",
        }
        message = json.dumps({"subscriptionId": 0, "event": event})
        for ws in list(self._spot_ws):
            with contextlib.suppress(Exception):
                await ws.send(message)

    def _order_update(self, order: dict[str, Any], trade: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "e": "ORDER_TRADE_UPDATE",
            "E": _now(),
            "T": _now(),
            "o": {
                "s": order["symbol"],
                "c": order["clientOrderId"],
                "S": order["side"],
                "o": order["type"],
                "q": order["origQty"],
                "p": order.get("price", "0"),
                "ap": order.get("avgPrice", "0"),
                "x": "TRADE" if trade else order["status"],
                "X": order["status"],
                "i": order["orderId"],
                "l": trade["qty"] if trade else "0",
                "z": order.get("executedQty", "0"),
                "L": trade["price"] if trade else "0",
                "N": "USDT",
                "n": trade["commission"] if trade else "0",
                "T": _now(),
                "t": trade["id"] if trade else 0,
                "m": False,
                "R": bool(order.get("reduceOnly")),
                "rp": trade["realizedPnl"] if trade else "0",
            },
        }

    async def _push_futures(self, message: dict[str, Any]) -> None:
        text = json.dumps(message)
        for ws in list(self._futures_ws):
            with contextlib.suppress(Exception):
                await ws.send(text)

    async def _ws_handler(self, ws: ServerConnection) -> None:
        path = ws.request.path if ws.request else ""
        if path.startswith("/ws-api/v3"):
            async for raw in ws:
                message = json.loads(raw)
                if message.get("method") != "userDataStream.subscribe.signature":
                    continue
                params = dict(message["params"])
                signature = params.pop("signature", "")
                payload = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
                expected = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()
                if params.get("apiKey") != self.api_key or signature != expected:
                    self.signature_failures += 1
                    await ws.send(json.dumps({"id": message["id"], "status": 401}))
                    continue
                self._spot_ws.add(ws)
                await ws.send(
                    json.dumps(
                        {"id": message["id"], "status": 200, "result": {"subscriptionId": 0}}
                    )
                )
            self._spot_ws.discard(ws)
            return
        if path.startswith("/private/ws/"):
            key = path.rsplit("/", 1)[-1]
            if key not in self.listen_keys:
                await ws.close(code=4001, reason="geçersiz listenKey")
                return
            self._futures_ws.add(ws)
            with contextlib.suppress(Exception):
                await ws.wait_closed()
            self._futures_ws.discard(ws)

    # --- REST ------------------------------------------------------------------------------

    def _app(self) -> FastAPI:
        app = FastAPI()
        exchange = self

        async def signed(request: Request) -> dict[str, str] | JSONResponse:
            if request.headers.get("X-MBX-APIKEY") != exchange.api_key:
                return _err(-2015, "Invalid API-key, IP, or permissions for action.", 401)
            params = exchange._verify(request.url.query)
            if params is None:
                return _err(-1022, "Signature for this request is not valid.")
            exchange.requests.append((request.method, request.url.path, params))
            return params

        def inject(stage: str) -> JSONResponse | None:
            if exchange.fail_next and exchange.fail_next[0].endswith(stage):
                kind = exchange.fail_next.pop(0)
                if kind.startswith("503"):
                    return _err(-1001, "Internal error", 503)
                if kind.startswith("1007"):
                    return _err(-1007, "Timeout waiting for response from backend server.", 408)
            return None

        @app.post("/api/v3/order")
        async def spot_place(request: Request) -> Any:
            p = await signed(request)
            if isinstance(p, JSONResponse):
                return p
            if failure := inject("before"):
                return failure
            cid = p["newClientOrderId"]
            if cid in exchange.spot_orders and exchange.spot_orders[cid]["status"] == "NEW":
                return _err(-2010, "Duplicate order sent.")
            if cid in exchange.spot_orders:
                return _err(-2010, "Duplicate order sent.")
            price = exchange.prices[p["symbol"]]
            qty = D(p["quantity"])
            base = p["symbol"].removesuffix("USDT")
            if p["side"] == "BUY" and qty * price * D("1.001") > exchange.spot_balances["USDT"]:
                return _err(-2010, "Account has insufficient balance for requested action.")
            if p["side"] == "SELL" and qty > exchange.spot_balances.get(base, D(0)):
                return _err(-2010, "Account has insufficient balance for requested action.")
            order = {
                "symbol": p["symbol"],
                "orderId": next(exchange._ids),
                "orderListId": -1,
                "clientOrderId": cid,
                "price": p.get("price", "0"),
                "stopPrice": p.get("stopPrice", "0"),
                "origQty": p["quantity"],
                "executedQty": "0",
                "cummulativeQuoteQty": "0",
                "status": "NEW",
                "type": p["type"],
                "side": p["side"],
                "transactTime": _now(),
            }
            exchange.spot_orders[cid] = order
            fills = []
            if p["type"] == "MARKET":
                trade = exchange._spot_fill(order, price)
                fills.append(
                    {
                        "price": trade["price"],
                        "qty": trade["qty"],
                        "commission": trade["commission"],
                        "commissionAsset": "USDT",
                        "tradeId": trade["id"],
                    }
                )
                await exchange._push_spot(order, trade)
            else:
                await exchange._push_spot(order, None)
            if failure := inject("after"):
                return failure
            return {k: v for k, v in order.items() if not k.startswith("_")} | {"fills": fills}

        @app.post("/api/v3/orderList/oco")
        async def spot_oco(request: Request) -> Any:
            p = await signed(request)
            if isinstance(p, JSONResponse):
                return p
            list_id = next(exchange._ids)
            legs = []
            for prefix, otype, price_key in (
                ("above", p["aboveType"], "abovePrice"),
                ("below", p["belowType"], "belowStopPrice"),
            ):
                cid = p[f"{prefix}ClientOrderId"]
                order = {
                    "symbol": p["symbol"],
                    "orderId": next(exchange._ids),
                    "orderListId": list_id,
                    "clientOrderId": cid,
                    "price": p.get(price_key, "0") if prefix == "above" else "0",
                    "stopPrice": p.get(price_key, "0") if prefix == "below" else "0",
                    "origQty": p["quantity"],
                    "executedQty": "0",
                    "cummulativeQuoteQty": "0",
                    "status": "NEW",
                    "type": otype,
                    "side": p["side"],
                    "transactTime": _now(),
                }
                exchange.spot_orders[cid] = order
                legs.append(order)
            legs[0]["_sibling"] = legs[1]["clientOrderId"]
            legs[1]["_sibling"] = legs[0]["clientOrderId"]
            return {
                "orderListId": list_id,
                "listClientOrderId": p["listClientOrderId"],
                "orderReports": [
                    {k: v for k, v in o.items() if not k.startswith("_")} for o in legs
                ],
            }

        @app.get("/api/v3/order")
        async def spot_query(request: Request) -> Any:
            p = await signed(request)
            if isinstance(p, JSONResponse):
                return p
            order = exchange.spot_orders.get(p["origClientOrderId"])
            if order is None:
                return _err(-2013, "Order does not exist.")
            return {k: v for k, v in order.items() if not k.startswith("_")}

        @app.delete("/api/v3/order")
        async def spot_cancel(request: Request) -> Any:
            p = await signed(request)
            if isinstance(p, JSONResponse):
                return p
            order = exchange.spot_orders.get(p["origClientOrderId"])
            if order is None or order["status"] != "NEW":
                return _err(-2011, "Unknown order sent.")
            order["status"] = "CANCELED"
            await exchange._push_spot(order, None)
            return {k: v for k, v in order.items() if not k.startswith("_")} | {
                "origClientOrderId": order["clientOrderId"]
            }

        @app.get("/api/v3/openOrders")
        async def spot_open(request: Request) -> Any:
            p = await signed(request)
            if isinstance(p, JSONResponse):
                return p
            return [
                {k: v for k, v in o.items() if not k.startswith("_")}
                for o in exchange.spot_orders.values()
                if o["status"] == "NEW" and (not p.get("symbol") or o["symbol"] == p["symbol"])
            ]

        @app.get("/api/v3/myTrades")
        async def spot_trades(request: Request) -> Any:
            p = await signed(request)
            if isinstance(p, JSONResponse):
                return p
            return [
                t
                for t in exchange.trades
                if t["market"] == "spot" and str(t["orderId"]) == p["orderId"]
            ]

        @app.get("/api/v3/account")
        async def spot_account(request: Request) -> Any:
            p = await signed(request)
            if isinstance(p, JSONResponse):
                return p
            return {
                "canTrade": True,
                "balances": [
                    {"asset": a, "free": str(v), "locked": "0"}
                    for a, v in exchange.spot_balances.items()
                ],
            }

        # --- Futures ---

        @app.post("/fapi/v1/order")
        async def futures_place(request: Request) -> Any:
            p = await signed(request)
            if isinstance(p, JSONResponse):
                return p
            if p["type"] in ("STOP_MARKET", "TAKE_PROFIT_MARKET", "TRAILING_STOP_MARKET"):
                return _err(-4120, "STOP_ORDER_SWITCH_ALGO")
            if failure := inject("before"):
                return failure
            cid = p["newClientOrderId"]
            if cid in exchange.futures_orders:
                return _err(-4116, "ClientOrderId is duplicated.")
            order = {
                "symbol": p["symbol"],
                "orderId": next(exchange._ids),
                "clientOrderId": cid,
                "price": p.get("price", "0"),
                "origQty": p["quantity"],
                "executedQty": "0",
                "avgPrice": "0",
                "status": "NEW",
                "type": p["type"],
                "side": p["side"],
                "reduceOnly": p.get("reduceOnly") == "true",
                "updateTime": _now(),
            }
            exchange.futures_orders[cid] = order
            if p["type"] == "MARKET":
                trade = exchange._futures_fill(order, exchange.prices[p["symbol"]])
                await exchange._push_futures(exchange._order_update(order, trade))
            if failure := inject("after"):
                return failure
            return order

        @app.get("/fapi/v1/order")
        async def futures_query(request: Request) -> Any:
            p = await signed(request)
            if isinstance(p, JSONResponse):
                return p
            order = exchange.futures_orders.get(p["origClientOrderId"])
            return order if order else _err(-2013, "Order does not exist.")

        @app.delete("/fapi/v1/order")
        async def futures_cancel(request: Request) -> Any:
            p = await signed(request)
            if isinstance(p, JSONResponse):
                return p
            order = exchange.futures_orders.get(p["origClientOrderId"])
            if order is None or order["status"] != "NEW":
                return _err(-2011, "Unknown order sent.")
            order["status"] = "CANCELED"
            return order

        @app.post("/fapi/v1/algoOrder")
        async def algo_place(request: Request) -> Any:
            p = await signed(request)
            if isinstance(p, JSONResponse):
                return p
            if p.get("algoType") != "CONDITIONAL":
                return _err(-1102, "algoType gerekli")
            if "quantity" in p and p.get("closePosition") == "true":
                return _err(-1106, "quantity closePosition ile gönderilemez")
            algo = {
                "algoId": next(exchange._ids),
                "clientAlgoId": p["clientAlgoId"],
                "algoType": "CONDITIONAL",
                "orderType": p["type"],
                "type": p["type"],
                "symbol": p["symbol"],
                "side": p["side"],
                "quantity": p.get("quantity", "0"),
                "triggerPrice": p.get("triggerPrice", "0"),
                "closePosition": p.get("closePosition"),
                "algoStatus": "NEW",
                "updateTime": _now(),
            }
            exchange.algo_orders[p["clientAlgoId"]] = algo
            return algo

        @app.get("/fapi/v1/algoOrder")
        async def algo_query(request: Request) -> Any:
            p = await signed(request)
            if isinstance(p, JSONResponse):
                return p
            algo = exchange.algo_orders.get(p["clientAlgoId"])
            return algo if algo else _err(-2013, "Order does not exist.")

        @app.delete("/fapi/v1/algoOrder")
        async def algo_cancel(request: Request) -> Any:
            p = await signed(request)
            if isinstance(p, JSONResponse):
                return p
            algo = exchange.algo_orders.get(p["clientAlgoId"])
            if algo is None or algo["algoStatus"] != "NEW":
                return _err(-2011, "Unknown order sent.")
            algo["algoStatus"] = "CANCELED"
            return {"algoId": algo["algoId"], "clientAlgoId": algo["clientAlgoId"], "code": "200"}

        @app.get("/fapi/v1/openOrders")
        async def futures_open(request: Request) -> Any:
            p = await signed(request)
            if isinstance(p, JSONResponse):
                return p
            return [o for o in exchange.futures_orders.values() if o["status"] == "NEW"]

        @app.get("/fapi/v1/openAlgoOrders")
        async def algo_open(request: Request) -> Any:
            p = await signed(request)
            if isinstance(p, JSONResponse):
                return p
            return [a for a in exchange.algo_orders.values() if a["algoStatus"] == "NEW"]

        @app.get("/fapi/v1/userTrades")
        async def futures_trades(request: Request) -> Any:
            p = await signed(request)
            if isinstance(p, JSONResponse):
                return p
            return [
                t
                for t in exchange.trades
                if t["market"] == "futures" and str(t["orderId"]) == p["orderId"]
            ]

        @app.get("/fapi/v3/balance")
        async def futures_balance(request: Request) -> Any:
            p = await signed(request)
            if isinstance(p, JSONResponse):
                return p
            wallet = str(exchange.futures_wallet)
            return [{"asset": "USDT", "balance": wallet, "availableBalance": wallet}]

        @app.get("/fapi/v3/positionRisk")
        async def futures_positions(request: Request) -> Any:
            p = await signed(request)
            if isinstance(p, JSONResponse):
                return p
            return [
                {"symbol": s, "positionAmt": str(q), "entryPrice": str(e), "unRealizedProfit": "0"}
                for s, (q, e) in exchange.futures_positions.items()
            ]

        @app.post("/fapi/v1/leverage")
        async def futures_leverage(request: Request) -> Any:
            p = await signed(request)
            if isinstance(p, JSONResponse):
                return p
            return {"symbol": p["symbol"], "leverage": int(p["leverage"])}

        def symbol_rules(symbol: str) -> dict[str, Any]:
            return {
                "symbol": symbol,
                "status": "TRADING",
                "baseAsset": symbol.removesuffix("USDT"),
                "quoteAsset": "USDT",
                "contractType": "PERPETUAL",
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                    {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                    {"filterType": "MIN_NOTIONAL", "notional": "5", "minNotional": "5"},
                ],
            }

        @app.get("/api/v3/time")
        @app.get("/fapi/v1/time")
        async def server_time() -> Any:
            return {"serverTime": _now()}

        @app.get("/api/v3/exchangeInfo")
        @app.get("/fapi/v1/exchangeInfo")
        async def exchange_info() -> Any:
            return {"symbols": [symbol_rules(s) for s in sorted(exchange.prices)]}

        @app.get("/sapi/v1/account/apiRestrictions")
        async def api_restrictions(request: Request) -> Any:
            p = await signed(request)
            if isinstance(p, JSONResponse):
                return p
            return exchange.restrictions

        @app.api_route("/fapi/v1/listenKey", methods=["POST", "PUT"])
        async def listen_key(request: Request) -> Any:
            if request.headers.get("X-MBX-APIKEY") != exchange.api_key:
                return _err(-2015, "Invalid API-key", 401)
            key = "dinleme-anahtari-1"
            exchange.listen_keys.add(key)
            return {"listenKey": key}

        return app
