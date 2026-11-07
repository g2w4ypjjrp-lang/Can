"""Binance istek imzalama.

İmza yükü, sorgu dizesi ile (varsa) gövdenin ayırıcısız birleşimidir. ASCII dışı karakterler
imzalamadan ÖNCE yüzde-kodlanır (percent-encode). Desteklenen anahtar türleri:

* **HMAC-SHA256:** imza onaltılık (hex) dizgidir.
* **Ed25519 (Binance'in önerdiği):** imza base64 dizgidir; URL'ye eklenirken yüzde-kodlanır.
  Gizli anahtar hiçbir zaman Binance'e gönderilmez; yalnızca açık anahtar Binance'e yüklenir.

Gerçek emir gönderen kod Aşama 10'dadır; bu modül yalnızca imza üretir.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.parse import quote

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from ati_engine.core.models import format_decimal

_SAFE = "-_.~"


def _encode_value(value: Any) -> str:
    from decimal import Decimal

    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, Decimal):
        text = format_decimal(value)
    else:
        text = str(value)
    return quote(text, safe=_SAFE)


def build_query(params: Mapping[str, Any]) -> str:
    """Parametreleri verilen sırada ``a=1&b=2`` biçiminde yüzde-kodlanmış dizgiye çevirir.

    ``None`` değerli parametreler atlanır.
    """
    return "&".join(
        f"{quote(str(key), safe=_SAFE)}={_encode_value(value)}"
        for key, value in params.items()
        if value is not None
    )


class RequestSigner(Protocol):
    @property
    def kind(self) -> str: ...

    def sign(self, payload: str) -> str: ...


class HmacSigner:
    kind = "hmac"

    def __init__(self, secret: str) -> None:
        if not secret:
            raise ValueError("HMAC gizli anahtarı boş olamaz")
        self._secret = secret.encode("utf-8")

    def sign(self, payload: str) -> str:
        return hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def __repr__(self) -> str:
        return "HmacSigner(***)"


class Ed25519Signer:
    kind = "ed25519"

    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._key = private_key

    @classmethod
    def from_pem(cls, pem: bytes, password: bytes | None = None) -> Ed25519Signer:
        key = load_pem_private_key(pem, password=password)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("PEM dosyası bir Ed25519 özel anahtarı içermiyor")
        return cls(key)

    def sign(self, payload: str) -> str:
        return base64.b64encode(self._key.sign(payload.encode("utf-8"))).decode("ascii")

    def __repr__(self) -> str:
        return "Ed25519Signer(***)"


def signed_query(params: Mapping[str, Any], signer: RequestSigner) -> str:
    """İmzalı sorgu dizesi üretir: ``<parametreler>&signature=<imza>``."""
    payload = build_query(params)
    signature = quote(signer.sign(payload), safe="")
    return f"{payload}&signature={signature}" if payload else f"signature={signature}"
