"""Aşama 10: API anahtarı saklama (yalnızca test ağı), anahtar doğrulama, canlı anahtar
yetki politikası ve gerçek hesap kilidi."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from ati_engine.core.models import Market, TradingMode
from ati_engine.exchange.rate_limit import WeightBudget
from ati_engine.exchange.rest import BinanceRestClient
from ati_engine.exchange.signing import HmacSigner
from ati_engine.execution.binance_venue import BinanceFuturesVenue, BinanceSpotVenue
from ati_engine.safety.trading_mode import LiveExecutionUnavailableCheck, LiveTradingLocked
from ati_engine.security.exchange_keys import (
    ExchangeKeyStore,
    LiveKeysLocked,
    check_live_key_policy,
    verify_key,
)
from ati_engine.security.vault import AesGcmCipher, SecretVault
from ati_engine.storage.database import Database
from fake_exchange import FakeExchange
from test_binance_venue import rest_client

KEY = "A" * 60 + "wxyz"
SECRET = "s" * 64


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[ExchangeKeyStore]:
    db = Database(tmp_path / "engine.db")
    await db.open()
    await db.migrate()
    yield ExchangeKeyStore(SecretVault(db, AesGcmCipher(AesGcmCipher.generate_key())))
    await db.close()


@pytest.fixture
async def exchange() -> AsyncIterator[FakeExchange]:
    fake = await FakeExchange().start()
    yield fake
    await fake.stop()


async def test_testnet_keys_are_stored_encrypted_and_hinted(store: ExchangeKeyStore) -> None:
    saved = await store.store("testnet", Market.USDM_FUTURES, KEY, SECRET)
    assert saved.api_key_hint == "…wxyz"
    loaded = await store.load("testnet", Market.USDM_FUTURES)
    assert loaded is not None and loaded[0] == KEY
    assert loaded[1].sign("a=1") == HmacSigner(SECRET).sign("a=1")
    assert "s" * 64 not in repr(loaded[1])
    info = await store.info("testnet", Market.USDM_FUTURES)
    assert info is not None and info.api_key_hint == "…wxyz"
    assert await store.load("testnet", Market.SPOT) is None
    assert await store.delete("testnet", Market.USDM_FUTURES)
    assert await store.load("testnet", Market.USDM_FUTURES) is None


async def test_live_keys_are_locked(store: ExchangeKeyStore) -> None:
    with pytest.raises(LiveKeysLocked, match="G1"):
        await store.store("live", Market.SPOT, KEY, SECRET)
    with pytest.raises(LiveKeysLocked):
        await store.load("live", Market.SPOT)
    with pytest.raises(ValueError, match="16-128"):
        await store.store("testnet", Market.SPOT, "kısa", SECRET)
    with pytest.raises(ValueError, match="testnet"):
        await store.store("baska", Market.SPOT, KEY, SECRET)  # type: ignore[arg-type]


async def test_verify_key_against_exchange(exchange: FakeExchange) -> None:
    good = rest_client(exchange)
    check = await verify_key(good, Market.SPOT)
    assert check.ok and check.can_trade is True
    assert (await verify_key(good, Market.USDM_FUTURES)).ok
    bad = rest_client(exchange, secret="yanlis")
    check = await verify_key(bad, Market.USDM_FUTURES)
    assert not check.ok and "reddetti" in check.message
    assert "demo.binance.com" in check.message  # nereden oluşturulacağı söylenir
    assert exchange.signature_failures == 1
    await good.close()
    await bad.close()


async def test_live_key_policy_rejects_withdrawal_permission(exchange: FakeExchange) -> None:
    rest = rest_client(exchange)
    verdict = await check_live_key_policy(rest, markets=[Market.SPOT, Market.USDM_FUTURES])
    assert verdict.accepted and verdict.warnings == ()
    exchange.restrictions["enableWithdrawals"] = True
    verdict = await check_live_key_policy(rest, markets=[Market.SPOT])
    assert not verdict.accepted
    assert [f.code for f in verdict.blocking] == ["withdrawals_enabled"]
    del exchange.restrictions["enableWithdrawals"]  # alan yoksa: açık kabul edilir
    assert not (await check_live_key_policy(rest, markets=[Market.SPOT])).accepted
    exchange.restrictions.update(enableWithdrawals=False, enableFutures=False, ipRestrict=False)
    verdict = await check_live_key_policy(rest, markets=[Market.USDM_FUTURES])
    assert [f.code for f in verdict.blocking] == ["futures_trading_disabled"]
    assert [f.code for f in verdict.warnings] == ["no_ip_restriction"]
    await rest.close()


async def test_live_mode_is_technically_impossible() -> None:
    result = await LiveExecutionUnavailableCheck().evaluate()
    assert not result.passed and "G1" in result.message and "G2" in result.message
    rest = BinanceRestClient(
        "https://testnet.binancefuture.com",
        budget=WeightBudget(100),
        api_key="k",
        signer=HmacSigner("s"),
    )
    for venue_cls in (BinanceSpotVenue, BinanceFuturesVenue):
        with pytest.raises(LiveTradingLocked):
            venue_cls(
                rest,
                mode=TradingMode.LIVE,
                api_key="k",
                signer=HmacSigner("s"),
                ws_url="wss://fstream.binancefuture.com/private",
            )
    await rest.close()


@pytest.mark.parametrize(
    ("rest_url", "ws_url"),
    [
        ("https://api.binance.com", "wss://ws-api.testnet.binance.vision/ws-api/v3"),
        ("https://fapi.binance.com", "wss://fstream.binancefuture.com/private"),
        ("https://testnet.binancefuture.com", "wss://fstream.binance.com/private"),
        ("https://testnet.binance.vision", "wss://ws-api.binance.com:443/ws-api/v3"),
    ],
)
async def test_testnet_mode_refuses_production_hosts(rest_url: str, ws_url: str) -> None:
    rest = BinanceRestClient(
        rest_url, budget=WeightBudget(100), api_key="k", signer=HmacSigner("s")
    )
    with pytest.raises(ValueError, match="gerçek Binance"):
        BinanceFuturesVenue(
            rest, mode=TradingMode.TESTNET, api_key="k", signer=HmacSigner("s"), ws_url=ws_url
        )
    await rest.close()


def test_testnet_defaults_are_binance_demo_trading() -> None:
    """Binance futures test ağını Demo Trading'e taşıdı; anahtarlar demo.binance.com'da
    oluşturulur. Varsayılan test adresleri Demo Trading'dir ve test modu kilidinden geçer."""
    from ati_engine.config import BinanceEndpoints

    b = BinanceEndpoints()
    assert b.futures_testnet_rest == "https://demo-fapi.binance.com"
    assert b.futures_testnet_ws_private == "wss://demo-fstream.binance.com/private"
    assert b.spot_testnet_rest == "https://demo-api.binance.com"
    assert b.spot_testnet_ws_api == "wss://demo-ws-api.binance.com/ws-api/v3"
    rest = BinanceRestClient(
        b.futures_testnet_rest, budget=WeightBudget(100), api_key="k", signer=HmacSigner("s")
    )
    BinanceFuturesVenue(
        rest,
        mode=TradingMode.TESTNET,
        api_key="k",
        signer=HmacSigner("s"),
        ws_url=b.futures_testnet_ws_private,
    )
    BinanceSpotVenue(
        rest,
        mode=TradingMode.TESTNET,
        api_key="k",
        signer=HmacSigner("s"),
        ws_url=b.spot_testnet_ws_api,
    )


async def test_futures_user_stream_falls_back_to_classic_path() -> None:
    """Akış sunucusu /private yolunu tanımıyorsa klasik /ws/<listenKey> yolu kullanılır ve
    sonraki bağlantılarda önce o denenir."""
    import websockets
    from websockets.asyncio.server import ServerConnection, serve
    from websockets.http11 import Request, Response

    paths: list[str] = []

    def only_classic(_conn: ServerConnection, request: Request) -> Response | None:
        paths.append(request.path)
        if request.path.startswith("/private/"):
            return _conn.respond(404, "yok\n")
        return None

    async def handler(ws: ServerConnection) -> None:
        await ws.wait_closed()

    async with serve(handler, "127.0.0.1", 0, process_request=only_classic) as server:
        port = server.sockets[0].getsockname()[1]
        rest = BinanceRestClient(
            "https://demo-fapi.binance.com",
            budget=WeightBudget(100),
            api_key="k",
            signer=HmacSigner("s"),
        )
        venue = BinanceFuturesVenue(
            rest,
            mode=TradingMode.TESTNET,
            api_key="k",
            signer=HmacSigner("s"),
            ws_url=f"ws://127.0.0.1:{port}/private",
        )
        ws = await venue._open_stream("anahtar1")
        await ws.close()
        assert paths == ["/private/ws/anahtar1", "/ws/anahtar1"]
        ws = await venue._open_stream("anahtar2")  # çalışan yol önce denenir
        await ws.close()
        assert paths[-1] == "/ws/anahtar2" and len(paths) == 3
        await rest.close()
    assert isinstance(websockets.__version__, str)
