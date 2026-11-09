"""Masaüstü uçtan uca testleri için sahte lisans sunucusu (bulutun lisans uç noktalarını taklit eder).

Cihaz imzasını doğrular, kirayı Ed25519 ile imzalar, 1 cihaz sınırı uygular. Yalnızca
``VALID_KEY`` geçerlidir. Gerçek bulut ile uçtan uca test: ``test_license_e2e.py``.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import time
import uuid
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ati_engine.api.server import EmbeddedServer, bind_socket
from ati_engine.licensing.keys import InvalidLicenseKey, normalize

VALID_KEY = "ATI-7XK9-PQ82-MN45-ZR61"
DAY_MS = 86_400_000


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"detail": {"code": code, "message": message}}, status_code=status)


class FakeLicenseServer:
    def __init__(self) -> None:
        self.signing = Ed25519PrivateKey.generate()
        public = self.signing.public_key().public_bytes_raw()
        self.kid = hashlib.sha256(public).hexdigest()[:16]
        self.public_key = base64.b64encode(public).decode()
        self.devices: dict[str, dict[str, Any]] = {}  # device_id -> {key, fingerprint, active}
        self.port = 0
        self._server: EmbeddedServer | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _lease(self, device_id: str) -> dict[str, Any]:
        device = self.devices[device_id]
        now = int(time.time() * 1000)
        payload = {
            "v": 1,
            "type": "license_lease",
            "lease_id": str(uuid.uuid4()),
            "license_id": "e2e-lisans",
            "serial": 1,
            "plan_code": "d30_1dev",
            "plan_name": "30 Gün - 1 Cihaz",
            "status": "active",
            "license_expires_at": now + 30 * DAY_MS,
            "device_limit": 1,
            "companion_device_limit": 2,
            "device_id": device_id,
            "device_key": base64.b64encode(device["key"]).decode(),
            "fingerprint": device["fingerprint"],
            "issued_at": now,
            "valid_until": now + DAY_MS,
            "offline_until": now + 3 * DAY_MS,
            "kid": self.kid,
        }
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        signed = {"p": text, "s": base64.b64encode(self.signing.sign(text.encode())).decode()}
        return {"lease": signed, "server_time_ms": now}

    def _app(self) -> FastAPI:
        app = FastAPI()

        def opened(message: dict[str, str], key: bytes) -> dict[str, Any] | None:
            try:
                Ed25519PublicKey.from_public_bytes(key).verify(
                    base64.b64decode(message["s"]), message["p"].encode()
                )
            except (InvalidSignature, ValueError, KeyError):
                return None
            payload: dict[str, Any] = json.loads(message["p"])
            return payload

        @app.post("/v1/licenses/activate")
        async def activate(request: Request) -> Any:
            message = await request.json()
            claimed = json.loads(message["p"])
            payload = opened(message, base64.b64decode(claimed["device_key"]))
            if payload is None:
                return _error(401, "bad_signature", "İmza doğrulanamadı")
            try:
                if normalize(payload["license_key"]) != normalize(VALID_KEY):
                    return _error(404, "not_found", "Lisans anahtarı geçersiz")
            except InvalidLicenseKey:
                return _error(400, "invalid_key", "Lisans anahtarı biçimi hatalı")
            existing = next(
                (d for d, v in self.devices.items() if v["fingerprint"] == payload["fingerprint"]),
                None,
            )
            others = [v for v in self.devices.values() if v["active"]]
            if existing is None and others:
                return _error(409, "device_limit", "Bu lisans için bilgisayar sınırına ulaşıldı")
            device_id = existing or str(uuid.uuid4())
            self.devices[device_id] = {
                "key": base64.b64decode(payload["device_key"]),
                "fingerprint": payload["fingerprint"],
                "active": True,
            }
            return self._lease(device_id)

        async def device_request(request: Request, kind: str) -> tuple[str | None, Any]:
            message = await request.json()
            claimed = json.loads(message["p"])
            device = self.devices.get(claimed.get("device_id", ""))
            if device is None or not device["active"]:
                return None, _error(403, "not_activated", "Bu bilgisayarda lisans etkin değil")
            if opened(message, device["key"]) is None or claimed.get("type") != kind:
                return None, _error(401, "bad_signature", "İmza doğrulanamadı")
            return str(claimed["device_id"]), None

        @app.post("/v1/licenses/renew")
        async def renew(request: Request) -> Any:
            device_id, error = await device_request(request, "renew")
            return error if device_id is None else self._lease(device_id)

        @app.post("/v1/licenses/deactivate")
        async def deactivate(request: Request) -> Any:
            device_id, error = await device_request(request, "deactivate")
            if device_id is None:
                return error
            self.devices[device_id]["active"] = False
            return {"status": "ok"}

        return app

    async def start(self) -> FakeLicenseServer:
        from uvicorn import Config

        sock = bind_socket("127.0.0.1", 0)
        self.port = sock.getsockname()[1]
        self._server = EmbeddedServer(
            Config(self._app(), log_config=None, access_log=False, lifespan="off")
        )
        self._task = asyncio.create_task(self._server.serve(sockets=[sock]))
        for _ in range(100):
            if self._server.started:
                break
            await asyncio.sleep(0.01)
        return self

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(self._task, 5)
