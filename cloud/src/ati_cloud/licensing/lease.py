"""İmzalı lisans kirası ve motordan gelen imzalı istekler.

Kira (lease), motorun çevrim dışı doğrulayabildiği kısa ömürlü bir belgedir: hangi lisansın,
hangi cihazda, hangi koşullarla ne zamana kadar geçerli olduğunu söyler ve bulutun Ed25519
anahtarıyla imzalanır. Motor imzayı gömülü açık anahtarla doğrular; kira cihaza (cihaz
anahtarı + parmak izi) bağlıdır, başka bilgisayarda geçersizdir.

Mesaj biçimi uzaktan kontrol protokolüyle aynıdır: ``{"p": JSON metni, "s": imza}``; imza
gönderilen metnin kendisi üzerine atılır. Ayrıntı: ``shared/protocol/license-v1.md``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

LEASE_TYPE = "license_lease"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"), validate=True)


def key_id(public_raw: bytes) -> str:
    return hashlib.sha256(public_raw).hexdigest()[:16]


def canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class LeaseSigner:
    def __init__(self, private_raw: bytes) -> None:
        if len(private_raw) != 32:
            raise ValueError("Kira imza anahtarı 32 baytlık Ed25519 özel anahtarı olmalı")
        self._key = Ed25519PrivateKey.from_private_bytes(private_raw)
        self.public_raw = self._key.public_key().public_bytes_raw()
        self.kid = key_id(self.public_raw)

    def sign(self, payload: dict[str, Any]) -> dict[str, str]:
        text = canonical({**payload, "kid": self.kid})
        return {"p": text, "s": b64(self._key.sign(text.encode("utf-8")))}


@dataclass(frozen=True)
class LeaseTerms:
    license_id: str
    serial: int
    plan_code: str
    plan_name: str
    status: str
    license_expires_at_ms: int | None
    device_limit: int
    companion_device_limit: int
    device_id: str
    device_key: bytes
    fingerprint: bytes


def lease_payload(terms: LeaseTerms, *, now_ms: int, ttl_s: int, offline_s: int) -> dict[str, Any]:
    valid_until = now_ms + ttl_s * 1000
    offline_until = now_ms + offline_s * 1000
    if terms.license_expires_at_ms is not None:
        valid_until = min(valid_until, terms.license_expires_at_ms)
        offline_until = min(offline_until, terms.license_expires_at_ms)
    return {
        "v": 1,
        "type": LEASE_TYPE,
        "lease_id": str(uuid.uuid4()),
        "license_id": terms.license_id,
        "serial": terms.serial,
        "plan_code": terms.plan_code,
        "plan_name": terms.plan_name,
        "status": terms.status,
        "license_expires_at": terms.license_expires_at_ms,
        "device_limit": terms.device_limit,
        "companion_device_limit": terms.companion_device_limit,
        "device_id": terms.device_id,
        "device_key": b64(terms.device_key),
        "fingerprint": terms.fingerprint.hex(),
        "issued_at": now_ms,
        "valid_until": valid_until,
        "offline_until": offline_until,
    }


class BadRequestSignature(ValueError):
    pass


def open_device_request(message: Any, public_raw: bytes | None = None) -> dict[str, Any]:
    """Motorun imzalı isteğini açar. ``public_raw`` verilmezse (aktivasyon) içerikteki
    ``device_key`` kullanılır: istek, o anahtarın sahibince imzalandığını kanıtlar."""
    if not isinstance(message, dict):
        raise BadRequestSignature("İstek biçimi hatalı")
    text, sig = message.get("p"), message.get("s")
    if not isinstance(text, str) or not isinstance(sig, str) or len(text) > 8192:
        raise BadRequestSignature("İstek biçimi hatalı")
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise BadRequestSignature("İstek içeriği JSON değil") from exc
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise BadRequestSignature("Desteklenmeyen istek sürümü")
    try:
        key = public_raw if public_raw is not None else unb64(str(payload.get("device_key", "")))
        if len(key) != 32:
            raise BadRequestSignature("Cihaz anahtarı geçersiz")
        Ed25519PublicKey.from_public_bytes(key).verify(unb64(sig), text.encode("utf-8"))
    except (InvalidSignature, ValueError) as exc:
        if isinstance(exc, BadRequestSignature):
            raise
        raise BadRequestSignature("İmza doğrulanamadı") from exc
    return payload
