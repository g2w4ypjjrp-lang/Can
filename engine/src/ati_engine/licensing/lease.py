"""İmzalı lisans kirasının doğrulanması (çevrim dışı).

Kira, bulutun Ed25519 anahtarıyla imzalanır; motor sürümüne gömülü güvenilir açık anahtarlarla
(``license.trusted_keys``) doğrulanır. Kira bu cihaza bağlıdır: cihaz anahtarı ve parmak izi
eşleşmezse (ör. veritabanı başka bilgisayara kopyalanmışsa) geçersizdir.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class LeaseError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Lease:
    signed: dict[str, str]
    data: dict[str, Any]

    @property
    def license_id(self) -> str:
        return str(self.data["license_id"])

    @property
    def device_id(self) -> str:
        return str(self.data["device_id"])

    @property
    def valid_until(self) -> int:
        return int(self.data["valid_until"])

    @property
    def offline_until(self) -> int:
        return int(self.data["offline_until"])

    @property
    def issued_at(self) -> int:
        return int(self.data["issued_at"])

    @property
    def license_expires_at(self) -> int | None:
        value = self.data.get("license_expires_at")
        return None if value is None else int(value)

    @property
    def companion_device_limit(self) -> int:
        return int(self.data.get("companion_device_limit", 0))


def verify_lease(
    signed: Any, trusted: dict[str, bytes], *, device_key: bytes, fingerprint: bytes
) -> Lease:
    if not isinstance(signed, dict):
        raise LeaseError("malformed", "Kira biçimi hatalı")
    text, sig = signed.get("p"), signed.get("s")
    if not isinstance(text, str) or not isinstance(sig, str):
        raise LeaseError("malformed", "Kira biçimi hatalı")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise LeaseError("malformed", "Kira içeriği okunamadı") from exc
    if not isinstance(data, dict) or data.get("v") != 1 or data.get("type") != "license_lease":
        raise LeaseError("malformed", "Desteklenmeyen kira sürümü")
    public = trusted.get(str(data.get("kid")))
    if public is None:
        raise LeaseError("unknown_key", "Kira tanınmayan bir anahtarla imzalanmış")
    try:
        Ed25519PublicKey.from_public_bytes(public).verify(
            base64.b64decode(sig, validate=True), text.encode("utf-8")
        )
    except (InvalidSignature, ValueError, binascii.Error) as exc:
        raise LeaseError("bad_signature", "Kira imzası doğrulanamadı") from exc
    if data.get("status") != "active":
        raise LeaseError("inactive", "Lisans etkin değil")
    try:
        same_device = base64.b64decode(str(data.get("device_key"))) == device_key
    except (ValueError, binascii.Error):
        same_device = False
    if not same_device or data.get("fingerprint") != fingerprint.hex():
        raise LeaseError("other_device", "Bu kira başka bir bilgisayara ait")
    for field_name in ("license_id", "device_id", "valid_until", "offline_until", "issued_at"):
        if field_name not in data:
            raise LeaseError("malformed", "Kira eksik alan içeriyor")
    return Lease(signed={"p": text, "s": sig}, data=data)
