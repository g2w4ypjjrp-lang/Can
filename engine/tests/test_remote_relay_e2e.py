"""Aşama 13 uçtan uca: GERÇEK aktarma servisi (cloud, ayrı süreç) + gerçek motor + telefon
benzetimi. Eşleştirme, imzalı komutun uygulanması, imzasız / tekrar oynatılmış / başka cihaz
adına gönderilmiş / Face ID gerektiren komutların reddi, motor mesajlarının telefonda
doğrulanması."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import websockets

from ati_engine.app import Engine
from ati_engine.config import EngineSettings, LocalApiSettings, RemoteSettings
from remote_device import DeviceSim

CLOUD_DIR = Path(__file__).resolve().parents[2] / "cloud"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("uv") is None or not CLOUD_DIR.is_dir(),
    reason="aktarma servisi süreci için uv ve cloud/ gerekir (Windows CI'da atlanır)",
)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def relay_url() -> AsyncIterator[str]:
    port = free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("VIRTUAL_ENV")}
    process = subprocess.Popen(
        ["uv", "run", "--project", str(CLOUD_DIR), "ati-cloud-relay", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(240):
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if process.poll() is not None:
                raise RuntimeError(process.stderr.read().decode() if process.stderr else "relay")
            import time

            time.sleep(0.25)
        else:
            raise RuntimeError("aktarma servisi başlamadı")
        yield f"ws://127.0.0.1:{port}"
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


@dataclass
class Stack:
    engine: Engine
    http: httpx.AsyncClient


@pytest.fixture
async def stack(tmp_path: Path, relay_url: str) -> AsyncIterator[Stack]:
    settings = EngineSettings(
        data_dir=tmp_path / "data",
        log_to_console=False,
        api=LocalApiSettings(port=0),
        remote=RemoteSettings(relay_url=relay_url, snapshot_interval_s=2),
    )
    engine = Engine(settings)
    task = asyncio.create_task(engine.run())
    await asyncio.wait_for(engine.ready.wait(), timeout=15)
    assert engine.runtime is not None
    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{engine.bound_port}",
        headers={"Authorization": f"Bearer {engine.runtime.api_token}"},
    ) as http:
        for _ in range(100):
            if (await http.get("/v1/remote/status")).json()["connected"]:
                break
            await asyncio.sleep(0.1)
        yield Stack(engine, http)
    engine.runtime.request_shutdown()
    await asyncio.wait_for(task, timeout=15)


class Phone:
    """Telefon: aktarma servisine bağlanır, motor mesajlarını imzasından doğrular."""

    def __init__(self, sim: DeviceSim, ws: Any, engine_key: bytes) -> None:
        self.sim = sim
        self.ws = ws
        self.engine_key = engine_key

    @classmethod
    async def connect(cls, relay: str, sim: DeviceSim, qr: dict[str, Any]) -> Phone:
        ws = await websockets.connect(relay + "/v1/relay/device")
        await ws.send(json.dumps(sim.hello(qr["engine_id"])))
        welcome = json.loads(await ws.recv())
        assert welcome["type"] == "welcome" and welcome["engine_online"] is True
        return cls(sim, ws, base64.b64decode(qr["engine_key"]))

    async def send(self, msg: dict[str, Any]) -> None:
        await self.ws.send(json.dumps({"type": "to_engine", "msg": msg}))

    async def next(self, kind: str, within: float = 10.0) -> dict[str, Any]:
        async with asyncio.timeout(within):
            while True:
                frame = json.loads(await self.ws.recv())
                if frame.get("type") != "from_engine":
                    continue
                payload = DeviceSim.open_engine(self.engine_key, frame["msg"])  # imza doğrulanır
                if payload["type"] == kind:
                    return payload


async def test_pair_and_control_through_real_relay(stack: Stack, relay_url: str) -> None:
    http = stack.http
    status = (await http.get("/v1/remote/status")).json()
    assert status["connected"] and status["devices"] == []
    pairing = (await http.post("/v1/remote/pairing")).json()
    qr = json.loads(pairing["qr"])
    assert qr["relay"] == relay_url

    phone = await Phone.connect(relay_url, DeviceSim("Can'ın iPhone'u"), qr)
    await phone.send(phone.sim.pair_request(qr))
    paired = await phone.next("pair_result")
    assert paired["ok"] and paired["name"] == "Can'ın iPhone'u"
    snapshot = await phone.next("snapshot")
    assert snapshot["data"]["engine"]["kill_switch"] is False
    assert snapshot["data"]["engine"]["trading_mode"] == "paper"

    engine_id = qr["engine_id"]
    command = phone.sim.command(engine_id, "engage_kill_switch", {"reason": "telefondan test"})
    await phone.send(command)
    result = await phone.next("result")
    assert result["ok"] and result["message"] == "Acil durdurma devrede"
    engine_status = (await http.get("/v1/status")).json()
    assert engine_status["kill_switch"]["engaged"] is True
    assert engine_status["engine_state"] == "halted"
    assert "telefondan test" in engine_status["kill_switch"]["reason"]

    await phone.send(command)  # aynı imzalı mesaj tekrar
    assert (await phone.next("result"))["reason"] == "replay"

    await phone.send({"p": command["p"]})  # imzasız: yanıt bile verilmez
    release_signing = phone.sim.command(engine_id, "release_kill_switch", key="signing")
    await phone.send(release_signing)
    assert (await phone.next("result"))["reason"] == "biometric_required"
    assert (await http.get("/v1/status")).json()["kill_switch"]["engaged"] is True

    # Başka bir cihaz (ör. ele geçirilmiş aktarma hesabı) kurbanın imzalı mesajını kendi
    # bağlantısından gönderirse aktarma servisi gerçek göndereni bildirir; motor reddeder.
    attacker = await Phone.connect(relay_url, DeviceSim("saldırgan"), qr)
    await attacker.send(phone.sim.command(engine_id, "close_all", key="guarded"))

    release = phone.sim.command(engine_id, "release_kill_switch", key="guarded")
    await phone.send(release)
    assert (await phone.next("result"))["ok"]
    assert (await http.get("/v1/status")).json()["kill_switch"]["engaged"] is False

    log = (await http.get("/v1/remote/commands")).json()
    reasons = [(r["command"], r["accepted"], r["reason"]) for r in log]
    assert ("engage_kill_switch", True, "ok") in reasons
    assert ("engage_kill_switch", False, "replay") in reasons
    assert ("", False, "malformed") in reasons  # imzasız
    assert ("release_kill_switch", False, "biometric_required") in reasons
    assert ("close_all", False, "malformed") in reasons  # başka cihaz adına
    assert ("release_kill_switch", True, "ok") in reasons
    audit = (await http.get("/v1/audit", params={"limit": 50})).json()
    actors = {a["actor"] for a in audit}
    assert f"remote:{phone.sim.device_id}" in actors

    devices = (await http.get("/v1/remote/status")).json()["devices"]
    assert [d["name"] for d in devices] == ["Can'ın iPhone'u"]
    assert devices[0]["online"] is True
    revoke = await http.post("/v1/remote/devices/revoke", params={"device_id": phone.sim.device_id})
    assert revoke.json() == {"revoked": True}
    await phone.send(phone.sim.command(engine_id, "engage_kill_switch"))
    await asyncio.sleep(0.5)
    assert (await http.get("/v1/status")).json()["kill_switch"]["engaged"] is False
    log = (await http.get("/v1/remote/commands")).json()
    assert log[0]["reason"] == "revoked_device"
    await phone.ws.close()
    await attacker.ws.close()


async def test_pairing_disabled_without_relay(tmp_path: Path) -> None:
    settings = EngineSettings(
        data_dir=tmp_path / "data", log_to_console=False, api=LocalApiSettings(port=0)
    )
    engine = Engine(settings)
    task = asyncio.create_task(engine.run())
    await asyncio.wait_for(engine.ready.wait(), timeout=15)
    assert engine.runtime is not None
    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{engine.bound_port}",
        headers={"Authorization": f"Bearer {engine.runtime.api_token}"},
    ) as http:
        status = (await http.get("/v1/remote/status")).json()
        assert status["enabled"] is False and len(status["engine_id"]) == 32
        response = await http.post("/v1/remote/pairing")
        assert response.status_code == 409 and "G5" in response.json()["detail"]
    engine.runtime.request_shutdown()
    await asyncio.wait_for(task, timeout=15)
