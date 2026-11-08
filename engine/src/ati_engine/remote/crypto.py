"""Uzaktan kontrol kriptografisi.

* Motor kimliği: Ed25519. Gizli anahtar motorun şifreli kasasında tutulur.
* Telefon anahtarları: P-256 (Secure Enclave). İmzalar ham ``r‖s`` (64 bayt); CryptoKit'in
  ``rawRepresentation`` biçimidir.
* İmza, gönderilen JSON metninin kendisi üzerine atılır (``{"p": metin, "s": imza}``); taraflar
  arası kanonikleştirme gerekmez.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

ID_BYTES = 16


class SignatureError(ValueError):
    """İmza veya anahtar geçersiz."""


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def unb64(text: str) -> bytes:
    try:
        return base64.b64decode(text, validate=True)
    except (ValueError, TypeError) as exc:
        raise SignatureError("base64 geçersiz") from exc


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64url(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(text + padding)
    except (ValueError, TypeError) as exc:
        raise SignatureError("base64url geçersiz") from exc


def key_id(public_raw: bytes) -> str:
    """Kimlik: açık anahtarın SHA-256 özetinin ilk 16 baytı (onaltılık)."""
    return hashlib.sha256(public_raw).digest()[:ID_BYTES].hex()


# --- Motor kimliği (Ed25519) ---------------------------------------------------------------


class EngineIdentity:
    def __init__(self, private: Ed25519PrivateKey) -> None:
        self._private = private
        self.public_raw = private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.engine_id = key_id(self.public_raw)

    @classmethod
    def generate(cls) -> EngineIdentity:
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_private_raw(cls, raw: bytes) -> EngineIdentity:
        return cls(Ed25519PrivateKey.from_private_bytes(raw))

    def private_raw(self) -> bytes:
        return self._private.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )

    def sign(self, data: bytes) -> bytes:
        return self._private.sign(data)

    def signed(self, payload: dict[str, Any]) -> dict[str, str]:
        """İmzalı mesaj: ``{"p": JSON metni, "s": imza}``."""
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return {"p": text, "s": b64(self.sign(text.encode("utf-8")))}

    def __repr__(self) -> str:
        return f"EngineIdentity({self.engine_id})"


def verify_ed25519(public_raw: bytes, signature: bytes, data: bytes) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(public_raw).verify(signature, data)
    except (InvalidSignature, ValueError) as exc:
        raise SignatureError("Ed25519 imzası geçersiz") from exc


# --- Telefon anahtarları (P-256) -------------------------------------------------------------


def load_p256(x963: bytes) -> ec.EllipticCurvePublicKey:
    if len(x963) != 65 or x963[0] != 0x04:
        raise SignatureError("P-256 açık anahtarı X9.63 sıkıştırılmamış biçimde olmalı")
    try:
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), x963)
    except ValueError as exc:
        raise SignatureError("P-256 açık anahtarı geçersiz") from exc


def verify_p256(x963: bytes, signature_raw: bytes, data: bytes) -> None:
    """Ham ``r‖s`` biçimindeki ECDSA/SHA-256 imzasını doğrular."""
    if len(signature_raw) != 64:
        raise SignatureError("P-256 imzası 64 bayt (r‖s) olmalı")
    r = int.from_bytes(signature_raw[:32], "big")
    s = int.from_bytes(signature_raw[32:], "big")
    try:
        load_p256(x963).verify(encode_dss_signature(r, s), data, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise SignatureError("P-256 imzası geçersiz") from exc


def hmac_proof(secret: bytes, data: bytes) -> bytes:
    return hmac.new(secret, data, hashlib.sha256).digest()


def proof_matches(secret: bytes, data: bytes, proof: bytes) -> bool:
    return hmac.compare_digest(hmac_proof(secret, data), proof)


def open_signed(message: Any) -> tuple[str, bytes, dict[str, Any]]:
    """``{"p", "s"}`` mesajını ayrıştırır (imzayı DOĞRULAMAZ). Metin, imza ve içerik döner."""
    if not isinstance(message, dict):
        raise SignatureError("mesaj nesne olmalı")
    text = message.get("p")
    sig = message.get("s")
    if not isinstance(text, str) or not isinstance(sig, str) or len(text) > 64_000:
        raise SignatureError("mesaj biçimi geçersiz")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SignatureError("içerik JSON değil") from exc
    if not isinstance(payload, dict):
        raise SignatureError("içerik nesne olmalı")
    return text, unb64(sig), payload


def relay_hello_text(role: str, *parts: str) -> bytes:
    return "|".join(("ati-relay-hello", role, *parts)).encode("utf-8")
