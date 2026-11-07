"""Gizli bilgileri loglardan ve hata mesajlarından temizleme.

İki katman uygulanır:
1. Anahtar adına göre: ``api_key``, ``secret``, ``signature``, ``token``, ``password`` vb.
   alanların değeri tamamen maskelenir.
2. Değer biçimine göre: Binance API anahtarı/imza biçimindeki uzun alfasayısal dizgiler
   ve URL sorgularındaki ``signature=`` / ``listenKey=`` parametreleri maskelenir.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

MASK = "***"

_SENSITIVE_KEY_RE = re.compile(
    r"(api[_-]?key|secret|signature|token|password|passwd|authorization|listen[_-]?key|"
    r"private[_-]?key|totp|cookie|session)",
    re.IGNORECASE,
)
# Binance API anahtarları ve HMAC imzaları 64 karakterlik alfasayısal dizgilerdir.
_LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9]{48,}\b")
_QUERY_SECRET_RE = re.compile(
    r"((?:signature|listenKey|apiKey|api_key|token)=)[^&\s\"']+", re.IGNORECASE
)
_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE)


def is_sensitive_key(key: str) -> bool:
    return bool(_SENSITIVE_KEY_RE.search(key))


def redact_text(text: str) -> str:
    text = _QUERY_SECRET_RE.sub(lambda m: m.group(1) + MASK, text)
    text = _BEARER_RE.sub(lambda m: m.group(1) + MASK, text)
    return _LONG_TOKEN_RE.sub(MASK, text)


def redact(value: Any, *, _depth: int = 0) -> Any:
    if _depth > 8:
        return value
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            k: (
                MASK if isinstance(k, str) and is_sensitive_key(k) else redact(v, _depth=_depth + 1)
            )
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return type(value)(redact(v, _depth=_depth + 1) for v in value)
    return value
