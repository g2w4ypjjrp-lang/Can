"""İmzalama, ağırlık bütçesi ve REST istemcisi testleri."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qsl, unquote

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from ati_engine.core.clock import ManualClock
from ati_engine.exchange.rate_limit import (
    IpBannedError,
    Priority,
    RateLimitError,
    WeightBudget,
    parse_rate_limits,
    request_weight_per_minute,
)
from ati_engine.exchange.rest import BinanceApiError, BinanceRestClient
from ati_engine.exchange.signing import Ed25519Signer, HmacSigner, build_query, signed_query

FIXTURES = Path(__file__).parent / "fixtures" / "binance"

# Binance Spot API belgelerindeki yayımlanmış ÖRNEK anahtar (gerçek bir hesaba ait değildir).
DOC_SECRET = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
DOC_PARAMS = {
    "symbol": "LTCBTC",
    "side": "BUY",
    "type": "LIMIT",
    "timeInForce": "GTC",
    "quantity": 1,
    "price": "0.1",
    "recvWindow": 5000,
    "timestamp": 1499827319559,
}


# --- İmzalama -------------------------------------------------------------------------------


def test_hmac_matches_binance_doc_example() -> None:
    payload = build_query(DOC_PARAMS)
    assert payload == (
        "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1"
        "&recvWindow=5000&timestamp=1499827319559"
    )
    assert (
        HmacSigner(DOC_SECRET).sign(payload)
        == "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"
    )


def test_non_ascii_is_percent_encoded_before_signing() -> None:
    payload = build_query({**DOC_PARAMS, "symbol": "１２３４５６"})
    assert payload.startswith("symbol=%EF%BC%91%EF%BC%92%EF%BC%93%EF%BC%94%EF%BC%95%EF%BC%96&")
    assert (
        HmacSigner(DOC_SECRET).sign(payload)
        == "e1353ec6b14d888f1164ae9af8228a3dbd508bc82eb867db8ab6046442f33ef3"
    )


def test_build_query_formats_values() -> None:
    query = build_query(
        {"price": Decimal("0.10000"), "skip": None, "flag": True, "qty": Decimal("1E+1")}
    )
    assert query == "price=0.1&flag=true&qty=10"


def test_ed25519_signature_verifies_and_is_url_safe() -> None:
    key = Ed25519PrivateKey.generate()
    signer = Ed25519Signer(key)
    payload = build_query(DOC_PARAMS)
    signature = signer.sign(payload)
    key.public_key().verify(base64.b64decode(signature), payload.encode())
    query = signed_query(DOC_PARAMS, signer)
    raw_sig = query.split("&signature=")[1]
    assert "+" not in raw_sig and "/" not in raw_sig and "=" not in raw_sig
    assert unquote(raw_sig) == signature


def test_ed25519_from_pem_rejects_other_key_types() -> None:
    ed_pem = Ed25519PrivateKey.generate().private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    )
    assert Ed25519Signer.from_pem(ed_pem).kind == "ed25519"
    ec_pem = generate_private_key(SECP256R1()).private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    )
    with pytest.raises(ValueError, match="Ed25519"):
        Ed25519Signer.from_pem(ec_pem)


def test_signers_never_reveal_secrets() -> None:
    assert DOC_SECRET not in repr(HmacSigner(DOC_SECRET))
    assert "***" in repr(Ed25519Signer(Ed25519PrivateKey.generate()))


# --- Ağırlık bütçesi ------------------------------------------------------------------------


def test_rate_limits_are_read_from_exchange_info() -> None:
    spot = json.loads((FIXTURES / "spot_exchange_info.json").read_text())
    futures = json.loads((FIXTURES / "futures_exchange_info.json").read_text())
    assert request_weight_per_minute(parse_rate_limits(spot["rateLimits"])) == 6000
    assert request_weight_per_minute(parse_rate_limits(futures["rateLimits"])) == 2400
    rules = parse_rate_limits(futures["rateLimits"])
    assert any(r.kind == "ORDERS" and r.interval_ms == 10_000 for r in rules)


def test_priority_thresholds() -> None:
    clock = ManualClock(start_ms=0)
    budget = WeightBudget(1000, clock=clock)
    budget.update_from_headers({"x-mbx-used-weight-1m": "590"})
    assert budget.delay_for(20, Priority.LOW) > 0  # %60 eşiği aşılıyor
    assert budget.delay_for(20, Priority.NORMAL) == 0
    budget.update_from_headers({"x-mbx-used-weight-1m": "940"})
    assert budget.delay_for(20, Priority.NORMAL) > 0
    assert budget.delay_for(10, Priority.HIGH) == 0


def test_window_resets_each_minute() -> None:
    clock = ManualClock(start_ms=120_000)
    budget = WeightBudget(1000, clock=clock)
    budget.update_from_headers({"x-mbx-used-weight-1m": "900"})
    assert budget.used == 900
    clock.advance(60_000)
    assert budget.used == 0


def test_server_reported_weight_is_respected() -> None:
    budget = WeightBudget(6000, clock=ManualClock(start_ms=0))
    budget.update_from_headers({"X-MBX-USED-WEIGHT-1M": "4800"})
    assert budget.used == 4800
    budget.update_from_headers({"x-mbx-used-weight-1m": "100"})  # daha düşük değer yok sayılır
    assert budget.used == 4800
    budget.update_from_headers({"x-mbx-used-weight-1m": "çöp"})
    assert budget.used == 4800


async def test_acquire_waits_for_next_window_without_real_sleep() -> None:
    clock = ManualClock(start_ms=30_000)
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.advance(int(seconds * 1000))

    budget = WeightBudget(100, clock=clock, sleep=fake_sleep)
    await budget.acquire(70, Priority.NORMAL)  # %80 = 80'e kadar serbest
    await budget.acquire(20, Priority.NORMAL)  # 90 > 80 -> sonraki dakikayı bekler
    assert sleeps == [30.0]
    assert budget.used == 20
    assert budget.waits == 1
    assert budget.total_used == 90


async def test_rate_limited_and_banned_states() -> None:
    clock = ManualClock(start_ms=0)
    budget = WeightBudget(1000, clock=clock)
    budget.on_rate_limited(7)
    assert budget.delay_for(1, Priority.HIGH) == pytest.approx(7.0)
    budget.on_banned(120)
    with pytest.raises(IpBannedError) as info:
        await budget.acquire(1, Priority.HIGH)
    assert info.value.retry_after_s == pytest.approx(120.0)
    clock.advance(121_000)
    await budget.acquire(1, Priority.HIGH)


async def test_acquire_rejects_invalid_weights() -> None:
    budget = WeightBudget(100)
    with pytest.raises(ValueError, match="pozitif"):
        await budget.acquire(0)
    with pytest.raises(ValueError, match="aşıyor"):
        await budget.acquire(99)


# --- REST istemcisi -------------------------------------------------------------------------


class _Recorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        weight_header = {"X-MBX-USED-WEIGHT-1M": "42"}
        if path == "/api/v3/depth":
            return httpx.Response(
                200, json={"lastUpdateId": 1, "bids": [], "asks": []}, headers=weight_header
            )
        if path == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": 1_700_000_001_000})
        if path == "/bad":
            return httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})
        if path == "/limited":
            return httpx.Response(
                429, json={"code": -1003, "msg": "Too many requests"}, headers={"Retry-After": "7"}
            )
        if path == "/banned":
            return httpx.Response(418, headers={"Retry-After": "120"})
        if path == "/api/v3/account":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, text="yok")


def _client(recorder: _Recorder, **kwargs: object) -> BinanceRestClient:
    return BinanceRestClient(
        "https://example.test",
        budget=WeightBudget(6000),
        client=httpx.AsyncClient(transport=httpx.MockTransport(recorder)),
        **kwargs,  # type: ignore[arg-type]
    )


async def test_rest_success_updates_budget() -> None:
    recorder = _Recorder()
    client = _client(recorder)
    body = await client.get("/api/v3/depth", params={"symbol": "BTCUSDT", "limit": 5}, weight=5)
    assert body["lastUpdateId"] == 1
    assert recorder.requests[0].url.query == b"symbol=BTCUSDT&limit=5"
    assert client.budget.used == 42


async def test_rest_error_mapping() -> None:
    client = _client(_Recorder())
    with pytest.raises(BinanceApiError) as info:
        await client.get("/bad", weight=1)
    assert info.value.code == -1121
    assert info.value.status == 400
    assert "Invalid symbol" in str(info.value)


async def test_rest_429_blocks_budget() -> None:
    client = _client(_Recorder())
    with pytest.raises(RateLimitError) as info:
        await client.get("/limited", weight=1)
    assert info.value.retry_after_s == 7
    assert client.budget.snapshot()["blocked_for_s"] > 6


async def test_rest_418_stops_all_requests() -> None:
    recorder = _Recorder()
    client = _client(recorder)
    with pytest.raises(IpBannedError):
        await client.get("/banned", weight=1)
    with pytest.raises(IpBannedError):
        await client.get("/api/v3/depth", weight=1)
    assert len(recorder.requests) == 1  # yasak sürerken Binance'e istek gitmez


async def test_signed_request_contains_valid_signature() -> None:
    recorder = _Recorder()
    clock = ManualClock(start_ms=1_700_000_000_000)
    client = _client(recorder, api_key="test-api-key", signer=HmacSigner("gizli"), clock=clock)
    await client.request(
        "GET", "/api/v3/account", params={"omitZeroBalances": True}, weight=20, signed=True
    )
    request = recorder.requests[0]
    assert request.headers["X-MBX-APIKEY"] == "test-api-key"
    query = request.url.query.decode()
    payload, _, signature = query.rpartition("&signature=")
    params = dict(parse_qsl(payload))
    assert params["timestamp"] == "1700000000000"
    assert params["recvWindow"] == "5000"
    expected = hmac.new(b"gizli", payload.encode(), hashlib.sha256).hexdigest()
    assert signature == expected


async def test_signed_request_requires_credentials() -> None:
    client = _client(_Recorder())
    with pytest.raises(RuntimeError, match="API anahtarı"):
        await client.request("GET", "/api/v3/account", weight=20, signed=True)


async def test_time_sync_offset() -> None:
    clock = ManualClock(start_ms=1_700_000_000_000)
    client = _client(_Recorder(), clock=clock)
    offset = await client.sync_time("/api/v3/time")
    assert 900 <= offset <= 1000
    assert client.time_offset_ms == offset
