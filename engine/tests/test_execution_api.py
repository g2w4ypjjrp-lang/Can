"""Aşama 10: yerel API üzerinden test ağı yürütmesi (gerçek motor + gerçek HTTP), sahte borsaya
karşı. Anahtar doğrulama/saklama, işlem modu kapısı, zorunlu stop, açma, izleme, kapatma,
mutabakat ve gizli bilginin hiçbir yanıtta/kayıtta görünmemesi."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from ati_engine.app import Engine
from ati_engine.config import BinanceEndpoints, EngineSettings, LocalApiSettings
from fake_exchange import FakeExchange

API_KEY = "TestAnahtar0123456789abcdef"
SECRET = "TestGizli0123456789abcdefXYZ"


@pytest.fixture
async def exchange() -> AsyncIterator[FakeExchange]:
    fake = await FakeExchange(api_key=API_KEY, secret=SECRET).start()
    fake.prices["BTCUSDT"] = Decimal(100)
    yield fake
    await fake.stop()


@pytest.fixture
async def client(tmp_path: Path, exchange: FakeExchange) -> AsyncIterator[httpx.AsyncClient]:
    settings = EngineSettings(
        data_dir=tmp_path / "data",
        log_to_console=False,
        api=LocalApiSettings(port=0),
        binance=BinanceEndpoints(
            spot_testnet_rest=exchange.rest_url,
            spot_testnet_ws_api=exchange.ws_api_url,
            futures_testnet_rest=exchange.rest_url,
            futures_testnet_ws_private=exchange.private_ws_url,
        ),
    )
    engine = Engine(settings)
    task = asyncio.create_task(engine.run())
    await asyncio.wait_for(engine.ready.wait(), timeout=10)
    assert engine.runtime is not None
    headers = {"Authorization": f"Bearer {engine.runtime.api_token}"}
    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{engine.bound_port}", headers=headers, timeout=20
    ) as http:
        yield http
    engine.runtime.request_shutdown()
    assert await asyncio.wait_for(task, timeout=15) == 0


TRADE = {
    "market": "usdm_futures",
    "symbol": "BTCUSDT",
    "direction": "long",
    "quantity": "2",
    "reference_price": "100",
    "stop_loss": "95",
    "take_profits": [{"price": "110", "fraction": "0.5"}, {"price": "120", "fraction": "0.5"}],
    "leverage": 2,
}


async def test_testnet_trading_through_local_api(
    client: httpx.AsyncClient, exchange: FakeExchange, tmp_path: Path
) -> None:
    status = (await client.get("/v1/execution/status")).json()
    assert status["live_locked"] is False and status["environment"] == "testnet"
    assert status["markets"]["usdm_futures"] == {
        "key_stored": False,
        "key_hint": None,
        "connected": False,
        "error": None,
    }

    bad = await client.post(
        "/v1/execution/testnet-key",
        json={"market": "usdm_futures", "api_key": API_KEY, "secret": "Yanlis0123456789abcdef"},
    )
    assert bad.status_code == 200
    assert bad.json()["verified"] is False and bad.json()["stored"] is False

    good = await client.post(
        "/v1/execution/testnet-key",
        json={"market": "usdm_futures", "api_key": API_KEY, "secret": SECRET},
    )
    body = good.json()
    assert body["verified"] and body["stored"] and body["key_hint"] == "…cdef"
    status = (await client.get("/v1/execution/status")).json()
    futures = status["markets"]["usdm_futures"]
    assert futures["connected"] and futures["last_reconcile"]["ok"]

    blocked = await client.post("/v1/execution/trades", json=TRADE)
    assert blocked.status_code == 409 and "Demo Trading değil" in blocked.json()["detail"]
    mode = await client.post("/v1/trading-mode", json={"mode": "testnet"})
    assert mode.status_code == 200

    no_stop = await client.post("/v1/execution/trades", json={**TRADE, "stop_loss": None})
    assert no_stop.status_code == 409 and "zorunlu" in no_stop.json()["detail"]
    wrong_stop = await client.post("/v1/execution/trades", json={**TRADE, "stop_loss": "101"})
    assert wrong_stop.status_code == 409 and "yanlış" in wrong_stop.json()["detail"]
    too_much = await client.post("/v1/execution/trades", json={**TRADE, "leverage": 20})
    assert too_much.status_code == 409 and "Kaldıraç" in too_much.json()["detail"]

    opened = await client.post("/v1/execution/trades", json=TRADE)
    assert opened.status_code == 200, opened.text
    trade = opened.json()
    assert trade["state"] == "open" and trade["filled_qty"] == "2"
    assert trade["protection_orders"] == 3

    positions = (await client.get("/v1/execution/positions")).json()
    assert [(p["symbol"], p["quantity"], p["protected"]) for p in positions] == [
        ("BTCUSDT", "2", True)
    ]
    orders = (await client.get("/v1/execution/orders")).json()
    assert sorted(o["purpose"] for o in orders) == ["stop_loss", "take_profit", "take_profit"]

    report = (await client.post("/v1/execution/reconcile?market=usdm_futures")).json()
    assert report["ok"] and report["issues"] == []

    closed = await client.post(
        "/v1/execution/close", json={"market": "usdm_futures", "symbol": "BTCUSDT"}
    )
    assert closed.json()["closed"] and closed.json()["status"] == "FILLED"
    await asyncio.sleep(0.2)
    assert (await client.get("/v1/execution/positions")).json() == []
    assert "BTCUSDT" not in exchange.futures_positions
    assert not [a for a in exchange.algo_orders.values() if a["algoStatus"] == "NEW"]

    risk = (await client.get("/v1/risk/status")).json()
    names = {c["name"] for c in risk["conditions"]}
    assert {
        "risk.daily_loss",
        "exchange.usdm_futures.stream",
        "exchange.usdm_futures.reconciled",
    } <= names
    assert risk["engine_state"] == "running" and risk["limits"]["max_leverage"] == 3
    assert risk["gate"]["approved"] == 1 and risk["gate"]["rejected"] == 3
    decisions = (await client.get("/v1/risk/decisions")).json()
    assert sorted(d["risk_verdict"] for d in decisions) == ["approved"] + ["rejected"] * 3
    rejected_codes = {r["code"] for d in decisions for r in d["risk_reasons"]}
    assert {"stop_required", "stop_side", "leverage"} <= rejected_codes
    events = (await client.get("/v1/risk/events")).json()
    assert {"gate.stop_required", "gate.stop_side", "gate.leverage"} <= {e["rule"] for e in events}
    auto = await client.post("/v1/autotrade", json={"enabled": True})
    assert auto.json()["enabled"] is True and auto.json()["environment"] == "testnet"
    assert auto.json()["replayed_opened"] == 0
    view = (await client.get("/v1/autotrade")).json()
    assert view["enabled"] is True
    checks = {c["key"]: c for c in view["checks"]}
    assert checks["mode"]["ok"] and checks["enabled"]["ok"]
    assert checks["keys.usdm_futures"]["ok"] and checks["keys.usdm_futures"]["page"] == "settings"
    assert view["ready"] is all(c["ok"] for c in view["checks"])

    audit = (await client.get("/v1/audit?limit=200")).text
    assert "execution.open" in audit and "execution.testnet_key" in audit
    assert SECRET not in audit and API_KEY not in audit
    raw_db = (tmp_path / "data").rglob("*.db")
    for path in raw_db:
        content = path.read_bytes()
        assert SECRET.encode() not in content and API_KEY.encode() not in content


async def test_live_key_and_live_mode_refused(client: httpx.AsyncClient) -> None:
    live = await client.post(
        "/v1/trading-mode",
        json={"mode": "live", "acknowledgement": "GERCEK PARA ILE ISLEM YAPILMASINI ONAYLIYORUM"},
    )
    assert live.status_code == 409
    checks = {c["name"]: c for c in live.json()["checks"]}
    assert not checks["live_key_connected"]["passed"]
    assert "para çekme yetkisi KAPALI" in checks["live_key_connected"]["message"]
    unknown = await client.post("/v1/execution/trades", json=TRADE)
    assert unknown.status_code == 409  # mod PAPER
    missing = await client.post("/v1/execution/connect?market=spot")
    assert missing.status_code == 409 and "anahtarı kayıtlı değil" in missing.json()["detail"]
