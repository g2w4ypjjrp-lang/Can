"""WebSocket bağlantı yöneticisi: abonelik, yeniden bağlanma, sunucu kapanışı, ölü bağlantı,
kesintisiz 24 saat yenilemesi ve akışların bağlantılara paylaştırılması."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
from collections.abc import AsyncIterator, Callable

import pytest

from ati_engine.config import BinanceEndpoints
from ati_engine.core.models import Market
from ati_engine.exchange.endpoints import WsRoute, endpoints_for
from ati_engine.market.parsing import ParsedMessage, StreamKind
from ati_engine.market.streams import ConnectionAttemptLimiter, StreamConnection, StreamManager
from fake_binance import FakeBinance


@pytest.fixture
async def fake() -> AsyncIterator[FakeBinance]:
    server = await FakeBinance().start()
    yield server
    await server.stop()


async def wait_until(predicate: Callable[[], bool], within: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + within
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("koşul zamanında sağlanmadı")
        await asyncio.sleep(0.02)


class Sink:
    def __init__(self) -> None:
        self.messages: list[ParsedMessage] = []
        self.states: list[tuple[str, bool, str]] = []

    async def on_parsed(self, parsed: ParsedMessage) -> None:
        self.messages.append(parsed)

    async def on_state(self, conn: StreamConnection, connected: bool, reason: str) -> None:
        self.states.append((conn.name, connected, reason))

    def kinds(self) -> set[StreamKind]:
        return {m.kind for m in self.messages}


def make_connection(
    fake: FakeBinance, sink: Sink, *, path: str = "/stream", **kwargs: object
) -> StreamConnection:
    options: dict[str, object] = {
        "control_rate_per_s": 50.0,
        "stale_after_s": 2.0,
        "backoff_initial_s": 0.05,
        "backoff_max_s": 0.2,
    }
    options.update(kwargs)
    return StreamConnection(
        name="test-1",
        url=f"{fake.ws_base}{path}",
        route=WsRoute.DEFAULT,
        market=Market.SPOT,
        on_parsed=sink.on_parsed,
        on_state=sink.on_state,
        **options,  # type: ignore[arg-type]
    )


@contextlib.asynccontextmanager
async def running(conn: StreamConnection) -> AsyncIterator[asyncio.Task[None]]:
    task = asyncio.create_task(conn.run())
    try:
        yield task
    finally:
        await conn.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_subscribes_and_receives(fake: FakeBinance) -> None:
    sink = Sink()
    conn = make_connection(fake, sink)
    conn.update(["btcusdt@aggTrade", "btcusdt@kline_1m", "!miniTicker@arr"])
    async with running(conn):
        await wait_until(
            lambda: (
                {StreamKind.AGG_TRADE, StreamKind.KLINE, StreamKind.MINI_TICKER_ARR} <= sink.kinds()
            )
        )
        assert conn.connected
        assert conn.healthy()
        assert fake.subscriptions() == conn.desired
    assert sink.states[0][1] is True


async def test_subscription_messages_are_batched_and_rate_limited(fake: FakeBinance) -> None:
    sink = Sink()
    conn = make_connection(fake, sink, control_rate_per_s=10.0, batch_size=4)
    streams = [f"sym{i}usdt@kline_1m" for i in range(10)]
    conn.update(streams)
    async with running(conn):
        await wait_until(lambda: fake.subscriptions() == set(streams))
    subs = [entry for entry in fake.control_log if entry[2] == "SUBSCRIBE"]
    assert [len(entry[3]) for entry in subs] == [4, 4, 2]
    gaps = [b[0] - a[0] for a, b in itertools.pairwise(subs)]
    assert all(gap >= 0.09 for gap in gaps)  # saniyede en fazla 10 kontrol mesajı


async def test_dynamic_update_sends_only_the_difference(fake: FakeBinance) -> None:
    sink = Sink()
    conn = make_connection(fake, sink)
    conn.update(["a@kline_1m", "b@kline_1m"])
    async with running(conn):
        await wait_until(lambda: fake.subscriptions() == {"a@kline_1m", "b@kline_1m"})
        conn.update(["b@kline_1m", "c@kline_1m"])
        await wait_until(lambda: fake.subscriptions() == {"b@kline_1m", "c@kline_1m"})
    methods = [(m, p) for _, _, m, p in fake.control_log]
    assert ("UNSUBSCRIBE", ["a@kline_1m"]) in methods
    assert ("SUBSCRIBE", ["c@kline_1m"]) in methods


async def test_reconnects_and_resubscribes_after_drop(fake: FakeBinance) -> None:
    sink = Sink()
    conn = make_connection(fake, sink)
    conn.update(["btcusdt@aggTrade"])
    async with running(conn):
        await wait_until(lambda: len(sink.messages) > 3)
        await fake.drop_all()
        await wait_until(lambda: conn.reconnects >= 1 and conn.connected)
        before = len(sink.messages)
        await wait_until(lambda: len(sink.messages) > before + 3)
        assert fake.subscriptions() == {"btcusdt@aggTrade"}
        assert conn.last_error is not None
    assert [s[1] for s in sink.states[:3]] == [True, False, True]


async def test_server_shutdown_triggers_immediate_reconnect(fake: FakeBinance) -> None:
    sink = Sink()
    conn = make_connection(fake, sink, backoff_initial_s=5.0, backoff_max_s=5.0)
    conn.update(["btcusdt@kline_1m"])
    async with running(conn):
        await wait_until(lambda: conn.connected and fake.connections_opened == 1)
        await fake.server_shutdown()
        # Geri çekilme 5 sn olmasına rağmen beklemeden yeniden bağlanmalı.
        await wait_until(lambda: fake.connections_opened == 2 and conn.connected, within=2.0)
        assert "serverShutdown" in (conn.last_error or "")


async def test_stale_connection_is_detected_and_replaced(fake: FakeBinance) -> None:
    sink = Sink()
    conn = make_connection(fake, sink, stale_after_s=0.5)
    conn.update(["btcusdt@kline_1m"])
    async with running(conn):
        await wait_until(lambda: conn.connected and len(sink.messages) > 2)
        fake.paused = True
        await wait_until(lambda: not conn.healthy(), within=3.0)
        await wait_until(lambda: conn.reconnects >= 1, within=3.0)
        assert "veri gelmedi" in (conn.last_error or "")
        fake.paused = False
        await wait_until(conn.healthy, within=3.0)


async def test_lifetime_renewal_is_seamless(fake: FakeBinance) -> None:
    sink = Sink()
    conn = make_connection(fake, sink, max_lifetime_s=0.5, check_interval_s=0.05)
    conn.update(["btcusdt@aggTrade"])
    health: list[bool] = []

    async def sample() -> None:
        while True:
            health.append(conn.healthy())
            await asyncio.sleep(0.02)

    async with running(conn):
        await wait_until(conn.healthy)
        sampler = asyncio.create_task(sample())
        try:
            # Sabit süre değil koşul beklenir: yavaş CI makinelerinde de kararlı.
            await wait_until(lambda: fake.connections_opened >= 3, within=15)
            await wait_until(lambda: len(fake.clients) == 1, within=5)
        finally:
            sampler.cancel()
        assert conn.reconnects == 0  # planlı yenileme kopma sayılmaz
        assert health
        assert all(health)  # yenileme sırasında sağlık hiç bozulmadı
        assert [s for s in sink.states if not s[1]] == []  # yenileme kopma bildirmedi


# --- Akışların bağlantılara paylaştırılması ----------------------------------------------------


def manager(market: Market, per_conn: int = 3) -> StreamManager:
    async def noop(_: ParsedMessage) -> None:
        return None

    return StreamManager(
        market=market,
        endpoints=endpoints_for(market, BinanceEndpoints()),
        on_parsed=noop,
        streams_per_connection=per_conn,
    )


def test_streams_are_sharded_across_connections() -> None:
    mgr = manager(Market.SPOT, per_conn=3)
    mgr.set_streams([f"s{i}@kline_1m" for i in range(7)])
    sizes = sorted(len(c.desired) for c in mgr.connections)
    assert sizes == [1, 3, 3]
    assert mgr.stream_count == 7
    # Kaldırma yalnızca ilgili bağlantıyı etkiler; boşalan bağlantı kapatılır.
    mgr.set_streams([f"s{i}@kline_1m" for i in range(3)])
    assert [len(c.desired) for c in mgr.connections] == [3]


def test_existing_assignments_are_stable() -> None:
    mgr = manager(Market.SPOT, per_conn=3)
    mgr.set_streams(["a@kline_1m", "b@kline_1m", "c@kline_1m"])
    first = mgr.connections[0]
    mgr.set_streams(["a@kline_1m", "b@kline_1m", "c@kline_1m", "d@kline_1m"])
    assert mgr.connections[0] is first
    assert first.desired == {"a@kline_1m", "b@kline_1m", "c@kline_1m"}


def test_futures_streams_are_routed_by_type() -> None:
    mgr = manager(Market.USDM_FUTURES, per_conn=200)
    mgr.set_streams(["btcusdt@aggTrade", "!ticker@arr", "btcusdt@depth@100ms", "!bookTicker"])
    routes = {c.route: c.desired for c in mgr.connections}
    assert routes[WsRoute.PUBLIC] == {"btcusdt@depth@100ms", "!bookTicker"}
    assert routes[WsRoute.MARKET] == {"btcusdt@aggTrade", "!ticker@arr"}
    urls = {c.route: c.url for c in mgr.connections}
    assert urls[WsRoute.PUBLIC] == "wss://fstream.binance.com/public/stream"
    assert urls[WsRoute.MARKET] == "wss://fstream.binance.com/market/stream"


def test_invalid_capacity_rejected() -> None:
    with pytest.raises(ValueError, match="1-1024"):
        manager(Market.SPOT, per_conn=2000)


async def test_attempt_limiter_enforces_window() -> None:
    limiter = ConnectionAttemptLimiter(max_attempts=2, window_s=0.3)
    loop = asyncio.get_running_loop()
    start = loop.time()
    for _ in range(3):
        await limiter.acquire()
    assert loop.time() - start >= 0.28


async def test_manager_reports_health(fake: FakeBinance) -> None:
    changes: list[bool] = []

    async def on_health(healthy: bool, detail: str) -> None:
        changes.append(healthy)

    async def noop(_: ParsedMessage) -> None:
        return None

    endpoints = endpoints_for(Market.SPOT, BinanceEndpoints(spot_market_data_ws=fake.ws_base))
    mgr = StreamManager(
        market=Market.SPOT,
        endpoints=endpoints,
        on_parsed=noop,
        on_health=on_health,
        streams_per_connection=2,
        stale_after_s=2.0,
        connection_options={"backoff_initial_s": 0.05, "backoff_max_s": 0.1},
    )
    mgr.set_streams(["a@kline_1m", "b@kline_1m", "c@kline_1m"])
    task = asyncio.create_task(mgr.run())
    try:
        await wait_until(lambda: changes[-1:] == [True])
        assert len(mgr.connections) == 2
        await fake.drop_all()
        await wait_until(lambda: False in changes)
        await wait_until(lambda: changes[-1] is True)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
