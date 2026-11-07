"""Gizli bilgi kasası (Binance API anahtarları, yerel API belirteci, lisans kirası).

Şifreleme sağlayıcıları:

* ``DpapiCipher`` (Windows, üretim): Windows Data Protection API, veriyi oturum açmış
  Windows kullanıcısının kimlik bilgilerine bağlı bir anahtarla şifreler. Şifreli veri
  başka bir kullanıcı hesabına veya başka bir bilgisayara kopyalanırsa çözülemez.
  Ek olarak gizli bilginin adı "entropy" olarak verilir; böylece bir kayıttaki şifreli
  veri başka bir kaydın yerine taşınamaz.
* ``AesGcmCipher`` (geliştirme/CI ve ileride parola tabanlı yedek): AES-256-GCM,
  her şifrelemede rastgele 96 bit nonce, gizli bilgi adı ek doğrulanmış veri (AAD).

Kasa, düz metni asla loglamaz; ``SecretStr`` döndürür.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

if TYPE_CHECKING:
    from ati_engine.storage.database import Database

_FORMAT_VERSION = 1


class VaultError(RuntimeError):
    pass


class SecretCipher(Protocol):
    @property
    def provider(self) -> str: ...

    def encrypt(self, plaintext: bytes, *, aad: bytes) -> bytes: ...

    def decrypt(self, ciphertext: bytes, *, aad: bytes) -> bytes: ...


class AesGcmCipher:
    provider = "aesgcm"

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("AES-256 anahtarı 32 bayt olmalı")
        self._aead = AESGCM(key)

    @staticmethod
    def generate_key() -> bytes:
        return AESGCM.generate_key(bit_length=256)

    def encrypt(self, plaintext: bytes, *, aad: bytes) -> bytes:
        nonce = os.urandom(12)
        return bytes([_FORMAT_VERSION]) + nonce + self._aead.encrypt(nonce, plaintext, aad)

    def decrypt(self, ciphertext: bytes, *, aad: bytes) -> bytes:
        if len(ciphertext) < 1 + 12 + 16 or ciphertext[0] != _FORMAT_VERSION:
            raise VaultError("Şifreli veri biçimi tanınmadı")
        nonce, body = ciphertext[1:13], ciphertext[13:]
        try:
            return self._aead.decrypt(nonce, body, aad)
        except InvalidTag as exc:
            raise VaultError("Şifreli veri doğrulanamadı (bozulmuş veya yanlış kayıt)") from exc


class DpapiCipher:
    """Windows DPAPI (CryptProtectData / CryptUnprotectData) sarmalayıcısı."""

    provider = "dpapi"

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise VaultError("DPAPI yalnızca Windows'ta kullanılabilir")

    def encrypt(self, plaintext: bytes, *, aad: bytes) -> bytes:
        return _dpapi_call(plaintext, aad, protect=True)

    def decrypt(self, ciphertext: bytes, *, aad: bytes) -> bytes:
        return _dpapi_call(ciphertext, aad, protect=False)


def _dpapi_call(data: bytes, entropy: bytes, *, protect: bool) -> bytes:  # pragma: no cover
    if sys.platform != "win32":
        raise VaultError("DPAPI yalnızca Windows'ta kullanılabilir")
    import ctypes
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def to_blob(raw: bytes) -> tuple[DataBlob, ctypes.Array[ctypes.c_char]]:
        buffer = ctypes.create_string_buffer(raw, len(raw))
        return DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    cryptprotect_ui_forbidden = 0x01

    in_blob, _in_buf = to_blob(data)
    entropy_blob, _ent_buf = to_blob(entropy)
    out_blob = DataBlob()
    func = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = func(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        cryptprotect_ui_forbidden,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise VaultError(f"DPAPI işlemi başarısız (hata {ctypes.get_last_error()})")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def load_or_create_dev_key(path: Path) -> bytes:
    """Windows dışı ortamlar için anahtar dosyası (yalnızca geliştirme ve CI).

    Üretimde Windows'ta DPAPI kullanılır; bu dosya oluşturulmaz.
    """
    if path.exists():
        key = path.read_bytes()
        if len(key) != 32:
            raise VaultError("Geliştirme anahtar dosyası bozuk")
        return key
    key = AesGcmCipher.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(key)
    return key


def default_cipher(data_dir: Path) -> SecretCipher:
    if sys.platform == "win32":
        return DpapiCipher()
    return AesGcmCipher(load_or_create_dev_key(data_dir / "runtime" / "dev-vault.key"))


class SecretVault:
    def __init__(self, db: Database, cipher: SecretCipher) -> None:
        self._db = db
        self._cipher = cipher

    @staticmethod
    def _aad(name: str) -> bytes:
        return f"ati-secret:v1:{name}".encode()

    @staticmethod
    def _check_name(name: str) -> None:
        if not name or len(name) > 128 or not all(c.isalnum() or c in "._-:" for c in name):
            raise ValueError("Geçersiz gizli bilgi adı")

    async def put(self, name: str, value: str | SecretStr) -> None:
        self._check_name(name)
        plain = value.get_secret_value() if isinstance(value, SecretStr) else value
        ciphertext = self._cipher.encrypt(plain.encode("utf-8"), aad=self._aad(name))
        await self._db.execute(
            """
            INSERT INTO secrets (name, provider, ciphertext, created_at, updated_at)
            VALUES (?, ?, ?, strftime('%s','now') * 1000, strftime('%s','now') * 1000)
            ON CONFLICT(name) DO UPDATE SET
                provider = excluded.provider,
                ciphertext = excluded.ciphertext,
                updated_at = excluded.updated_at
            """,
            (name, self._cipher.provider, ciphertext),
        )

    async def get(self, name: str) -> SecretStr | None:
        self._check_name(name)
        row = await self._db.fetchone(
            "SELECT provider, ciphertext FROM secrets WHERE name = ?", (name,)
        )
        if row is None:
            return None
        provider, ciphertext = row
        if provider != self._cipher.provider:
            raise VaultError(
                f"'{name}' farklı bir sağlayıcıyla ({provider}) şifrelenmiş; yeniden girilmeli"
            )
        plain = self._cipher.decrypt(bytes(ciphertext), aad=self._aad(name))
        return SecretStr(plain.decode("utf-8"))

    async def delete(self, name: str) -> bool:
        self._check_name(name)
        changed = await self._db.execute("DELETE FROM secrets WHERE name = ?", (name,))
        return changed > 0

    async def names(self) -> list[str]:
        rows = await self._db.fetchall("SELECT name FROM secrets ORDER BY name")
        return [str(r[0]) for r in rows]
