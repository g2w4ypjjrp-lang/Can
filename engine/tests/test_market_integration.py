"""Uçtan uca: motor + piyasa verisi servisi + sahte Binance (REST ve WebSocket).

"Beklenmeyen bağlantı kesintilerinde güvenli moda geçme" gereksinimi burada doğrulanır.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import websockets

from ati_engine.app import Engine
from ati_engine.config import BinanceEndpoints, EngineSettings, LocalApiSettings, MarketDataSettings
from ati_engine.core.models import EngineState, Market
from fake_binance import FakeBinance


async def wait_until(predicate: Callable[[], bool], within: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + within
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("koşul zamanında sağlanmadı")
        await asyncio.sleep(0.05)


@dataclass
class Stack:
    engine: Engine
    fake: FakeBinance
    base_url: str
    token: str

    @property
    def state(self) -> EngineState:
        assert self.engine.runtime is not None
        return self.engine.runtime.safety.state.state

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url, headers={"Authorization": f"Bearer {self.token}"}
        )


@pytest.fixture
async def stack(tmp_path: Path) -> AsyncIterator[Stack]:
    fake = await FakeBinance(interval_s=0.05).start()
    settings = EngineSettings(
        data_dir=tmp_path / "data",
        log_to_console=False,
        api=LocalApiSettings(port=0),
        binance=BinanceEndpoints(**fake.binance_endpoints()),
        market_data=MarketDataSettings(
            enabled=True,
            symbol_allowlist=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            focus_symbols=["BTCUSDT", "ETHUSDT"],
            stale_after_s=3,
            depth_snapshot_limit=100,
        ),
    )
    engine = Engine(settings)
    task = asyncio.create_task(engine.run())
    await asyncio.wait_for(engine.ready.wait(), timeout=10)
    assert engine.runtime is not None
    yield Stack(
        engine=engine,
        fake=fake,
        base_url=f"http://127.0.0.1:{engine.bound_port}",
        token=engine.runtime.api_token,
    )
    engine.runtime.request_shutdown()
    await asyncio.wait_for(task, timeout=15)
    await fake.stop()


async def test_engine_waits_for_market_data_then_runs(stack: Stack) -> None:
    await wait_until(lambda: stack.state is EngineState.RUNNING)
    runtime = stack.engine.runtime
    assert runtime is not None
    conditions = {c.name: c.ready for c in runtime.safety.conditions()}
    assert conditions == {"market_data.spot": True, "market_data.usdm_futures": True}
    subs = stack.fake.subscriptions()
    assert "!miniTicker@arr" in subs
    assert {"!ticker@arr", "!markPrice@arr@1s", "!forceOrder@arr"} <= subs
    assert {"btcusdt@kline_1m", "btcusdt@aggTrade", "btcusdt@depth@100ms"} <= subs
    assert "solusdt@depth@100ms" not in subs  # odakta değil
    assert not any(s.startswith("xauusdt") for s in subs)  # altın kontratı evrende yok


async def test_order_books_sync_and_market_api(stack: Stack) -> None:
    await wait_until(lambda: stack.state is EngineState.RUNNING)
    async with stack.client() as client:

        async def books_synced() -> bool:
            body = (await client.get("/v1/market/status")).json()
            return all(
                b["state"] == "synced" for m in body["markets"] for b in m["order_books"]
            ) and all(m["order_books"] for m in body["markets"])

        for _ in range(100):
            if await books_synced():
                break
            await asyncio.sleep(0.1)
        status = (await client.get("/v1/market/status")).json()
        assert status["enabled"] is True
        markets = {m["market"]: m for m in status["markets"]}
        assert set(markets) == {"spot", "usdm_futures"}
        spot = markets["spot"]
        assert spot["ready"] is True
        assert spot["tracked_symbols"] == 3
        assert {b["symbol"] for b in spot["order_books"]} == {"BTCUSDT", "ETHUSDT"}
        assert all(b["best_bid"] == 100.0 and b["best_ask"] == 101.0 for b in spot["order_books"])
        assert all(b["resyncs"] == 0 for m in markets.values() for b in m["order_books"])
        assert {c["route"] for c in markets["usdm_futures"]["connections"]} == {"market", "public"}
        assert spot["rest_budget"]["total_used"] > 0

        tickers = (
            await client.get("/v1/market/tickers", params={"market": "spot", "limit": 5})
        ).json()
        assert [t["symbol"] for t in tickers["tickers"]] == ["SOLUSDT", "ETHUSDT", "BTCUSDT"]
        futures = (await client.get("/v1/market/tickers", params={"market": "usdm_futures"})).json()
        btc = next(t for t in futures["tickers"] if t["symbol"] == "BTCUSDT")
        assert btc["funding_rate"] == pytest.approx(0.0001)

        focus = await client.post(
            "/v1/market/focus", json={"market": "spot", "symbols": ["solusdt", "YOKUSDT"]}
        )
        assert focus.json() == {"market": "spot", "focus": ["SOLUSDT"]}
        await wait_until(lambda: "solusdt@depth@100ms" in stack.fake.subscriptions())
        await wait_until(lambda: "btcusdt@depth@100ms" not in _spot_subs(stack.fake))


def _spot_subs(fake: FakeBinance) -> set[str]:
    return {s for c in fake.clients if c.path == "/stream" for s in c.streams}


async def test_disconnect_forces_safe_mode_and_recovers(stack: Stack) -> None:
    await wait_until(lambda: stack.state is EngineState.RUNNING)
    runtime = stack.engine.runtime
    assert runtime is not None
    seen: list[EngineState] = []
    from ati_engine.core.events import EngineStateChanged

    runtime.bus.subscribe(EngineStateChanged, lambda e: seen.append(e.current), name="t")
    await stack.fake.drop_all()
    await wait_until(lambda: EngineState.SAFE_MODE in seen)
    await wait_until(lambda: stack.state is EngineState.RUNNING)
    assert seen[:2] == [EngineState.SAFE_MODE, EngineState.RUNNING]


async def test_lost_trades_are_recovered_from_rest(stack: Stack) -> None:
    """Akışta kaybolan işlemler REST'ten geri alınır; sembol başına kimlikler kesintisiz olur."""
    await wait_until(lambda: stack.state is EngineState.RUNNING)
    runtime = stack.engine.runtime
    assert runtime is not None
    from ati_engine.market.events import AggTrade

    seen: dict[tuple[str, str], set[int]] = {}

    def record(event: AggTrade) -> None:
        seen.setdefault((event.market.value, event.symbol), set()).add(event.trade_id)

    runtime.bus.subscribe(AggTrade, record, name="t-trades")
    await wait_until(lambda: len(seen) >= 6)
    stack.fake.skip_trades = 7  # bir sonraki tikte her işlem akışında 7 mesaj "kaybolur"

    def recovered() -> int:
        return sum(s.gaps.stats.recovered_trades for s in runtime.market_data.values())

    await wait_until(lambda: recovered() >= 7 * 6)
    await asyncio.sleep(0.3)
    for ids in seen.values():
        assert ids == set(range(min(ids), max(ids) + 1))  # boşluk yok
    for service in runtime.market_data.values():
        assert service.gaps.stats.detected >= 3
        assert service.gaps.stats.unrecovered_trades == 0
    assert stack.fake.agg_trade_requests  # REST'ten istendi


async def test_silent_feed_forces_safe_mode(stack: Stack) -> None:
    await wait_until(lambda: stack.state is EngineState.RUNNING)
    stack.fake.paused = True
    await wait_until(lambda: stack.state is EngineState.SAFE_MODE, within=10)
    runtime = stack.engine.runtime
    assert runtime is not None
    assert not runtime.safety.state.can_open_positions()
    assert runtime.safety.state.can_manage_positions()
    stack.fake.paused = False
    await wait_until(lambda: stack.state is EngineState.RUNNING, within=15)


async def test_ui_stream_gets_system_events_only(stack: Stack) -> None:
    await wait_until(lambda: stack.state is EngineState.RUNNING)
    url = stack.base_url.replace("http://", "ws://") + "/v1/events"
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"type": "auth", "token": stack.token}))
        assert json.loads(await ws.recv())["type"] == "auth_ok"
        await stack.fake.drop_all()
        types: set[str] = set()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 5
        while loop.time() < deadline and "StreamConnectionChanged" not in types:
            types.add(json.loads(await asyncio.wait_for(ws.recv(), timeout=5))["type"])
    assert "StreamConnectionChanged" in types
    assert not types & {"AggTrade", "Kline", "TickerBatch", "DepthDiff", "OrderBookTop"}


async def test_unreachable_exchange_keeps_engine_safe(tmp_path: Path) -> None:
    """Binance'e hiç ulaşılamıyorsa motor güvenli modda kalır ve nedenini raporlar."""
    settings = EngineSettings(
        data_dir=tmp_path / "data",
        log_to_console=False,
        api=LocalApiSettings(port=0),
        markets=[Market.SPOT],
        binance=BinanceEndpoints(
            spot_market_data_rest="http://127.0.0.1:9", spot_market_data_ws="ws://127.0.0.1:9"
        ),
        market_data=MarketDataSettings(enabled=True),
    )
    engine = Engine(settings)
    task = asyncio.create_task(engine.run())
    await asyncio.wait_for(engine.ready.wait(), timeout=10)
    runtime = engine.runtime
    assert runtime is not None
    try:
        await wait_until(
            lambda: any(
                c.name == "market_data.spot" and "keşif başarısız" in c.detail
                for c in runtime.safety.conditions()
            )
        )
        assert runtime.safety.state.state is EngineState.SAFE_MODE
    finally:
        runtime.request_shutdown()
        await asyncio.wait_for(task, timeout=15)


async def test_discovery_failure_reason_replaces_initial_detail(tmp_path: Path) -> None:
    """Windows'ta görülen sıralamanın her platformda yeniden üretilmesi (CI regresyonu).

    REST yavaş başarısız olur (bağlantıyı kabul edip 1.5 sn sonra kapatır); bu sırada akış
    sağlığı kontrolü önce çalışır ve "semboller keşfediliyor" nedenini bildirir. Keşif sonradan
    başarısız olunca hazır olmama *nedeni* değişir ve bu değişiklik de bildirilmelidir.
    """

    async def hang_then_close(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read(1024)
        await asyncio.sleep(1.5)
        writer.close()

    server = await asyncio.start_server(hang_then_close, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    settings = EngineSettings(
        data_dir=tmp_path / "data",
        log_to_console=False,
        api=LocalApiSettings(port=0),
        markets=[Market.SPOT],
        binance=BinanceEndpoints(
            spot_market_data_rest=f"http://127.0.0.1:{port}", spot_market_data_ws="ws://127.0.0.1:9"
        ),
        market_data=MarketDataSettings(enabled=True),
    )
    engine = Engine(settings)
    task = asyncio.create_task(engine.run())
    await asyncio.wait_for(engine.ready.wait(), timeout=10)
    runtime = engine.runtime
    assert runtime is not None

    def detail() -> str:
        return next(
            (c.detail for c in runtime.safety.conditions() if c.name == "market_data.spot"), ""
        )

    try:
        await wait_until(lambda: "keşfediliyor" in detail())  # önce sağlık kontrolü bildirir
        await wait_until(lambda: "keşif başarısız" in detail())  # sonra neden güncellenir
        assert runtime.safety.state.state is EngineState.SAFE_MODE
    finally:
        runtime.request_shutdown()
        await asyncio.wait_for(task, timeout=15)
        server.close()
        await server.wait_closed()


async def test_scanner_api_with_warmup(stack: Stack) -> None:
    await wait_until(lambda: stack.state is EngineState.RUNNING)
    runtime = stack.engine.runtime
    assert runtime is not None
    scanner = runtime.scanner
    assert scanner is not None
    await wait_until(
        lambda: (
            scanner.warmup_done.get("spot") == 3 and scanner.warmup_done.get("usdm_futures") == 3
        )
    )
    assert stack.fake.kline_requests == 6
    # Isınmadan sonraki ilk turu bekle (tablo saniyede bir yenilenir).
    await wait_until(
        lambda: (
            len(scanner.rows) >= 6 and all(r.baseline_minutes >= 240 for r in scanner.rows.values())
        )
    )
    async with stack.client() as client:
        top = (
            await client.get(
                "/v1/scanner/top", params={"market": "spot", "sort": "quote_volume_60s"}
            )
        ).json()
        assert {r["symbol"] for r in top["rows"]} == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
        row = top["rows"][0]
        assert row["baseline_minutes"] >= 240  # REST ısınması (kapanmamış mum hariç)
        # 60 sn'lik akış verisi dolmadan hacim z-skoru hesaplanmaz (yanlış alarm önlemi).
        assert row["volume_z_60s"] is None
        assert top["stats"]["tick_ms_last"] < 50
        bad = await client.get("/v1/scanner/top", params={"sort": "yok"})
        assert bad.status_code == 422
        signals = await client.get("/v1/scanner/signals")
        assert signals.status_code == 200
        assert isinstance(signals.json(), list)


async def test_whale_radar_end_to_end(stack: Stack) -> None:
    """Gerçek akış yolundan enjekte edilen büyük emir ve tasfiye zinciri API'de görünür."""
    await wait_until(lambda: stack.state is EngineState.RUNNING)
    runtime = stack.engine.runtime
    assert runtime is not None
    radar = runtime.whales
    assert radar is not None
    await wait_until(lambda: "btcusdt@aggTrade" in stack.fake.subscriptions())
    now = time.time_ns() // 1_000_000
    # Akışın sıradaki işlem kimliği: boşluk doldurucu sahte bir "kayıp" görmesin.
    stack.fake._trade_ids["s:BTCUSDT"] += 1
    trade_id = stack.fake._trade_ids["s:BTCUSDT"]
    big = {
        "e": "aggTrade",
        "E": now,
        "s": "BTCUSDT",
        "a": trade_id,
        "p": "100.0",
        "q": "20000",
        "f": 1,
        "l": 1,
        "T": now,
        "m": False,
    }
    assert await stack.fake.inject("btcusdt@aggTrade", big) == 1
    for i in range(3):
        liquidation = {
            "e": "forceOrder",
            "E": now + i,
            "o": {
                "s": "ETHUSDT",
                "S": "SELL",
                "o": "LIMIT",
                "f": "IOC",
                "q": "200",
                "p": "2000",
                "ap": "2000",
                "X": "FILLED",
                "l": "200",
                "z": "200",
                "T": now + i,
            },
        }
        assert await stack.fake.inject("!forceOrder@arr", liquidation, futures=True) == 1
    await wait_until(
        lambda: any(t.symbol == "BTCUSDT" and t.notional >= 2_000_000 for t in radar.trades)
    )
    await wait_until(lambda: any(a.kind.value == "liquidation_cascade" for a in radar.alerts))
    async with stack.client() as client:
        trades = (
            await client.get("/v1/whales/trades", params={"market": "spot", "symbol": "btcusdt"})
        ).json()
        # Sahte sunucunun arka plan işlemi (alış, 50 $) aynı milisaniyeye düşerse radar onu
        # doğru şekilde aynı süpürmeye katar (Windows'ta saat çözünürlüğü ~15 ms).
        assert 2_000_000 <= trades[0]["notional"] < 2_000_000 + 1_000
        assert trades[0]["side"] == "buy"
        alerts = (await client.get("/v1/whales/alerts")).json()
        kinds = {a["kind"] for a in alerts}
        assert {"mega_trade", "liquidation_cascade"} <= kinds
        summary = (await client.get("/v1/whales/summary", params={"market": "spot"})).json()
        assert summary["rows"][0]["symbol"] == "BTCUSDT"
        assert summary["stats"]["liquidations_5m"]["long"] == pytest.approx(1_200_000)
        assert (await client.get("/v1/whales/impact")).status_code == 200
        assert (await client.get("/v1/whales/positioning")).status_code == 200
