"""Uzaktan kontrol kriptografisi.

* Motor kimliği: Ed25519. Gizli anahtar motorun şifreli kasasında tutulur.
* Telefon anahtarları: P-256 (Secure Enclave). İmzalar ham ``r‖s`` (64 bayt); CryptoKit'in
  ``rawRepresentation`` biçimidir.
* İmza, gönderilen JSON metninin kendisi üzerine atılır (``{"p": metin, "s": imza}``); taraflar
  arası kanonikleştirme gerekmez.
* Uçtan uca şifreleme (Aşama 18): imzalı mesaj, alıcının P-256 anahtar anlaşması anahtarına
  şifrelenir. Her mesajda yeni geçici anahtar → ECDH → HKDF-SHA256 → AES-256-GCM. Bağlam
  (yön, motor ve cihaz kimliği) hem HKDF ``info``'sunda hem GCM ek verisindedir: aktarma
  servisi mesajı başka cihaza/yöne yönlendirirse çözülemez. Telefonun anahtarı Secure
  Enclave'dedir (CryptoKit Secure Enclave'de P-256 anlaşmasını destekler, X25519'u desteklemez).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

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


# --- Uçtan uca şifreleme (P-256 ECDH + HKDF-SHA256 + AES-256-GCM) -------------------------------

ENVELOPE_VERSION = 1
NONCE_BYTES = 12
TAG_BYTES = 16
MAX_SEALED_BYTES = 96_000
Direction = Literal["e2d", "d2e"]  # motor → cihaz, cihaz → motor


class SealError(ValueError):
    """Şifreli zarf açılamadı (biçim, anahtar, bağlam veya bütünlük)."""


def p256_x963(public: ec.EllipticCurvePublicKey) -> bytes:
    return public.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


class KeyAgreement:
    """P-256 anahtar anlaşması anahtarı. Motorun anahtarı şifreli kasada tutulur."""

    def __init__(self, private: ec.EllipticCurvePrivateKey) -> None:
        if not isinstance(private.curve, ec.SECP256R1):
            raise ValueError("P-256 anahtarı gerekli")
        self._private = private
        self.public_x963 = p256_x963(private.public_key())

    @classmethod
    def generate(cls) -> KeyAgreement:
        return cls(ec.generate_private_key(ec.SECP256R1()))

    @classmethod
    def from_private_raw(cls, raw: bytes) -> KeyAgreement:
        if len(raw) != 32:
            raise ValueError("P-256 gizli anahtarı 32 bayt olmalı")
        return cls(ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1()))

    def private_raw(self) -> bytes:
        return self._private.private_numbers().private_value.to_bytes(32, "big")

    def shared(self, peer_x963: bytes) -> bytes:
        """ECDH ortak sırrı (x koordinatı, 32 bayt; CryptoKit ``SharedSecret`` ile aynı)."""
        try:
            return self._private.exchange(ec.ECDH(), load_p256(peer_x963))
        except SignatureError as exc:
            raise SealError("karşı tarafın anahtarı geçersiz") from exc

    def __repr__(self) -> str:
        return f"KeyAgreement({key_id(self.public_x963)})"


def channel_info(direction: Direction, engine_id: str, device_id: str) -> bytes:
    return f"ati-remote-v1|{direction}|{engine_id}|{device_id}".encode()


def _envelope_key(
    shared: bytes, ephemeral_x963: bytes, recipient_x963: bytes, info: bytes
) -> bytes:
    hkdf = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=ephemeral_x963 + recipient_x963, info=info
    )
    return hkdf.derive(shared)


def seal(
    recipient_x963: bytes,
    plaintext: bytes,
    info: bytes,
    *,
    ephemeral: KeyAgreement | None = None,
    nonce: bytes | None = None,
) -> dict[str, Any]:
    """Alıcıya şifreli zarf: ``{"v":1, "e": geçici açık anahtar, "n": nonce, "c": şifreli+etiket}``.
    ``ephemeral`` ve ``nonce`` yalnızca test vektörleri içindir; normalde her mesajda yenidir."""
    eph = ephemeral or KeyAgreement.generate()
    iv = nonce if nonce is not None else secrets.token_bytes(NONCE_BYTES)
    if len(iv) != NONCE_BYTES:
        raise ValueError("nonce 12 bayt olmalı")
    key = _envelope_key(eph.shared(recipient_x963), eph.public_x963, recipient_x963, info)
    return {
        "v": ENVELOPE_VERSION,
        "e": b64(eph.public_x963),
        "n": b64(iv),
        "c": b64(AESGCM(key).encrypt(iv, plaintext, info)),
    }


def is_sealed(message: Any) -> bool:
    return isinstance(message, dict) and {"v", "e", "n", "c"} <= set(message)


def open_sealed(recipient: KeyAgreement, envelope: Any, info: bytes) -> bytes:
    """Zarfı açar; biçim, anahtar, bağlam (``info``) veya bütünlük hatasında ``SealError``."""
    if not is_sealed(envelope) or envelope.get("v") != ENVELOPE_VERSION:
        raise SealError("şifreli zarf bekleniyordu")
    parts = (envelope["e"], envelope["n"], envelope["c"])
    if not all(isinstance(x, str) for x in parts) or len(envelope["c"]) > MAX_SEALED_BYTES:
        raise SealError("zarf biçimi geçersiz")
    try:
        ephemeral, iv, sealed = (unb64(x) for x in parts)
    except SignatureError as exc:
        raise SealError("zarf base64 geçersiz") from exc
    if len(iv) != NONCE_BYTES or len(sealed) < TAG_BYTES:
        raise SealError("zarf biçimi geçersiz")
    key = _envelope_key(recipient.shared(ephemeral), ephemeral, recipient.public_x963, info)
    try:
        return AESGCM(key).decrypt(iv, sealed, info)
    except InvalidTag as exc:
        raise SealError(
            "zarf çözülemedi (yanlış anahtar, bağlam veya değiştirilmiş içerik)"
        ) from exc


def seal_json(recipient_x963: bytes, message: dict[str, Any], info: bytes) -> dict[str, Any]:
    text = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    return seal(recipient_x963, text.encode("utf-8"), info)


def open_json(recipient: KeyAgreement, envelope: Any, info: bytes) -> dict[str, Any]:
    try:
        value = json.loads(open_sealed(recipient, envelope, info))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise SealError("zarf içeriği JSON değil") from exc
    if not isinstance(value, dict):
        raise SealError("zarf içeriği nesne olmalı")
    return value
