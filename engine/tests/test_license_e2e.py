"""Aşama 15 uçtan uca: GERÇEK bulut lisans API'si (ati-cloud-api, ayrı süreç, PostgreSQL) +
gerçek motor. Etkinleştirme, işlem kapısı (hazırlık koşulu), kira yenileme, sunucuda dondurma
sonrası ret, cihaz limiti, cihaz bırakma.

``ATI_TEST_DATABASE_URL`` (PostgreSQL) ve ``uv`` gerekir; yoksa atlanır.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ati_engine.app import Engine
from ati_engine.config import EngineSettings, LicenseSettings, LocalApiSettings

CLOUD_DIR = Path(__file__).resolve().parents[2] / "cloud"
ADMIN_DSN = os.environ.get("ATI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("uv") is None or not ADMIN_DSN,
    reason="bulut lisans API'si için PostgreSQL (ATI_TEST_DATABASE_URL) ve uv gerekir",
)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class Cloud:
    url: str
    env: dict[str, str]
    kid: str
    public_key: str

    def fixture(self, *args: str) -> str:
        result = subprocess.run(
            [
                "uv",
                "run",
                "--project",
                str(CLOUD_DIR),
                "python",
                "scripts/e2e_license_fixture.py",
                *args,
            ],
            cwd=CLOUD_DIR,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr)
        return result.stdout.strip()


@pytest.fixture(scope="module")
def cloud() -> Iterator[Cloud]:
    assert ADMIN_DSN
    url = urlparse(ADMIN_DSN)
    dsn = urlunparse(url._replace(path="/ati_license_engine_e2e"))
    signing = Ed25519PrivateKey.generate()
    public = signing.public_key().public_bytes_raw()
    env = {k: v for k, v in os.environ.items() if not k.startswith("VIRTUAL_ENV")}
    env.update(
        ATI_ENVIRONMENT="test",
        ATI_DATABASE_URL=dsn,
        ATI_SESSION_COOKIE_SECURE="false",
        ATI_LICENSE_PEPPER=base64.b64encode(secrets.token_bytes(32)).decode(),
        ATI_LICENSE_KEK=base64.b64encode(secrets.token_bytes(32)).decode(),
        ATI_LEASE_SIGNING_KEY=base64.b64encode(signing.private_bytes_raw()).decode(),
    )
    state = Cloud(
        url="",
        env=env,
        kid=hashlib.sha256(public).hexdigest()[:16],
        public_key=base64.b64encode(public).decode(),
    )
    state.fixture("setup")
    port = free_port()
    process = subprocess.Popen(
        ["uv", "run", "--project", str(CLOUD_DIR), "ati-cloud-api", "--port", str(port)],
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
                raise RuntimeError(process.stderr.read().decode() if process.stderr else "api")
            time.sleep(0.25)
        else:
            raise RuntimeError("bulut API'si başlamadı")
        state.url = f"http://127.0.0.1:{port}"
        yield state
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


@dataclass
class Node:
    engine: Engine
    http: httpx.AsyncClient
    task: asyncio.Task[int]


async def start_engine(tmp: Path, cloud: Cloud, fingerprint: str) -> Node:
    settings = EngineSettings(
        data_dir=tmp,
        log_to_console=False,
        api=LocalApiSettings(port=0),
        license=LicenseSettings(
            server_url=cloud.url,
            trusted_keys={cloud.kid: cloud.public_key},
            enforce=True,
            fingerprint_override=fingerprint,
        ),
    )
    engine = Engine(settings)
    task = asyncio.create_task(engine.run())
    await asyncio.wait_for(engine.ready.wait(), timeout=20)
    assert engine.runtime is not None
    http = httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{engine.bound_port}",
        headers={"Authorization": f"Bearer {engine.runtime.api_token}"},
        timeout=30,
    )
    return Node(engine, http, task)


async def stop_engine(node: Node) -> None:
    await node.http.aclose()
    assert node.engine.runtime is not None
    node.engine.runtime.request_shutdown()
    await asyncio.wait_for(node.task, timeout=20)


@pytest.fixture
async def nodes(tmp_path: Path, cloud: Cloud) -> AsyncIterator[list[Node]]:
    started: list[Node] = []
    yield started
    for node in started:
        await stop_engine(node)


def license_condition(status: dict[str, Any]) -> dict[str, Any]:
    return next(c for c in status["readiness"] if c["name"] == "license.valid")


async def test_engine_activates_renews_and_obeys_cloud(
    tmp_path: Path, cloud: Cloud, nodes: list[Node]
) -> None:
    issued = json.loads(cloud.fixture("issue", "motor@example.com", "d30_1dev"))
    key = issued["key"]
    first = await start_engine(tmp_path / "pc1", cloud, "pc-1")
    nodes.append(first)

    status = (await first.http.get("/v1/license")).json()
    assert status["state"] == "unlicensed" and status["enforced"]
    engine_status = (await first.http.get("/v1/status")).json()
    # Lisans yokken yeni işlem açılmaz: hazırlık koşulu yanlış, motor güvenli modda.
    assert engine_status["engine_state"] == "safe_mode"
    assert engine_status["can_open_positions"] is False
    assert license_condition(engine_status)["ready"] is False

    typo = key[:-1] + ("0" if key[-1] != "0" else "1")
    bad = await first.http.post("/v1/license/activate", json={"key": typo})
    assert bad.status_code == 400 and "yazım hatası" in bad.json()["detail"]

    activated = await first.http.post("/v1/license/activate", json={"key": key})
    assert activated.status_code == 200, activated.text
    body = activated.json()
    assert body["state"] == "active" and body["plan_code"] == "d30_1dev"
    assert body["license_id"] == issued["license_id"] and body["companion_device_limit"] == 2
    assert body["key_hint"].endswith(key[-4:])
    engine_status = (await first.http.get("/v1/status")).json()
    assert license_condition(engine_status)["ready"] is True

    renewed = (await first.http.post("/v1/license/refresh")).json()
    assert renewed["state"] == "active" and renewed["last_renewed_at"] >= body["last_renewed_at"]

    # 1 cihazlık lisans: ikinci bilgisayar reddedilir.
    second = await start_engine(tmp_path / "pc2", cloud, "pc-2")
    nodes.append(second)
    limit = await second.http.post("/v1/license/activate", json={"key": key})
    assert limit.status_code == 409 and "sınır" in limit.json()["detail"]

    # Sunucuda dondurma: yenilemede ret, işlem kapısı kapanır.
    cloud.fixture("sql", "UPDATE licenses SET status = 'frozen', frozen_reason = 'inceleme'")
    frozen = (await first.http.post("/v1/license/refresh")).json()
    assert frozen["state"] == "revoked" and "dondurulmuş" in frozen["message"]
    engine_status = (await first.http.get("/v1/status")).json()
    assert engine_status["engine_state"] == "safe_mode"
    assert engine_status["can_open_positions"] is False
    assert license_condition(engine_status)["ready"] is False

    # Dondurma kalkınca yeniden etkinleştirilir (aynı bilgisayar, yeni yer tüketmez).
    cloud.fixture("sql", "UPDATE licenses SET status = 'active'")
    again = await first.http.post("/v1/license/activate", json={"key": key})
    assert again.status_code == 200 and again.json()["state"] == "active"

    # Bilgisayar değişikliği: ilk bilgisayar lisansı bırakır, ikincisi etkinleştirir.
    released = (await first.http.post("/v1/license/deactivate")).json()
    assert released["state"] == "unlicensed"
    moved = await second.http.post("/v1/license/activate", json={"key": key})
    assert moved.status_code == 200 and moved.json()["state"] == "active"
    audit = (await first.http.get("/v1/audit", params={"limit": 50})).json()
    actions = [entry["action"] for entry in audit]
    assert "license.activated" in actions and "license.deactivated" in actions
    assert all(key not in json.dumps(entry) for entry in audit)  # anahtar kayda yazılmaz
