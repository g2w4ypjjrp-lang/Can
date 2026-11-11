"""Testler için telefon benzetimi: iOS uygulamasıyla aynı kablo biçimini üretir (P-256, ham r‖s
imza, ``{"p", "s"}`` mesajları, uçtan uca şifreli zarf). Anahtarlar yazılımdır (Secure Enclave
yerine)."""

from __future__ import annotations

import base64
import json
import secrets
import time
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from ati_engine.remote.crypto import (
    KeyAgreement,
    channel_info,
    hmac_proof,
    key_id,
    open_json,
    relay_hello_text,
    seal_json,
    unb64url,
    verify_ed25519,
)


def now_ms() -> int:
    return int(time.time() * 1000)


def raw_signature(key: ec.EllipticCurvePrivateKey, data: bytes) -> bytes:
    r, s = decode_dss_signature(key.sign(data, ec.ECDSA(hashes.SHA256())))
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def x963(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class DeviceSim:
    def __init__(self, name: str = "Test iPhone", protection: str = "software") -> None:
        self.name = name
        self.protection = protection
        self.signing = ec.generate_private_key(ec.SECP256R1())
        self.guarded = ec.generate_private_key(ec.SECP256R1())
        self.signing_key = x963(self.signing)
        self.device_id = key_id(self.signing_key)
        self.kx = KeyAgreement.generate()  # uçtan uca şifreleme (iPhone'da Secure Enclave)
        self.last_seq = 0

    def next_seq(self) -> int:
        self.last_seq = max(self.last_seq + 1, now_ms())
        return self.last_seq

    def pair_request(self, qr: dict[str, Any], *, ts: int | None = None) -> dict[str, str]:
        payload = {
            "v": 1,
            "type": "pair_request",
            "engine_id": qr["engine_id"],
            "device_id": self.device_id,
            "name": self.name,
            "signing_key": b64(self.signing_key),
            "guarded_key": b64(x963(self.guarded)),
            "protection": self.protection,
            "kx_key": b64(self.kx.public_x963),
            "ts_ms": ts if ts is not None else now_ms(),
            "nonce": secrets.token_hex(8),
        }
        text = json.dumps(payload)
        data = text.encode("utf-8")
        return {
            "p": text,
            "s": b64(raw_signature(self.signing, data)),
            "proof": b64(hmac_proof(unb64url(qr["pair"]), data)),
        }

    def command(
        self,
        engine_id: str,
        command: str,
        args: dict[str, Any] | None = None,
        *,
        key: str = "signing",
        seq: int | None = None,
        ts: int | None = None,
        signer: ec.EllipticCurvePrivateKey | None = None,
    ) -> dict[str, str]:
        payload = {
            "v": 1,
            "type": "command",
            "engine_id": engine_id,
            "device_id": self.device_id,
            "key": key,
            "seq": seq if seq is not None else self.next_seq(),
            "ts_ms": ts if ts is not None else now_ms(),
            "command": command,
            "args": args or {},
        }
        text = json.dumps(payload, ensure_ascii=False)
        private = signer or (self.guarded if key == "guarded" else self.signing)
        return {"p": text, "s": b64(raw_signature(private, text.encode("utf-8")))}

    def hello(self, engine_id: str, *, ts: int | None = None) -> dict[str, Any]:
        stamp = ts if ts is not None else now_ms()
        return {
            "type": "hello",
            "role": "device",
            "device_id": self.device_id,
            "engine_id": engine_id,
            "key": b64(self.signing_key),
            "ts_ms": stamp,
            "sig": b64(
                raw_signature(
                    self.signing, relay_hello_text("device", self.device_id, engine_id, str(stamp))
                )
            ),
        }

    def seal(self, engine_kx: bytes, engine_id: str, message: dict[str, Any]) -> dict[str, Any]:
        """Motora giden mesajı motorun şifreleme anahtarına şifreler (QR'daki ``engine_kx``)."""
        return seal_json(engine_kx, message, channel_info("d2e", engine_id, self.device_id))

    def open_sealed(self, engine_key: bytes, engine_id: str, envelope: Any) -> dict[str, Any]:
        """Motordan gelen zarfı çözer, sonra imzayı doğrular (telefonun yaptığı gibi)."""
        message = open_json(self.kx, envelope, channel_info("e2d", engine_id, self.device_id))
        return self.open_engine(engine_key, message)

    @staticmethod
    def open_engine(engine_key: bytes, message: dict[str, str]) -> dict[str, Any]:
        """Motor mesajını doğrular (telefonun yaptığı gibi) ve içeriği döner."""
        verify_ed25519(engine_key, base64.b64decode(message["s"]), message["p"].encode("utf-8"))
        payload: dict[str, Any] = json.loads(message["p"])
        return payload
