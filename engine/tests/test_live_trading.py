"""Gerçek hesap modu (kullanıcı onayıyla, 2026-11-11): para çekme yetkili anahtarın reddi, ayrı
Demo / gerçek hesap servisleri, onay ifadesi ve bağlı anahtar olmadan gerçek moda geçilememesi,
gerçek modda işlemin gerçek hesap servisine gitmesi, motor yeniden başlayınca sanal moda dönüş.

Gerçek Binance yerine sahte borsa (yerel adres) kullanılır; gerçek moda yalnızca gerçek Binance
adresleri ve yerel test adresi kabul edilir."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from ati_engine.app import Engine
from ati_engine.config import BinanceEndpoints, EngineSettings, LocalApiSettings
from ati_engine.safety.trading_mode import LIVE_TRADING_ACK_PHRASE
from fake_exchange import FakeExchange

API_KEY = "GercekAnahtar0123456789abcdef"
SECRET = "GercekGizli0123456789abcdefXYZ"
TRADE = {
    "market": "usdm_futures",
    "symbol": "BTCUSDT",
    "direction": "long",
    "quantity": "0.5",
    "reference_price": "100",
    "stop_loss": "95",
    "take_profits": [{"price": "110", "fraction": "1"}],
    "leverage": 2,
    "reason": "gerçek hesap testi",
}


@pytest.fixture
async def exchange() -> AsyncIterator[FakeExchange]:
    fake = await FakeExchange(api_key=API_KEY, secret=SECRET).start()
    fake.prices["BTCUSDT"] = Decimal(100)
    yield fake
    await fake.stop()


def live_settings(tmp_path: Path, exchange: FakeExchange) -> EngineSettings:
    # Gerçek hesap adresleri sahte borsaya yönlendirilir; Demo adresleri kullanılmaz.
    return EngineSettings(
        data_dir=tmp_path / "data",
        log_to_console=False,
        api=LocalApiSettings(port=0),
        binance=BinanceEndpoints(
            spot_live_rest=exchange.rest_url,
            spot_live_ws_api=exchange.ws_api_url,
            futures_live_rest=exchange.rest_url,
            futures_live_ws_private=exchange.private_ws_url,
        ),
    )


async def start(settings: EngineSettings) -> tuple[Engine, asyncio.Task[Any], httpx.AsyncClient]:
    engine = Engine(settings)
    task = asyncio.create_task(engine.run())
    await asyncio.wait_for(engine.ready.wait(), timeout=15)
    assert engine.runtime is not None
    client = httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{engine.bound_port}",
        headers={"Authorization": f"Bearer {engine.runtime.api_token}"},
        timeout=20,
    )
    return engine, task, client


async def stop(engine: Engine, task: asyncio.Task[Any], client: httpx.AsyncClient) -> None:
    await client.aclose()
    assert engine.runtime is not None
    engine.runtime.request_shutdown()
    await asyncio.wait_for(task, timeout=15)


async def test_live_key_with_withdrawal_permission_is_rejected(
    tmp_path: Path, exchange: FakeExchange
) -> None:
    engine, task, http = await start(live_settings(tmp_path, exchange))
    exchange.restrictions["enableWithdrawals"] = True
    rejected = await http.post(
        "/v1/execution/live-key",
        json={"market": "usdm_futures", "api_key": API_KEY, "secret": SECRET},
    )
    body = rejected.json()
    assert body["verified"] is False and body["stored"] is False
    assert "PARA ÇEKME" in body["message"]
    status = (await http.get("/v1/execution/status", params={"environment": "live"})).json()
    assert status["markets"]["usdm_futures"]["key_stored"] is False
    audit = (await http.get("/v1/audit")).text
    assert "execution.live_key" in audit and API_KEY not in audit and SECRET not in audit

    exchange.restrictions.update(enableWithdrawals=False, enableFutures=False)
    no_trade = await http.post(
        "/v1/execution/live-key",
        json={"market": "usdm_futures", "api_key": API_KEY, "secret": SECRET},
    )
    assert no_trade.json()["stored"] is False and "Futures yetkisi" in no_trade.json()["message"]
    await stop(engine, task, http)


async def test_live_mode_end_to_end(tmp_path: Path, exchange: FakeExchange) -> None:
    settings = live_settings(tmp_path, exchange)
    engine, task, http = await start(settings)
    # Anahtar yokken onay ifadesi doğru olsa bile gerçek moda geçilmez.
    refused = await http.post(
        "/v1/trading-mode", json={"mode": "live", "acknowledgement": LIVE_TRADING_ACK_PHRASE}
    )
    assert refused.status_code == 409
    assert {c["name"] for c in refused.json()["checks"] if not c["passed"]} == {
        "live_key_connected"
    }

    saved = await http.post(
        "/v1/execution/live-key",
        json={"market": "usdm_futures", "api_key": API_KEY, "secret": SECRET},
    )
    assert saved.json()["stored"] is True, saved.text
    assert "Uyarı" not in saved.json()["message"]  # sahte borsada IP kısıtı var
    live_status = (await http.get("/v1/execution/status", params={"environment": "live"})).json()
    assert (
        live_status["environment"] == "live" and live_status["markets"]["usdm_futures"]["connected"]
    )
    demo_status = (await http.get("/v1/execution/status", params={"environment": "testnet"})).json()
    assert demo_status["markets"]["usdm_futures"]["key_stored"] is False  # Demo anahtarı ayrı

    # Onay ifadesi yanlışsa ya da eksikse reddedilir.
    wrong = await http.post("/v1/trading-mode", json={"mode": "live", "acknowledgement": "evet"})
    assert wrong.status_code == 409
    # Sanal moddayken işlem açılmaz.
    assert (await http.post("/v1/execution/trades", json=TRADE)).status_code == 409

    accepted = await http.post(
        "/v1/trading-mode", json={"mode": "live", "acknowledgement": LIVE_TRADING_ACK_PHRASE}
    )
    assert accepted.status_code == 200 and accepted.json()["mode"] == "live"
    status = (await http.get("/v1/execution/status")).json()
    assert status["environment"] == "live" and status["trading_mode"] == "live"
    opened = await http.post("/v1/execution/trades", json=TRADE)
    assert opened.status_code == 200, opened.text
    assert opened.json()["state"] == "open"
    assert exchange.futures_positions["BTCUSDT"][0] == Decimal("0.5")
    positions = (await http.get("/v1/execution/positions")).json()
    assert [p["symbol"] for p in positions] == ["BTCUSDT"]
    auto = (await http.get("/v1/autotrade")).json()
    assert auto["environment"] == "live" and "GERÇEK PARA" in auto["disclaimer"]
    # Açık gerçek pozisyon varken anahtar silinemez.
    blocked = await http.post("/v1/execution/live-key/delete", params={"market": "usdm_futures"})
    assert blocked.status_code == 409
    entries = (await http.get("/v1/audit?limit=200")).json()
    opens = [e for e in entries if e["action"] == "execution.open"]
    assert opens and opens[0]["details"]["mode"] == "live"
    assert any(e["action"] == "trading_mode.request" and e["details"]["accepted"]
               and e["details"]["to"] == "live" for e in entries)  # fmt: skip
    await stop(engine, task, http)

    # Yeniden açılışta motor sanal modda başlar; gerçek mod kendiliğinden geri gelmez.
    engine, task, http = await start(settings)
    mode = (await http.get("/v1/trading-mode")).json()
    assert mode["mode"] == "paper"
    await stop(engine, task, http)


async def test_kill_switch_blocks_live_mode(tmp_path: Path, exchange: FakeExchange) -> None:
    engine, task, http = await start(live_settings(tmp_path, exchange))
    await http.post(
        "/v1/execution/live-key",
        json={"market": "usdm_futures", "api_key": API_KEY, "secret": SECRET},
    )
    await http.post("/v1/kill-switch/engage", json={"reason": "test"})
    refused = await http.post(
        "/v1/trading-mode", json={"mode": "live", "acknowledgement": LIVE_TRADING_ACK_PHRASE}
    )
    assert refused.status_code == 409
    assert "kill_switch_released" in {
        c["name"] for c in refused.json()["checks"] if not c["passed"]
    }
    await stop(engine, task, http)
