"""Telefon tarayıcısına bildirim (Web Push): ekran kilitliyken ve sayfa kapalıyken de ulaşır.

Uygulama indirmeden çalışır: iPhone'da site "Ana Ekrana Ekle" ile eklenir (iOS 16.4+), Android'de
Chrome'da doğrudan. Tarayıcı bir abonelik (uç adresi + şifreleme anahtarları) üretir ve bunu
uçtan uca şifreli aktarma kanalıyla motora gönderir.

Bildirim içeriği **motorda, tarayıcının anahtarına şifrelenir** (RFC 8291, ``aes128gcm`` /
RFC 8188). Apple/Google'ın bildirim sunucuları ve bizim sunucumuz içeriği okuyamaz; yalnızca
şifreli paketi telefona taşırlar. Gönderen kimliği VAPID (RFC 8292) ile kanıtlanır: abonelik bu
motorun açık anahtarına bağlıdır, başka biri bu telefona bildirim gönderemez.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

RECORD_SIZE = 4096
# Bildirim servislerinin alan adları (abonelik adresi yalnızca bunlardan biri olabilir; motorun
# rastgele adreslere istek atması engellenir).
PUSH_SERVICE_SUFFIXES = (
    "push.apple.com",  # Safari / iPhone (web.push.apple.com)
    "fcm.googleapis.com",  # Chrome, Android, Samsung Internet
    "push.services.mozilla.com",  # Firefox
    "notify.windows.com",  # Edge
)
MAX_PAYLOAD = 3000  # şifreli paket 4 KB sınırının altında kalsın


class PushError(ValueError):
    pass


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64url(text: str) -> bytes:
    text = text.strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hmac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def _public_raw(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def _load_public(raw: bytes) -> ec.EllipticCurvePublicKey:
    if len(raw) != 65 or raw[0] != 4:
        raise PushError("Tarayıcı anahtarı geçersiz")
    try:
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    except ValueError as exc:
        raise PushError("Tarayıcı anahtarı geçersiz") from exc


def encrypt(
    plaintext: bytes,
    ua_public: bytes,
    auth_secret: bytes,
    *,
    sender_key: ec.EllipticCurvePrivateKey | None = None,
    salt: bytes | None = None,
) -> bytes:
    """RFC 8291 ile tek kayıtlık ``aes128gcm`` gövdesi. ``sender_key`` ve ``salt`` yalnızca
    testlerde verilir (her bildirimde yeni geçici anahtar ve rastgele tuz kullanılır)."""
    if len(auth_secret) != 16:
        raise PushError("Tarayıcı doğrulama değeri geçersiz")
    if len(plaintext) + 17 > RECORD_SIZE:
        raise PushError("Bildirim çok uzun")
    receiver = _load_public(ua_public)
    sender = sender_key or ec.generate_private_key(ec.SECP256R1())
    sender_public = _public_raw(sender.public_key())
    salt = salt or os.urandom(16)
    shared = sender.exchange(ec.ECDH(), receiver)
    prk_key = _hmac(auth_secret, shared)
    ikm = _hmac(prk_key, b"WebPush: info\x00" + ua_public + sender_public + b"\x01")
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    ciphertext = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)
    header = salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(sender_public)]) + sender_public
    return header + ciphertext


@dataclass(frozen=True)
class Subscription:
    endpoint: str
    p256dh: bytes
    auth: bytes

    @classmethod
    def parse(
        cls, args: dict[str, Any], *, extra_hosts: tuple[str, ...] = (), allow_http: bool = False
    ) -> Subscription:
        endpoint = str(args.get("endpoint", "")).strip()
        if not endpoint or len(endpoint) > 1000:
            raise PushError("Bildirim adresi geçersiz")
        parts = urlsplit(endpoint)
        host = (parts.hostname or "").lower()
        local = allow_http and parts.scheme == "http" and host in extra_hosts
        if parts.scheme != "https" and not local:
            raise PushError("Bildirim adresi güvenli (https) değil")
        allowed = PUSH_SERVICE_SUFFIXES + extra_hosts
        if not any(host == s or host.endswith("." + s) for s in allowed):
            raise PushError("Bilinmeyen bildirim servisi")
        try:
            p256dh = unb64url(str(args.get("p256dh", "")))
            auth = unb64url(str(args.get("auth", "")))
        except ValueError as exc:
            raise PushError("Tarayıcı anahtarları okunamadı") from exc
        _load_public(p256dh)
        if len(auth) != 16:
            raise PushError("Tarayıcı doğrulama değeri geçersiz")
        return cls(endpoint, p256dh, auth)


class VapidKey:
    """Gönderen kimliği (P-256). Gizli kısım motorun kasasında durur."""

    def __init__(self, key: ec.EllipticCurvePrivateKey) -> None:
        self._key = key

    @classmethod
    def generate(cls) -> VapidKey:
        return cls(ec.generate_private_key(ec.SECP256R1()))

    @classmethod
    def from_private_raw(cls, raw: bytes) -> VapidKey:
        return cls(ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1()))

    def private_raw(self) -> bytes:
        return self._key.private_numbers().private_value.to_bytes(32, "big")

    @property
    def public_raw(self) -> bytes:
        return _public_raw(self._key.public_key())

    @property
    def public_b64url(self) -> str:
        return b64url(self.public_raw)

    def authorization(self, endpoint: str, subject: str, now: float | None = None) -> str:
        """``Authorization: vapid t=<JWT>, k=<açık anahtar>`` (ES256; Apple en çok 1 saat kabul
        eder, 50 dakika kullanılır)."""
        parts = urlsplit(endpoint)
        claims = {
            "aud": f"{parts.scheme}://{parts.netloc}",
            "exp": int((now or time.time()) + 50 * 60),
            "sub": subject,
        }
        header = b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
        body = b64url(json.dumps(claims, separators=(",", ":")).encode())
        signing_input = f"{header}.{body}".encode("ascii")
        der = self._key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        return f"vapid t={header}.{body}.{b64url(signature)}, k={self.public_b64url}"


def build_request(
    vapid: VapidKey,
    subscription: Subscription,
    message: dict[str, Any],
    *,
    subject: str,
    ttl_s: int = 3600,
    urgency: str = "normal",
) -> tuple[dict[str, str], bytes]:
    """Bildirim isteğinin başlıkları ve şifreli gövdesi."""
    plaintext = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(plaintext) > MAX_PAYLOAD:
        raise PushError("Bildirim çok uzun")
    body = encrypt(plaintext, subscription.p256dh, subscription.auth)
    headers = {
        "Authorization": vapid.authorization(subscription.endpoint, subject),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(ttl_s),
        "Urgency": urgency,
    }
    return headers, body
