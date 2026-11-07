"""Binance WebSocket akış yönetimi.

``StreamConnection`` tek bir birleşik akış bağlantısıdır:
* Akışlara ``SUBSCRIBE`` / ``UNSUBSCRIBE`` mesajlarıyla abone olur; mesajlar parti halinde ve
  bağlantı başına mesaj limitinin altında gönderilir (Spot 5/sn, Futures 10/sn; Binance ping/pong
  çerçevelerini de bu limite sayar).
* Kopmada üstel geri çekilme + rastgele sapma ile yeniden bağlanır; bağlantı açma denemeleri IP
  limitine karşı paylaşılan bir sınırlayıcıdan geçer.
* ``serverShutdown`` olayında beklemeden yeniden bağlanır.
* ``stale_after_s`` boyunca mesaj gelmezse bağlantıyı ölü sayıp yeniden açar.
* 24 saatlik bağlantı ömrü dolmadan **önce yeni bağlantıyı açar, abone olur, ilk veriyi alınca
  eskisini kapatır** (kesintisiz yenileme).

``StreamManager`` bir piyasanın tüm akışlarını bağlantılara paylaştırır (bağlantı başına en
fazla ``streams_per_connection``), akış listesi değiştikçe yalnızca farkı gönderir ve
bağlantıların sağlığını tek bir "hazır" bilgisine indirger.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
import random
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection

from ati_engine.core.models import Market
from ati_engine.exchange.endpoints import MarketEndpoints, WsRoute
from ati_engine.market.parsing import ControlMessage, ParsedMessage, StreamKind, parse_message

logger = logging.getLogger(__name__)

ParsedHandler = Callable[[ParsedMessage], Awaitable[None]]
StateHandler = Callable[["StreamConnection", bool, str], Awaitable[None]]

_request_ids = itertools.count(1)


class ConnectionAttemptLimiter:
    """Kayan pencerede bağlantı açma denemesi sınırı (Spot: 5 dakikada 300 / IP)."""

    def __init__(self, max_attempts: int = 300, window_s: float = 300.0) -> None:
        self._max = max_attempts
        self._window = window_s
        self._times: deque[float] = deque()

    async def acquire(self) -> None:
        while True:
            now = time.monotonic()
            while self._times and now - self._times[0] > self._window:
                self._times.popleft()
            if len(self._times) < self._max:
                self._times.append(now)
                return
            await asyncio.sleep(self._window - (now - self._times[0]) + 0.01)


class _ServerShutdown(Exception):
    pass


class _Stale(Exception):
    pass


@dataclass
class ConnectionStatus:
    name: str
    route: str
    url: str
    connected: bool
    healthy: bool
    streams: int
    subscribed: int
    messages: int
    reconnects: int
    last_message_age_s: float | None
    connected_for_s: float | None
    last_error: str | None


class StreamConnection:
    def __init__(
        self,
        *,
        name: str,
        url: str,
        route: WsRoute,
        market: Market,
        on_parsed: ParsedHandler,
        on_state: StateHandler | None = None,
        attempt_limiter: ConnectionAttemptLimiter | None = None,
        control_rate_per_s: float = 3.0,
        batch_size: int = 100,
        stale_after_s: float = 30.0,
        max_lifetime_s: float = 23.5 * 3600,
        backoff_initial_s: float = 1.0,
        backoff_max_s: float = 60.0,
        open_timeout_s: float = 10.0,
    ) -> None:
        self.name = name
        self.url = url
        self.route = route
        self.market = market
        self._on_parsed = on_parsed
        self._on_state = on_state
        self._attempts = attempt_limiter or ConnectionAttemptLimiter()
        self._control_interval = 1.0 / control_rate_per_s
        self._batch = batch_size
        self.stale_after_s = stale_after_s
        self._max_lifetime = max_lifetime_s
        self._backoff_initial = backoff_initial_s
        self._backoff_max = backoff_max_s
        self._open_timeout = open_timeout_s

        self.desired: set[str] = set()
        self.subscribed: set[str] = set()
        self._changed = asyncio.Event()
        self._ws: ClientConnection | None = None
        self._last_control = 0.0
        self._stopping = False
        self.connected = False
        self.renewing = False
        self.messages = 0
        self.reconnects = 0
        self.control_errors = 0
        self.last_message_at: float | None = None
        self.connected_at: float | None = None
        self.last_error: str | None = None

    # --- Dış arayüz -------------------------------------------------------------------

    def update(self, streams: Iterable[str]) -> None:
        self.desired = set(streams)
        self._changed.set()

    def healthy(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        if not self.desired:
            return True
        fresh = self.last_message_at is not None and now - self.last_message_at < self.stale_after_s
        return (self.connected or self.renewing) and fresh

    def status(self) -> ConnectionStatus:
        now = time.monotonic()
        return ConnectionStatus(
            name=self.name,
            route=self.route.value,
            url=self.url,
            connected=self.connected,
            healthy=self.healthy(now),
            streams=len(self.desired),
            subscribed=len(self.subscribed),
            messages=self.messages,
            reconnects=self.reconnects,
            last_message_age_s=None if self.last_message_at is None else now - self.last_message_at,
            connected_for_s=None if self.connected_at is None else now - self.connected_at,
            last_error=self.last_error,
        )

    async def stop(self) -> None:
        self._stopping = True
        self._changed.set()
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()

    # --- Yaşam döngüsü ------------------------------------------------------------------

    async def run(self) -> None:
        failures = 0
        while not self._stopping:
            await self._attempts.acquire()
            started = time.monotonic()
            immediate = False
            try:
                ws = await websockets.connect(
                    self.url,
                    open_timeout=self._open_timeout,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=2,
                    max_size=16 * 1024 * 1024,
                    max_queue=1024,
                )
                await self._session(ws)
            except asyncio.CancelledError:
                raise
            except _ServerShutdown:
                self.last_error = "sunucu kapanıyor (serverShutdown)"
                immediate = True
            except _Stale:
                self.last_error = f"{self.stale_after_s:.0f} sn veri gelmedi"
            except (OSError, TimeoutError, websockets.exceptions.WebSocketException) as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"[:300]
            finally:
                was_connected = self.connected
                self.connected = False
                self.renewing = False
                self.subscribed.clear()
                if self._ws is not None:
                    with contextlib.suppress(Exception):
                        await self._ws.close()
                    self._ws = None
                if was_connected:
                    await self._notify(False, self.last_error or "bağlantı kapandı")
            if self._stopping:
                break
            self.reconnects += 1
            failures = 0 if time.monotonic() - started > 60 else failures + 1
            if immediate:
                continue
            delay = min(self._backoff_max, self._backoff_initial * (2 ** min(failures, 10)))
            await asyncio.sleep(delay * random.uniform(0.5, 1.0))  # noqa: S311 - kriptografik değil

    async def _notify(self, connected: bool, reason: str) -> None:
        if self._on_state is not None:
            try:
                await self._on_state(self, connected, reason)
            except Exception:
                logger.exception("Bağlantı durum bildirimi hata verdi")

    async def _send_control(self, ws: ClientConnection, method: str, params: list[str]) -> None:
        wait = self._last_control + self._control_interval - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_control = time.monotonic()
        await ws.send(json.dumps({"method": method, "params": params, "id": next(_request_ids)}))

    async def _sync_subscriptions(self, ws: ClientConnection) -> None:
        while True:
            to_remove = sorted(self.subscribed - self.desired)
            to_add = sorted(self.desired - self.subscribed)
            if not to_add and not to_remove:
                return
            if to_remove:
                batch = to_remove[: self._batch]
                await self._send_control(ws, "UNSUBSCRIBE", batch)
                self.subscribed.difference_update(batch)
            elif to_add:
                batch = to_add[: self._batch]
                await self._send_control(ws, "SUBSCRIBE", batch)
                self.subscribed.update(batch)

    async def _handle(self, raw: str | bytes) -> None:
        self.last_message_at = time.monotonic()
        self.messages += 1
        parsed = parse_message(self.market, raw)
        if parsed is None:
            return
        if isinstance(parsed, ControlMessage):
            if parsed.error:
                self.control_errors += 1
                logger.warning(
                    "Binance abonelik hatası",
                    extra={"connection": self.name, "error": parsed.error},
                )
            return
        if parsed.kind is StreamKind.SERVER_SHUTDOWN:
            raise _ServerShutdown
        await self._on_parsed(parsed)

    async def _reader(self, ws: ClientConnection) -> None:
        async for raw in ws:
            await self._handle(raw)
        raise websockets.exceptions.ConnectionClosedOK(None, None)

    async def _open_replacement(self) -> tuple[ClientConnection, str | bytes]:
        await self._attempts.acquire()
        ws = await websockets.connect(
            self.url,
            open_timeout=self._open_timeout,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=2,
            max_size=16 * 1024 * 1024,
            max_queue=1024,
        )
        subscribed_backup = set(self.subscribed)
        self.subscribed = set()
        try:
            await self._sync_subscriptions(ws)
            deadline = time.monotonic() + self.stale_after_s
            while True:
                raw = await asyncio.wait_for(
                    ws.recv(), timeout=max(0.1, deadline - time.monotonic())
                )
                if b'"stream"' in (raw if isinstance(raw, bytes) else raw.encode()):
                    return ws, raw
        except BaseException:
            self.subscribed = subscribed_backup
            with contextlib.suppress(Exception):
                await ws.close()
            raise

    async def _session(self, ws: ClientConnection) -> None:
        self._ws = ws
        self.connected = True
        self.connected_at = time.monotonic()
        self.last_message_at = time.monotonic()
        self.subscribed = set()
        await self._sync_subscriptions(ws)
        await self._notify(True, "bağlandı")
        reader = asyncio.create_task(self._reader(ws), name=f"ws-read:{self.name}")
        try:
            while not self._stopping:
                waiter = asyncio.create_task(self._changed.wait())
                done, _ = await asyncio.wait(
                    {reader, waiter}, timeout=1.0, return_when=asyncio.FIRST_COMPLETED
                )
                if waiter not in done:
                    waiter.cancel()
                if reader in done:
                    reader.result()  # hatayı yükselt
                if self._changed.is_set():
                    self._changed.clear()
                    await self._sync_subscriptions(ws)
                now = time.monotonic()
                if (
                    self.desired
                    and self.last_message_at
                    and now - self.last_message_at > self.stale_after_s
                ):
                    raise _Stale
                if self.connected_at and now - self.connected_at > self._max_lifetime:
                    # Kesintisiz yenileme: önce yenisi, sonra eskisi.
                    self.renewing = True
                    new_ws, first = await self._open_replacement()
                    reader.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await reader
                    with contextlib.suppress(Exception):
                        await ws.close()
                    ws = self._ws = new_ws
                    self.connected_at = time.monotonic()
                    self.renewing = False
                    await self._handle(first)
                    reader = asyncio.create_task(self._reader(ws), name=f"ws-read:{self.name}")
        finally:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await reader


class StreamManager:
    """Bir piyasanın akışlarını bağlantılara paylaştırır ve sağlığını izler."""

    def __init__(
        self,
        *,
        market: Market,
        endpoints: MarketEndpoints,
        on_parsed: ParsedHandler,
        on_health: Callable[[bool, str], Awaitable[None]] | None = None,
        on_connection_state: StateHandler | None = None,
        streams_per_connection: int = 200,
        control_rate_per_s: float | None = None,
        stale_after_s: float = 30.0,
        attempt_limiter: ConnectionAttemptLimiter | None = None,
        connection_options: dict[str, Any] | None = None,
    ) -> None:
        if not 1 <= streams_per_connection <= 1024:
            raise ValueError("Bağlantı başına akış sayısı 1-1024 arasında olmalı")
        self.market = market
        self._endpoints = endpoints
        self._on_parsed = on_parsed
        self._on_health = on_health
        self._on_connection_state = on_connection_state
        self._per_conn = streams_per_connection
        # Spot 5/sn, Futures 10/sn; ping/pong payı bırakılır.
        self._control_rate = control_rate_per_s or (3.0 if market is Market.SPOT else 6.0)
        self._stale = stale_after_s
        self._attempts = attempt_limiter or ConnectionAttemptLimiter()
        self._options = connection_options or {}
        self._connections: dict[str, StreamConnection] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._assignment: dict[str, str] = {}  # akış -> bağlantı adı
        self._counter = itertools.count(1)
        self._healthy: bool | None = None
        self._running = False

    @property
    def connections(self) -> list[StreamConnection]:
        return list(self._connections.values())

    @property
    def stream_count(self) -> int:
        return len(self._assignment)

    def _new_connection(self, route: WsRoute) -> StreamConnection:
        name = f"{self.market.value}-{route.value}-{next(self._counter)}"
        conn = StreamConnection(
            name=name,
            url=self._endpoints.ws_url(route),
            route=route,
            market=self.market,
            on_parsed=self._on_parsed,
            on_state=self._handle_state,
            attempt_limiter=self._attempts,
            control_rate_per_s=self._control_rate,
            stale_after_s=self._stale,
            **self._options,
        )
        self._connections[name] = conn
        if self._running:
            self._start(conn)
        return conn

    async def _handle_state(self, conn: StreamConnection, connected: bool, reason: str) -> None:
        if self._on_connection_state is not None:
            await self._on_connection_state(conn, connected, reason)
        # Kopma, yoklama döngüsünü beklemeden hemen bildirilir (güvenli moda geçiş gecikmesin).
        await self._check_health()

    async def _check_health(self) -> None:
        healthy = self.healthy()
        if healthy != self._healthy:
            self._healthy = healthy
            if self._on_health is not None:
                await self._on_health(healthy, self.health_detail())

    def _start(self, conn: StreamConnection) -> None:
        self._tasks[conn.name] = asyncio.create_task(conn.run(), name=f"ws:{conn.name}")

    def set_streams(self, streams: Iterable[str]) -> None:
        desired = set(streams)
        # Kaldırılanlar
        for stream in [s for s in self._assignment if s not in desired]:
            del self._assignment[stream]
        # Bağlantı başına mevcut atamalar
        members: dict[str, set[str]] = {name: set() for name in self._connections}
        for stream, name in self._assignment.items():
            members[name].add(stream)
        # Yeni akışları rota bazında boş yeri olan bağlantılara yerleştir
        for stream in sorted(desired - set(self._assignment)):
            route = self._endpoints.route_for(stream)
            target = next(
                (
                    c
                    for c in self._connections.values()
                    if c.route is route and len(members[c.name]) < self._per_conn
                ),
                None,
            )
            if target is None:
                target = self._new_connection(route)
                members[target.name] = set()
            members[target.name].add(stream)
            self._assignment[stream] = target.name
        for name, conn in list(self._connections.items()):
            streams_for_conn = members.get(name, set())
            if not streams_for_conn:
                self._retire(name)
            else:
                conn.update(streams_for_conn)

    def _retire(self, name: str) -> None:
        conn = self._connections.pop(name)
        task = self._tasks.pop(name, None)
        if task is not None:
            conn._stopping = True
            task.cancel()

    def healthy(self) -> bool:
        if not self._connections:
            return False
        now = time.monotonic()
        return all(c.healthy(now) for c in self._connections.values())

    def health_detail(self) -> str:
        now = time.monotonic()
        bad = [c.name for c in self._connections.values() if not c.healthy(now)]
        if not self._connections:
            return "akış yok"
        if bad:
            return "sağlıksız bağlantılar: " + ", ".join(bad)
        return f"{len(self._connections)} bağlantı, {self.stream_count} akış"

    async def run(self) -> None:
        self._running = True
        for conn in self._connections.values():
            if conn.name not in self._tasks:
                self._start(conn)
        try:
            while True:
                await asyncio.sleep(0.5)
                for name, task in list(self._tasks.items()):
                    if task.done() and name in self._connections:
                        exc = task.exception() if not task.cancelled() else None
                        logger.error(
                            "Akış bağlantısı görevi bitti",
                            extra={"connection": name, "error": repr(exc)},
                        )
                        self._start(self._connections[name])
                await self._check_health()
        finally:
            self._running = False
            for conn in self._connections.values():
                await conn.stop()
            for task in self._tasks.values():
                task.cancel()
            for task in self._tasks.values():
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            self._tasks.clear()

    def status(self) -> list[ConnectionStatus]:
        return [c.status() for c in self._connections.values()]
