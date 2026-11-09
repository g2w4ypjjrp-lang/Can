"""Yönetici güvenliği yapı taşları: TOTP (RFC 6238), kurtarma kodları, gizli değer kutusu.

* TOTP: HMAC-SHA1, 6 hane, 30 sn; saat kayması için ±1 adım. Aynı zaman adımındaki kod ikinci
  kez kabul edilmez (son kullanılan adım saklanır).
* Kurtarma kodları: 10 adet, ``XXXXX-XXXXX`` (Crockford Base32, kod başına 50 bit); yalnızca
  SHA-256 özeti saklanır, her biri tek kullanımlıktır.
* Gizli değer kutusu: AES-256-GCM; TOTP sırları ve ödeme sağlayıcı anahtarları veritabanında bu
  şekilde durur. AAD kayda bağlıdır (başka kayda taşınan şifreli değer çözülemez).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

TOTP_STEP_S = 30
TOTP_DIGITS = 6
ISSUER = "AI Trading Intelligence"
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_totp_secret() -> bytes:
    return secrets.token_bytes(20)


def totp_code(secret: bytes, counter: int) -> str:
    digest = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**TOTP_DIGITS).zfill(TOTP_DIGITS)


def verify_totp(
    secret: bytes, code: str, *, last_counter: int | None, now: float | None = None
) -> int | None:
    """Kod geçerliyse kullanılan zaman adımını döner; geçersiz veya tekrar kullanılmışsa None."""
    code = "".join(code.split())
    if len(code) != TOTP_DIGITS or not code.isdigit():
        return None
    current = int((time.time() if now is None else now) // TOTP_STEP_S)
    for counter in (current - 1, current, current + 1):
        if last_counter is not None and counter <= last_counter:
            continue
        if hmac.compare_digest(totp_code(secret, counter), code):
            return counter
    return None


def otpauth_uri(secret: bytes, account: str) -> str:
    label = quote(f"{ISSUER}:{account}")
    encoded = base64.b32encode(secret).decode().rstrip("=")
    return (
        f"otpauth://totp/{label}?secret={encoded}&issuer={quote(ISSUER)}"
        f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_STEP_S}"
    )


def new_recovery_codes(count: int = 10) -> list[str]:
    codes = []
    for _ in range(count):
        body = "".join(secrets.choice(_CROCKFORD) for _ in range(10))
        codes.append(f"{body[:5]}-{body[5:]}")
    return codes


def recovery_digest(code: str) -> bytes:
    normalized = "".join(code.split()).upper().replace("-", "")
    normalized = normalized.translate(str.maketrans("ILO", "110"))
    return hashlib.sha256(f"ati-recovery|{normalized}".encode()).digest()


def token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


class SecretBox:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Yönetici gizli anahtarı 32 bayt olmalı")
        self._aead = AESGCM(key)

    def seal(self, plaintext: bytes, aad: str) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + self._aead.encrypt(nonce, plaintext, aad.encode())

    def open(self, blob: bytes, aad: str) -> bytes:
        return self._aead.decrypt(blob[:12], blob[12:], aad.encode())
