"""Aşama 13: aktarma servisi. Kimlik kanıtı (hello imzası), yönlendirme, kanal yalıtımı, hız ve
cihaz sınırı, bağlantı değişimi. Veritabanı gerektirmez."""

from __future__ import annotations

import base64
import time
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ati_cloud.relay import MAX_DEVICES_PER_ENGINE, create_relay_app, hello_text, key_id


def now() -> int:
    return int(time.time() * 1000)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


class Engine:
    def __init__(self) -> None:
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.id = key_id(self.public)

    def hello(self, *, ts: int | None = None, engine_id: str | None = None) -> dict[str, Any]:
        stamp = now() if ts is None else ts
        eid = engine_id or self.id
        return {
            "type": "hello",
            "role": "engine",
            "engine_id": eid,
            "key": b64(self.public),
            "ts_ms": stamp,
            "sig": b64(self.key.sign(hello_text("engine", eid, str(stamp)))),
        }


class Device:
    def __init__(self) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.public = self.key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        self.id = key_id(self.public)

    def hello(self, engine_id: str, *, device_id: str | None = None) -> dict[str, Any]:
        stamp = now()
        did = device_id or self.id
        r, s = decode_dss_signature(
            self.key.sign(
                hello_text("device", did, engine_id, str(stamp)), ec.ECDSA(hashes.SHA256())
            )
        )
        return {
            "type": "hello",
            "role": "device",
            "device_id": did,
            "engine_id": engine_id,
            "key": b64(self.public),
            "ts_ms": stamp,
            "sig": b64(r.to_bytes(32, "big") + s.to_bytes(32, "big")),
        }


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_relay_app())


def connect_engine(client: TestClient, engine: Engine) -> Any:
    ws = client.websocket_connect("/v1/relay/engine").__enter__()
    ws.send_json(engine.hello())
    assert ws.receive_json() == {"type": "welcome", "role": "engine"}
    return ws


def connect_device(client: TestClient, device: Device, engine_id: str) -> Any:
    ws = client.websocket_connect("/v1/relay/device").__enter__()
    ws.send_json(device.hello(engine_id))
    welcome = ws.receive_json()
    assert welcome["type"] == "welcome"
    return ws


def test_routing_is_relay_attested_and_channel_isolated(client: TestClient) -> None:
    engine, other_engine = Engine(), Engine()
    e1 = connect_engine(client, engine)
    e2 = connect_engine(client, other_engine)
    device = Device()
    d = connect_device(client, device, engine.id)
    assert e1.receive_json() == {"type": "device_online", "device_id": device.id}

    d.send_json({"type": "to_engine", "msg": {"p": "{}", "s": "x"}})
    assert e1.receive_json() == {
        "type": "from_device",
        "device_id": device.id,
        "msg": {"p": "{}", "s": "x"},
    }

    e1.send_json({"type": "to_device", "device_id": device.id, "msg": {"p": "a", "s": "b"}})
    assert d.receive_json() == {"type": "from_engine", "msg": {"p": "a", "s": "b"}}
    # Başka motorun kanalındaki cihaza ulaşılamaz; ardından gelen geçerli mesaj ilk teslim edilen olmalı.
    e2.send_json({"type": "to_device", "device_id": device.id, "msg": {"p": "sahte", "s": "x"}})
    e1.send_json({"type": "to_device", "device_id": device.id, "msg": {"p": "gercek", "s": "x"}})
    assert d.receive_json()["msg"]["p"] == "gercek"

    d.close()
    assert e1.receive_json() == {"type": "device_offline", "device_id": device.id}
    e1.close()
    e2.close()


def test_engine_offline_and_reconnect(client: TestClient) -> None:
    engine = Engine()
    device = Device()
    d = connect_device(client, device, engine.id)
    d.send_json({"type": "to_engine", "msg": {"p": "{}", "s": "x"}})
    assert d.receive_json() == {"type": "engine_offline"}
    e = connect_engine(client, engine)
    assert e.receive_json() == {"type": "device_online", "device_id": device.id}
    e.close()
    assert d.receive_json() == {"type": "engine_offline"}
    d.close()


@pytest.mark.parametrize(
    "attack", ["bad_signature", "foreign_id", "stale", "wrong_role", "garbage"]
)
def test_engine_hello_must_prove_key(client: TestClient, attack: str) -> None:
    engine = Engine()
    if attack == "bad_signature":
        hello = engine.hello()
        hello["sig"] = b64(Engine().key.sign(b"baska"))
    elif attack == "foreign_id":
        hello = engine.hello(engine_id=Engine().id)
    elif attack == "stale":
        hello = engine.hello(ts=now() - 10 * 60_000)
    elif attack == "wrong_role":
        hello = {**engine.hello(), "role": "device"}
    else:
        hello = {"type": "hello", "role": "engine", "key": "@@@"}
    with client.websocket_connect("/v1/relay/engine") as ws:
        ws.send_json(hello)
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4403
    assert client.app.state.hub.counts == {"engines": 0, "devices": 0}  # type: ignore[attr-defined]


def test_device_cannot_impersonate_another_device(client: TestClient) -> None:
    engine = Engine()
    e = connect_engine(client, engine)
    victim, attacker = Device(), Device()
    with client.websocket_connect("/v1/relay/device") as ws:
        ws.send_json(attacker.hello(engine.id, device_id=victim.id))
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4403
    e.close()


def test_device_rate_limit(client: TestClient) -> None:
    engine = Engine()
    e = connect_engine(client, engine)
    device = Device()
    d = connect_device(client, device, engine.id)
    e.receive_json()  # device_online
    errors = 0
    for _ in range(40):
        d.send_json({"type": "to_engine", "msg": {"p": "{}", "s": "x"}})
    for _ in range(40):
        message = d.receive_json() if errors < 10 else None
        if message is None:
            break
        if message == {"type": "error", "reason": "rate_limited"}:
            errors += 1
    assert errors >= 5
    d.close()
    e.close()


def test_device_limit_per_engine_and_replacement(client: TestClient) -> None:
    engine = Engine()
    sockets = [connect_device(client, Device(), engine.id) for _ in range(MAX_DEVICES_PER_ENGINE)]
    with client.websocket_connect("/v1/relay/device") as ws:
        ws.send_json(Device().hello(engine.id))
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4429
    for s in sockets:
        s.close()
    first = connect_engine(client, engine)
    second = connect_engine(client, engine)
    with pytest.raises(WebSocketDisconnect) as replaced:
        first.receive_json()
    assert replaced.value.code == 4409
    second.close()
    assert client.get("/health").json()["status"] == "ok"
