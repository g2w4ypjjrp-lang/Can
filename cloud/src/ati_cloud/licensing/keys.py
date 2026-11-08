"""Lisans anahtarı: üretim, doğrulama, arama özeti ve zarf şifreleme.

Biçim ``ATI-XXXX-XXXX-XXXX-XXXX``: Crockford Base32 alfabesinden 15 rastgele karakter (2^75
olasılık) + 1 Luhn mod 32 kontrol karakteri. Kontrol karakteri yazım hatalarını sunucuya
gitmeden yakalar. Ayrıntı: ``docs/04-veritabani-semasi.md`` §1.3.

* Arama: ``HMAC-SHA256(pepper, anahtar)``. Pepper ayrı gizli bilgi deposundadır; veritabanı
  sızsa bile anahtarlar doğrulanamaz.
* Yeniden gösterim: AES-256-GCM zarf şifreleme. Her anahtar kendi rastgele veri anahtarıyla
  (DEK) şifrelenir; DEK ana anahtarla (KEK, üretimde KMS) sarılır. Şifreli metin satırın arama
  özetine bağlanır (AAD): başka bir satıra taşınırsa çözülemez.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_INDEX = {ch: i for i, ch in enumerate(ALPHABET)}
# Crockford: karışan harfler okunurken düzeltilir.
_ALIASES = str.maketrans({"I": "1", "L": "1", "O": "0"})
PREFIX = "ATI"
RANDOM_CHARS = 15


class InvalidLicenseKey(ValueError):
    """Biçim veya kontrol karakteri hatalı (sunucuya sorulmadan reddedilir)."""


def check_char(payload: str) -> str:
    """Luhn mod 32 kontrol karakteri."""
    factor = 2
    total = 0
    for ch in reversed(payload):
        addend = factor * _INDEX[ch]
        factor = 1 if factor == 2 else 2
        total += addend // 32 + addend % 32
    return ALPHABET[(32 - total % 32) % 32]


def _luhn_valid(body: str) -> bool:
    factor = 1
    total = 0
    for ch in reversed(body):
        addend = factor * _INDEX[ch]
        factor = 1 if factor == 2 else 2
        total += addend // 32 + addend % 32
    return total % 32 == 0


def format_key(body: str) -> str:
    return f"{PREFIX}-" + "-".join(body[i : i + 4] for i in range(0, 16, 4))


def generate_key() -> str:
    body = "".join(secrets.choice(ALPHABET) for _ in range(RANDOM_CHARS))
    return format_key(body + check_char(body))


def normalize(key: str) -> str:
    """Kullanıcının yazdığı anahtarı 16 karakterlik gövdeye indirger ve doğrular."""
    text = "".join(key.split()).upper().replace("-", "")
    if text.startswith(PREFIX) and len(text) == 19:
        text = text[3:]
    text = text.translate(_ALIASES)
    if len(text) != 16 or any(ch not in _INDEX for ch in text):
        raise InvalidLicenseKey("Lisans anahtarı biçimi hatalı (ATI-XXXX-XXXX-XXXX-XXXX)")
    if not _luhn_valid(text):
        raise InvalidLicenseKey("Lisans anahtarında yazım hatası var (kontrol karakteri tutmuyor)")
    return text


def key_hint(key: str) -> str:
    return f"{PREFIX}-****-****-****-{normalize(key)[12:]}"


class KeyHasher:
    def __init__(self, pepper: bytes) -> None:
        if len(pepper) < 32:
            raise ValueError("Lisans pepper'ı en az 32 bayt olmalı")
        self._pepper = pepper

    def digest(self, key: str) -> bytes:
        return hmac.new(self._pepper, normalize(key).encode("ascii"), hashlib.sha256).digest()


class KeyCipher:
    """AES-256-GCM zarf şifreleme. Biçim: sürüm(1) | KEK kimliği uzunluğu(1) | KEK kimliği |
    sarma nonce(12) | sarılmış DEK(48) | nonce(12) | şifreli metin + etiket."""

    VERSION = 1

    def __init__(self, kek: bytes, kek_id: str) -> None:
        if len(kek) != 32:
            raise ValueError("KEK 32 bayt olmalı (AES-256)")
        if not 1 <= len(kek_id.encode()) <= 64:
            raise ValueError("KEK kimliği 1-64 bayt olmalı")
        self._kek = AESGCM(kek)
        self.kek_id = kek_id

    def encrypt(self, key: str, aad: bytes) -> bytes:
        body = normalize(key).encode("ascii")
        dek = AESGCM.generate_key(bit_length=256)
        wrap_nonce = secrets.token_bytes(12)
        wrapped = self._kek.encrypt(wrap_nonce, dek, b"ati-dek|" + aad)
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(dek).encrypt(nonce, body, b"ati-license-key|" + aad)
        kid = self.kek_id.encode()
        return bytes([self.VERSION, len(kid)]) + kid + wrap_nonce + wrapped + nonce + ciphertext

    def decrypt(self, blob: bytes, aad: bytes) -> str:
        if not blob or blob[0] != self.VERSION:
            raise ValueError("Bilinmeyen şifreleme sürümü")
        kid_len = blob[1]
        kid = blob[2 : 2 + kid_len].decode()
        if kid != self.kek_id:
            raise ValueError(f"Bu anahtar başka bir KEK ile şifrelenmiş ({kid})")
        rest = blob[2 + kid_len :]
        wrap_nonce, wrapped, nonce, ciphertext = rest[:12], rest[12:60], rest[60:72], rest[72:]
        dek = self._kek.decrypt(wrap_nonce, wrapped, b"ati-dek|" + aad)
        body = AESGCM(dek).decrypt(nonce, ciphertext, b"ati-license-key|" + aad).decode("ascii")
        return format_key(body)
