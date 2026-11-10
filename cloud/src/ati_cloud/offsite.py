"""Sunucu dışı yedek: gece alınan veritabanı yedeği şifrelenip S3 uyumlu depoya (Cloudflare R2)
yüklenir (``ati-cloud-offsite``).

* Şifreleme sunucuda yapılır (AES-256-GCM); depo sağlayıcısı içeriği okuyamaz. Anahtar
  ``ATI_OFFSITE_ENCRYPTION_KEY`` (``bulut.env``); bulut.env ile birlikte sunucu dışında saklanmalı,
  yoksa yedek açılamaz.
* Yükleme AWS imza sürüm 4 (SigV4) ile yapılır; ek kütüphane gerekmez. R2 bölgesi ``auto``.
* Saklama süresi depoda yaşam döngüsü kuralıyla ayarlanır (ör. 30 gün sonra sil).

Dosya biçimi: ``ATIB1`` (5 bayt) + 12 bayt nonce + şifreli içerik ve etiket. İlişkili veri dosya
adıdır: başka bir yedeğin adıyla yeniden adlandırılan dosya açılmaz.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

MAGIC = b"ATIB1"


class OffsiteSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATI_OFFSITE_", extra="ignore")

    endpoint: str = ""  # ör. https://<hesap>.r2.cloudflarestorage.com
    bucket: str = ""
    access_key: str = ""
    secret_key: SecretStr = SecretStr("")
    region: str = "auto"
    encryption_key: SecretStr = SecretStr("")  # base64, 32 bayt
    prefix: str = "yedekler/"

    @property
    def configured(self) -> bool:
        return bool(
            self.endpoint and self.bucket and self.access_key and self.secret_key.get_secret_value()
        )


def _key(settings: OffsiteSettings) -> bytes:
    raw = base64.b64decode(settings.encryption_key.get_secret_value() or "", validate=True)
    if len(raw) != 32:
        raise ValueError("ATI_OFFSITE_ENCRYPTION_KEY 32 baytlık base64 olmalı")
    return raw


def encrypt(data: bytes, key: bytes, name: str) -> bytes:
    nonce = os.urandom(12)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, data, name.encode())


def decrypt(blob: bytes, key: bytes, name: str) -> bytes:
    if not blob.startswith(MAGIC):
        raise ValueError("Bu dosya bir ATI şifreli yedeği değil")
    nonce, body = blob[5:17], blob[17:]
    return AESGCM(key).decrypt(nonce, body, name.encode())


# --- AWS imza sürüm 4 ------------------------------------------------------------------------


def _hmac(key: bytes, text: str) -> bytes:
    return hmac.new(key, text.encode(), hashlib.sha256).digest()


def sign_v4(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    payload_hash: str,
    access_key: str,
    secret_key: str,
    region: str,
    now: datetime,
    service: str = "s3",
) -> dict[str, str]:
    """İstek başlıklarına ``x-amz-date``, ``x-amz-content-sha256`` ve ``Authorization`` ekler."""
    parts = urlsplit(url)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    day = amz_date[:8]
    all_headers = {k.lower(): v.strip() for k, v in headers.items()}
    all_headers["host"] = parts.netloc
    all_headers["x-amz-date"] = amz_date
    all_headers["x-amz-content-sha256"] = payload_hash
    signed = sorted(all_headers)
    canonical_query = "&".join(
        sorted(
            f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}"
            for k, _, v in (p.partition("=") for p in parts.query.split("&") if p)
        )
    )
    canonical = "\n".join(
        [
            method,
            quote(parts.path or "/", safe="/-_.~"),
            canonical_query,
            "".join(f"{h}:{all_headers[h]}\n" for h in signed),
            ";".join(signed),
            payload_hash,
        ]
    )
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()]
    )
    k = _hmac(
        _hmac(_hmac(_hmac(f"AWS4{secret_key}".encode(), day), region), service), "aws4_request"
    )
    signature = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
    result = {k: v for k, v in all_headers.items() if k != "host"}
    result["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={';'.join(signed)}, Signature={signature}"
    )
    return result


def upload(path: Path, settings: OffsiteSettings, *, client: httpx.Client | None = None) -> str:
    """Dosyayı şifreleyip yükler; depodaki anahtarı döndürür."""
    if not settings.configured:
        raise ValueError("Sunucu dışı yedek ayarlı değil (yonet.ps1 yedek-bulut-ayarla)")
    name = f"{path.name}.enc"
    blob = encrypt(path.read_bytes(), _key(settings), name)
    object_key = f"{settings.prefix}{name}"
    url = f"{settings.endpoint.rstrip('/')}/{settings.bucket}/{quote(object_key, safe='/-_.~')}"
    headers = sign_v4(
        method="PUT",
        url=url,
        headers={"content-type": "application/octet-stream"},
        payload_hash=hashlib.sha256(blob).hexdigest(),
        access_key=settings.access_key,
        secret_key=settings.secret_key.get_secret_value(),
        region=settings.region,
        now=datetime.now(UTC),
    )
    own = client is None
    http = client or httpx.Client(timeout=120)
    try:
        response = http.put(url, content=blob, headers=headers)
    finally:
        if own:
            http.close()
    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"Yükleme reddedildi (HTTP {response.status_code}): {response.text[:200]}"
        )
    return object_key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ati-cloud-offsite", description="Sunucu dışı yedek")
    sub = parser.add_subparsers(dest="command", required=True)
    up = sub.add_parser("upload", help="Yedeği şifreleyip depoya yükle")
    up.add_argument("file", type=Path)
    dec = sub.add_parser("decrypt", help="İndirilen şifreli yedeği aç (geri yükleme için)")
    dec.add_argument("file", type=Path)
    dec.add_argument("out", type=Path)
    sub.add_parser("new-key", help="Yeni şifreleme anahtarı üret (base64)")
    args = parser.parse_args(argv)
    if args.command == "new-key":
        print(base64.b64encode(os.urandom(32)).decode())
        return 0
    settings = OffsiteSettings()
    try:
        if args.command == "upload":
            key = upload(args.file, settings)
            print(f"Yüklendi: {settings.bucket}/{key}")
        else:
            data = decrypt(args.file.read_bytes(), _key(settings), args.file.name)
            args.out.write_bytes(data)
            print(f"Açıldı: {args.out}")
    except InvalidTag:
        print("HATA: şifreleme anahtarı yanlış ya da dosya bozuk/değiştirilmiş", file=sys.stderr)
        return 1
    except (ValueError, RuntimeError, OSError, httpx.HTTPError) as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 1
    return 0
