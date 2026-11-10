"""Yerel API'nin uçtan uca testleri: gerçek motor, gerçek uvicorn sunucusu, gerçek HTTP/WS."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import websockets

from ati_engine.app import Engine
from ati_engine.config import EngineSettings, LocalApiSettings
from ati_engine.core.models import EngineState
from ati_engine.safety.kill_switch import RELEASE_CONFIRMATION
from ati_engine.safety.trading_mode import LIVE_TRADING_ACK_PHRASE


@dataclass
class RunningEngine:
    engine: Engine
    base_url: str
    ws_url: str
    token: str

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


@pytest.fixture
async def running(tmp_path: Path) -> AsyncIterator[RunningEngine]:
    settings = EngineSettings(
        data_dir=tmp_path / "data",
        log_to_console=False,
        heartbeat_interval_s=0.05,
        api=LocalApiSettings(port=0),
    )
    engine = Engine(settings)
    task = asyncio.create_task(engine.run())
    await asyncio.wait_for(engine.ready.wait(), timeout=10)
    assert engine.runtime is not None and engine.bound_port
    port = engine.bound_port
    yield RunningEngine(
        engine=engine,
        base_url=f"http://127.0.0.1:{port}",
        ws_url=f"ws://127.0.0.1:{port}/v1/events",
        token=engine.runtime.api_token,
    )
    engine.runtime.request_shutdown()
    assert await asyncio.wait_for(task, timeout=10) == 0


async def test_health_needs_no_token(running: RunningEngine) -> None:
    async with httpx.AsyncClient(base_url=running.base_url) as client:
        response = await client.get("/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_status_requires_valid_token(running: RunningEngine) -> None:
    async with httpx.AsyncClient(base_url=running.base_url) as client:
        assert (await client.get("/v1/status")).status_code == 401
        bad = await client.get("/v1/status", headers={"Authorization": "Bearer yanlis"})
        assert bad.status_code == 401
        ok = await client.get("/v1/status", headers=running.auth)
    assert ok.status_code == 200
    body = ok.json()
    assert body["engine_state"] == EngineState.RUNNING.value
    assert body["trading_mode"] == "paper"
    assert body["kill_switch"]["engaged"] is False
    assert {t["name"] for t in body["tasks"]} == {
        "loop-lag-monitor",
        "heartbeat",
        "telegram",  # bildirim kuyruğu (kapalıyken boşta bekler)
        "crash-reports",  # isteğe bağlı hata raporu kuyruğu (kapalıyken boşta bekler)
        "strategy-reliability",  # strateji ağırlıklarını saatte bir günceller
        "execution-connect",  # test ağı anahtarı yoksa hemen tamamlanır
    }


async def test_foreign_host_header_rejected(running: RunningEngine) -> None:
    """DNS rebinding: kötü niyetli bir site 127.0.0.1'e kendi alan adıyla istek atamaz."""
    async with httpx.AsyncClient(base_url=running.base_url) as client:
        response = await client.get("/v1/health", headers={"Host": "evil.example.com"})
    assert response.status_code == 400


async def test_kill_switch_flow(running: RunningEngine) -> None:
    async with httpx.AsyncClient(base_url=running.base_url, headers=running.auth) as client:
        engaged = await client.post("/v1/kill-switch/engage", json={"reason": "test"})
        assert engaged.status_code == 200
        assert engaged.json()["engine_state"] == "halted"

        wrong = await client.post("/v1/kill-switch/release", json={"confirmation": "tamam"})
        assert wrong.status_code == 400

        released = await client.post(
            "/v1/kill-switch/release", json={"confirmation": RELEASE_CONFIRMATION}
        )
        assert released.status_code == 200
        assert released.json()["engine_state"] == "running"

        audit = await client.get("/v1/audit", params={"limit": 10})
    actions = [e["action"] for e in audit.json()]
    assert actions[:3] == [
        "kill_switch.release",
        "kill_switch.release_rejected",
        "kill_switch.engage",
    ]


async def test_live_mode_refused_in_phase_one(running: RunningEngine) -> None:
    async with httpx.AsyncClient(base_url=running.base_url, headers=running.auth) as client:
        response = await client.post(
            "/v1/trading-mode",
            json={"mode": "live", "acknowledgement": LIVE_TRADING_ACK_PHRASE},
        )
        assert response.status_code == 409
        body = response.json()
        assert body["accepted"] is False
        assert body["mode"] == "paper"
        failed = {c["name"] for c in body["checks"] if not c["passed"]}
        assert {"config_live_enabled", "live_execution_available"} <= failed

        testnet = await client.post("/v1/trading-mode", json={"mode": "testnet"})
        assert testnet.status_code == 200
        assert (await client.get("/v1/trading-mode")).json()["mode"] == "testnet"


async def test_invalid_payload_rejected(running: RunningEngine) -> None:
    async with httpx.AsyncClient(base_url=running.base_url, headers=running.auth) as client:
        assert (await client.post("/v1/kill-switch/engage", json={"reason": ""})).status_code == 422
        assert (await client.post("/v1/trading-mode", json={"mode": "yolo"})).status_code == 422


async def test_websocket_requires_auth(running: RunningEngine) -> None:
    async with websockets.connect(running.ws_url) as ws:
        await ws.send(json.dumps({"type": "auth", "token": "yanlis"}))
        with pytest.raises(websockets.ConnectionClosed) as info:
            await asyncio.wait_for(ws.recv(), timeout=5)
    assert info.value.rcvd is not None and info.value.rcvd.code == 4401


async def test_websocket_rejects_foreign_origin(running: RunningEngine) -> None:
    with pytest.raises(websockets.InvalidStatus):
        async with websockets.connect(running.ws_url, origin="https://evil.example.com"):  # type: ignore[arg-type]
            pass


async def test_websocket_streams_events(running: RunningEngine) -> None:
    async with websockets.connect(running.ws_url) as ws:
        await ws.send(json.dumps({"type": "auth", "token": running.token}))
        hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert hello["type"] == "auth_ok"

        async with httpx.AsyncClient(base_url=running.base_url, headers=running.auth) as client:
            await client.post("/v1/kill-switch/engage", json={"reason": "ws testi"})

        seen: set[str] = set()
        for _ in range(100):
            message = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            seen.add(message["type"])
            if message["type"] == "KillSwitchEngaged":
                assert message["reason"] == "ws testi"
            if {"Heartbeat", "KillSwitchEngaged", "EngineStateChanged"} <= seen:
                break
    assert {"Heartbeat", "KillSwitchEngaged", "EngineStateChanged"} <= seen


async def test_shutdown_endpoint(tmp_path: Path) -> None:
    settings = EngineSettings(
        data_dir=tmp_path / "d", log_to_console=False, api=LocalApiSettings(port=0)
    )
    engine = Engine(settings)
    task = asyncio.create_task(engine.run())
    await asyncio.wait_for(engine.ready.wait(), timeout=10)
    assert engine.runtime is not None
    runtime_file = settings.paths.runtime_file
    info = json.loads(runtime_file.read_text(encoding="utf-8"))
    assert info["port"] == engine.bound_port
    assert info["token"] == engine.runtime.api_token
    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{engine.bound_port}",
        headers={"Authorization": f"Bearer {info['token']}"},
    ) as client:
        response = await client.post("/v1/engine/shutdown")
    assert response.status_code == 202
    assert await asyncio.wait_for(task, timeout=10) == 0
    assert not runtime_file.exists()


async def test_token_from_env_is_not_written_to_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATI_LOCAL_API_TOKEN", "masaustu-tarafindan-verilen-belirtec")
    settings = EngineSettings(
        data_dir=tmp_path / "d", log_to_console=False, api=LocalApiSettings(port=0)
    )
    engine = Engine(settings)
    task = asyncio.create_task(engine.run())
    await asyncio.wait_for(engine.ready.wait(), timeout=10)
    assert engine.runtime is not None
    try:
        assert engine.runtime.api_token == "masaustu-tarafindan-verilen-belirtec"
        info = json.loads(settings.paths.runtime_file.read_text(encoding="utf-8"))
        assert "token" not in info
    finally:
        engine.runtime.request_shutdown()
        await asyncio.wait_for(task, timeout=10)


async def test_second_engine_on_same_data_dir_is_refused(running: RunningEngine) -> None:
    from ati_engine.system.single_instance import AlreadyRunningError

    second = Engine(running.engine.settings)
    with pytest.raises(AlreadyRunningError):
        await second.run()
