"""Aktarma servisi (relay): iOS ↔ masaüstü motoru arasında uçtan uca imzalı mesajları yönlendirir.

Protokol: ``shared/protocol/remote-v1.md``. Servis **hiçbir anahtar tutmaz** ve mesaj içeriğini
yorumlamaz. Komutlar telefonun anahtarıyla, durum mesajları motorun anahtarıyla imzalıdır. Bu
servis ele geçirilse bile komut üretemez, durum sahteleyemez, cihaz eşleştiremez.

Yaptığı denetimler:

* Bağlanan taraf, kimliğinin türetildiği anahtara sahip olduğunu imzalı bir ``hello`` ile
  kanıtlar. Başkasının kimliğiyle bağlanılamaz.
* Mesaj boyutu ve hız sınırı uygulanır. Motor başına en fazla 20 telefon bağlanabilir.
* Telefon yalnızca bağlandığı motorla, motor yalnızca kendi kanalındaki telefonlarla konuşur.

Tek örnek durumu bellektedir. Birden çok örnekte yönlendirme Redis pub/sub ile yapılacaktır
(dağıtım aşaması, G5).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from ati_cloud import __version__

logger = logging.getLogger(__name__)

MAX_MESSAGE_BYTES = 64 * 1024
MAX_DEVICES_PER_ENGINE = 20
HELLO_TIMEOUT_S = 10.0
MAX_SKEW_MS = 120_000
CLOSE_POLICY = 4403
CLOSE_REPLACED = 4409
CLOSE_LIMIT = 4429


def key_id(public_raw: bytes) -> str:
    return hashlib.sha256(public_raw).digest()[:16].hex()


def hello_text(role: str, *parts: str) -> bytes:
    return "|".join(("ati-relay-hello", role, *parts)).encode("utf-8")


class HelloError(ValueError):
    pass


def _b64(text: Any) -> bytes:
    if not isinstance(text, str):
        raise HelloError("base64 bekleniyordu")
    try:
        return base64.b64decode(text, validate=True)
    except ValueError as exc:
        raise HelloError("base64 geçersiz") from exc


def _fresh(ts: Any, now_ms: int) -> int:
    if not isinstance(ts, int) or isinstance(ts, bool) or abs(now_ms - ts) > MAX_SKEW_MS:
        raise HelloError("zaman damgası geçersiz")
    return ts


def verify_engine_hello(hello: dict[str, Any], now_ms: int) -> str:
    if hello.get("type") != "hello" or hello.get("role") != "engine":
        raise HelloError("hello bekleniyordu")
    key = _b64(hello.get("key"))
    engine_id = key_id(key) if len(key) == 32 else None
    if engine_id is None or hello.get("engine_id") != engine_id:
        raise HelloError("motor kimliği anahtarla eşleşmiyor")
    ts = _fresh(hello.get("ts_ms"), now_ms)
    try:
        Ed25519PublicKey.from_public_bytes(key).verify(
            _b64(hello.get("sig")), hello_text("engine", engine_id, str(ts))
        )
    except (InvalidSignature, ValueError) as exc:
        raise HelloError("imza geçersiz") from exc
    return engine_id


def verify_device_hello(hello: dict[str, Any], now_ms: int) -> tuple[str, str]:
    if hello.get("type") != "hello" or hello.get("role") != "device":
        raise HelloError("hello bekleniyordu")
    key = _b64(hello.get("key"))
    device_id = hello.get("device_id")
    engine_id = hello.get("engine_id")
    if len(key) != 65 or key[0] != 0x04 or device_id != key_id(key):
        raise HelloError("cihaz kimliği anahtarla eşleşmiyor")
    if not isinstance(engine_id, str) or len(engine_id) != 32:
        raise HelloError("motor kimliği geçersiz")
    ts = _fresh(hello.get("ts_ms"), now_ms)
    sig = _b64(hello.get("sig"))
    if len(sig) != 64:
        raise HelloError("imza 64 bayt olmalı")
    try:
        public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), key)
        der = encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big"))
        public.verify(
            der, hello_text("device", device_id, engine_id, str(ts)), ec.ECDSA(hashes.SHA256())
        )
    except (InvalidSignature, ValueError) as exc:
        raise HelloError("imza geçersiz") from exc
    return device_id, engine_id


class RateLimiter:
    """Belirteç kovası: ``capacity`` mesaj, saniyede ``rate`` yenilenir."""

    def __init__(self, capacity: float, rate: float) -> None:
        self.capacity = capacity
        self.rate = rate
        self.tokens = capacity
        self.updated = time.monotonic()

    def allow(self) -> bool:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


@dataclass
class Channel:
    engine: WebSocket | None = None
    devices: dict[str, WebSocket] = field(default_factory=dict)


class RelayHub:
    def __init__(self) -> None:
        self.channels: dict[str, Channel] = {}
        self.stats = {"engines": 0, "devices": 0, "forwarded": 0, "rejected_hello": 0, "limited": 0}

    def channel(self, engine_id: str) -> Channel:
        return self.channels.setdefault(engine_id, Channel())

    def cleanup(self, engine_id: str) -> None:
        channel = self.channels.get(engine_id)
        if channel and channel.engine is None and not channel.devices:
            del self.channels[engine_id]

    @property
    def counts(self) -> dict[str, int]:
        return {
            "engines": sum(1 for c in self.channels.values() if c.engine is not None),
            "devices": sum(len(c.devices) for c in self.channels.values()),
        }


async def _send(ws: WebSocket | None, payload: dict[str, Any]) -> None:
    if ws is None:
        return
    with contextlib.suppress(Exception):
        await ws.send_text(json.dumps(payload, ensure_ascii=False))


async def _receive_json(ws: WebSocket, within: float | None = None) -> dict[str, Any]:
    text = await asyncio.wait_for(ws.receive_text(), within) if within else await ws.receive_text()
    if len(text.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise HelloError("mesaj çok büyük")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise HelloError("mesaj nesne olmalı")
    return data


def _now_ms() -> int:
    return int(time.time() * 1000)


def create_relay_app(hub: RelayHub | None = None) -> FastAPI:
    app = FastAPI(
        title="AI Trading Intelligence Relay",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    relay = hub or RelayHub()
    app.state.hub = relay

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, **relay.counts}

    @app.websocket("/v1/relay/engine")
    async def engine_socket(ws: WebSocket) -> None:
        await ws.accept()
        try:
            engine_id = verify_engine_hello(await _receive_json(ws, HELLO_TIMEOUT_S), _now_ms())
        except (HelloError, TimeoutError, ValueError, WebSocketDisconnect):
            relay.stats["rejected_hello"] += 1
            with contextlib.suppress(Exception):
                await ws.close(code=CLOSE_POLICY)
            return
        channel = relay.channel(engine_id)
        previous = channel.engine
        channel.engine = ws
        if previous is not None:
            with contextlib.suppress(Exception):
                await previous.close(code=CLOSE_REPLACED)
        relay.stats["engines"] += 1
        await _send(ws, {"type": "welcome", "role": "engine"})
        for device_id in list(channel.devices):
            await _send(ws, {"type": "device_online", "device_id": device_id})
        limiter = RateLimiter(capacity=400, rate=40)
        try:
            while True:
                message = await _receive_json(ws)
                if not limiter.allow():
                    relay.stats["limited"] += 1
                    continue
                if message.get("type") != "to_device":
                    continue
                target = channel.devices.get(str(message.get("device_id", "")))
                if target is not None and isinstance(message.get("msg"), dict):
                    relay.stats["forwarded"] += 1
                    await _send(target, {"type": "from_engine", "msg": message["msg"]})
        except (WebSocketDisconnect, HelloError, ValueError):
            pass
        finally:
            if channel.engine is ws:
                channel.engine = None
                for device in list(channel.devices.values()):
                    await _send(device, {"type": "engine_offline"})
            relay.cleanup(engine_id)

    @app.websocket("/v1/relay/device")
    async def device_socket(ws: WebSocket) -> None:
        await ws.accept()
        try:
            device_id, engine_id = verify_device_hello(
                await _receive_json(ws, HELLO_TIMEOUT_S), _now_ms()
            )
        except (HelloError, TimeoutError, ValueError, WebSocketDisconnect):
            relay.stats["rejected_hello"] += 1
            with contextlib.suppress(Exception):
                await ws.close(code=CLOSE_POLICY)
            return
        channel = relay.channel(engine_id)
        if device_id not in channel.devices and len(channel.devices) >= MAX_DEVICES_PER_ENGINE:
            with contextlib.suppress(Exception):
                await ws.close(code=CLOSE_LIMIT)
            relay.cleanup(engine_id)
            return
        previous = channel.devices.get(device_id)
        channel.devices[device_id] = ws
        if previous is not None:
            with contextlib.suppress(Exception):
                await previous.close(code=CLOSE_REPLACED)
        relay.stats["devices"] += 1
        await _send(
            ws, {"type": "welcome", "role": "device", "engine_online": channel.engine is not None}
        )
        await _send(channel.engine, {"type": "device_online", "device_id": device_id})
        limiter = RateLimiter(capacity=30, rate=1)
        try:
            while True:
                message = await _receive_json(ws)
                if not limiter.allow():
                    relay.stats["limited"] += 1
                    await _send(ws, {"type": "error", "reason": "rate_limited"})
                    continue
                if message.get("type") != "to_engine" or not isinstance(message.get("msg"), dict):
                    continue
                if channel.engine is None:
                    await _send(ws, {"type": "engine_offline"})
                    continue
                relay.stats["forwarded"] += 1
                await _send(
                    channel.engine,
                    {"type": "from_device", "device_id": device_id, "msg": message["msg"]},
                )
        except (WebSocketDisconnect, HelloError, ValueError):
            pass
        finally:
            if channel.devices.get(device_id) is ws:
                del channel.devices[device_id]
                await _send(channel.engine, {"type": "device_offline", "device_id": device_id})
            relay.cleanup(engine_id)

    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(prog="ati-cloud-relay", description="Aktarma servisi")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run(create_relay_app(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
