"""Testler için yerel sahte Binance sunucusu (WebSocket + REST).

Gerçek Binance davranışlarını taklit eder:
* ``/stream``, ``/market/stream``, ``/public/stream`` yollarında birleşik akış; ``SUBSCRIBE`` /
  ``UNSUBSCRIBE`` mesajlarına ``{"result": null, "id": ...}`` yanıtı.
* Abone olunan her akış için sentetik ama biçimi gerçek mesajlar: mum, aggTrade (ardışık kimlik),
  mini/24 saat ticker dizileri, mark price, derinlik farkları (Spot: U/u, Futures: U/u/pu).
* REST: exchangeInfo (gerçek fikstür), derinlik anlık görüntüsü (akışla tutarlı lastUpdateId),
  sunucu saati.
* Arıza enjeksiyonu: tüm bağlantıları düşür, ``serverShutdown`` gönder, veri akışını durdur.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import websockets
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from websockets.asyncio.server import ServerConnection

from ati_engine.api.server import EmbeddedServer, bind_socket

FIXTURES = Path(__file__).parent / "fixtures" / "binance"


@dataclass
class _Client:
    ws: ServerConnection
    path: str
    streams: set[str] = field(default_factory=set)


class FakeBinance:
    def __init__(self, *, interval_s: float = 0.05) -> None:
        self.interval_s = interval_s
        self.clients: list[_Client] = []
        self.control_log: list[
            tuple[float, str, str, list[str]]
        ] = []  # (zaman, yol, yöntem, akışlar)
        self.connections_opened = 0
        self.paused = False
        self._trade_ids: dict[str, int] = defaultdict(lambda: 1_000)
        self._depth_ids: dict[str, int] = defaultdict(lambda: 10_000)
        self._ws_server: Any = None
        self._rest: EmbeddedServer | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self.ws_port = 0
        self.rest_port = 0
        self.spot_info = json.loads((FIXTURES / "spot_exchange_info.json").read_text())
        self.futures_info = json.loads((FIXTURES / "futures_exchange_info.json").read_text())
        self.depth_requests: list[str] = []

    # --- Adresler ------------------------------------------------------------------------

    @property
    def ws_base(self) -> str:
        return f"ws://127.0.0.1:{self.ws_port}"

    @property
    def rest_base(self) -> str:
        return f"http://127.0.0.1:{self.rest_port}"

    def binance_endpoints(self) -> dict[str, str]:
        return {
            "spot_market_data_rest": self.rest_base,
            "spot_market_data_ws": self.ws_base,
            "futures_rest": self.rest_base,
            "futures_ws_public": f"{self.ws_base}/public",
            "futures_ws_market": f"{self.ws_base}/market",
        }

    # --- Yaşam döngüsü --------------------------------------------------------------------

    async def start(self) -> FakeBinance:
        self._ws_server = await websockets.serve(self._handle, "127.0.0.1", 0)
        self.ws_port = self._ws_server.sockets[0].getsockname()[1]
        sock = bind_socket("127.0.0.1", 0)
        self.rest_port = sock.getsockname()[1]
        from uvicorn import Config

        self._rest = EmbeddedServer(
            Config(self._rest_app(), log_config=None, access_log=False, lifespan="off")
        )
        self._tasks.append(asyncio.create_task(self._rest.serve(sockets=[sock])))
        self._tasks.append(asyncio.create_task(self._pump()))
        for _ in range(100):
            if self._rest.started:
                break
            await asyncio.sleep(0.01)
        return self

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._rest is not None:
            self._rest.should_exit = True
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if self._ws_server is not None:
            self._ws_server.close()
            await self._ws_server.wait_closed()

    # --- Arıza enjeksiyonu ----------------------------------------------------------------

    async def drop_all(self) -> None:
        for client in list(self.clients):
            with contextlib.suppress(Exception):
                await client.ws.close(code=1011, reason="test kopması")

    async def server_shutdown(self) -> None:
        msg = json.dumps(
            {"stream": "!serverShutdown", "data": {"e": "serverShutdown", "E": _now()}}
        )
        for client in list(self.clients):
            with contextlib.suppress(Exception):
                await client.ws.send(msg)

    def subscriptions(self) -> set[str]:
        return {s for c in self.clients for s in c.streams}

    # --- WebSocket -----------------------------------------------------------------------

    async def _handle(self, ws: ServerConnection) -> None:
        path = ws.request.path if ws.request is not None else "/"
        client = _Client(ws=ws, path=path)
        self.clients.append(client)
        self.connections_opened += 1
        try:
            async for raw in ws:
                msg = json.loads(raw)
                method = msg.get("method")
                params = list(msg.get("params") or [])
                self.control_log.append((time.monotonic(), path, str(method), params))
                if method == "SUBSCRIBE":
                    client.streams.update(params)
                elif method == "UNSUBSCRIBE":
                    client.streams.difference_update(params)
                await ws.send(json.dumps({"result": None, "id": msg.get("id")}))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.remove(client)

    async def _pump(self) -> None:
        while True:
            await asyncio.sleep(self.interval_s)
            if self.paused:
                continue
            for client in list(self.clients):
                futures = client.path.startswith(("/market", "/public"))
                for stream in sorted(client.streams):
                    payload = self._message(stream, futures)
                    if payload is None:
                        continue
                    with contextlib.suppress(Exception):
                        await client.ws.send(json.dumps({"stream": stream, "data": payload}))

    def _message(self, stream: str, futures: bool) -> Any:
        now = _now()
        symbol, _, kind = stream.partition("@")
        sym = symbol.upper()
        if stream in ("!miniTicker@arr", "!ticker@arr"):
            return [
                {
                    "e": "24hrMiniTicker",
                    "E": now,
                    "s": s,
                    "c": "101",
                    "o": "100",
                    "h": "102",
                    "l": "99",
                    "v": "10",
                    "q": str(1000 + i),
                }
                for i, s in enumerate(("BTCUSDT", "ETHUSDT", "SOLUSDT"))
            ]
        if stream.startswith("!markPrice@arr"):
            return [
                {
                    "e": "markPriceUpdate",
                    "E": now,
                    "s": "BTCUSDT",
                    "p": "100.5",
                    "i": "100.4",
                    "r": "0.0001",
                    "T": now + 3_600_000,
                }
            ]
        if stream == "!forceOrder@arr":
            return None
        if kind.startswith("kline_"):
            return {
                "e": "kline",
                "E": now,
                "s": sym,
                "k": {
                    "t": now - now % 60_000,
                    "T": now - now % 60_000 + 59_999,
                    "s": sym,
                    "i": kind[6:],
                    "o": "100",
                    "c": "101",
                    "h": "102",
                    "l": "99",
                    "v": "1",
                    "n": 3,
                    "x": False,
                    "q": "100",
                    "V": "0.5",
                    "Q": "50",
                },
            }
        if kind == "aggTrade":
            self._trade_ids[stream] += 1
            return {
                "e": "aggTrade",
                "E": now,
                "s": sym,
                "a": self._trade_ids[stream],
                "p": "100.1",
                "q": "0.5",
                "f": 1,
                "l": 1,
                "T": now,
                "m": False,
            }
        if kind.startswith("depth"):
            key = f"{'f' if futures else 's'}:{sym}"
            prev = self._depth_ids[key]
            first, final = prev + 1, prev + 3
            self._depth_ids[key] = final
            data = {
                "e": "depthUpdate",
                "E": now,
                "s": sym,
                "U": first,
                "u": final,
                "b": [["100", "1.5"]],
                "a": [["101", "2.5"]],
            }
            if futures:
                data["pu"] = prev
            return data
        return None

    # --- REST ----------------------------------------------------------------------------

    def _rest_app(self) -> FastAPI:
        app = FastAPI()
        headers = {"X-MBX-USED-WEIGHT-1M": "10"}

        @app.get("/api/v3/exchangeInfo")
        async def spot_info() -> JSONResponse:
            return JSONResponse(self.spot_info, headers=headers)

        @app.get("/fapi/v1/exchangeInfo")
        async def futures_info() -> JSONResponse:
            return JSONResponse(self.futures_info, headers=headers)

        def depth(prefix: str, symbol: str) -> JSONResponse:
            self.depth_requests.append(f"{prefix}:{symbol}")
            last = self._depth_ids[f"{prefix}:{symbol}"]
            body = {
                "lastUpdateId": last,
                "bids": [["100", "1"], ["99", "2"]],
                "asks": [["101", "1"], ["102", "2"]],
            }
            return JSONResponse(body, headers=headers)

        @app.get("/api/v3/depth")
        async def spot_depth(symbol: str, limit: int = 100) -> JSONResponse:
            return depth("s", symbol)

        @app.get("/fapi/v1/depth")
        async def futures_depth(symbol: str, limit: int = 100) -> JSONResponse:
            return depth("f", symbol)

        @app.get("/api/v3/time")
        @app.get("/fapi/v1/time")
        async def server_time() -> dict[str, int]:
            return {"serverTime": _now()}

        return app


def _now() -> int:
    return time.time_ns() // 1_000_000
