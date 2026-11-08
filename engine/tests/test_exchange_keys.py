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
    assert not check.ok and "geçersiz" in check.message
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
