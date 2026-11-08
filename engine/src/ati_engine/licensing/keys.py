"""Lisans anahtarı biçim denetimi (sunucuya gitmeden yazım hatası yakalama).

Biçim ``ATI-XXXX-XXXX-XXXX-XXXX``: Crockford Base32, son karakter Luhn mod 32 kontrolü.
Bulut tarafıyla aynı kurallar; ortak test vektörleri:
``shared/protocol/test-vectors/license-v1.json``.
"""

from __future__ import annotations

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_INDEX = {ch: i for i, ch in enumerate(ALPHABET)}
_ALIASES = str.maketrans({"I": "1", "L": "1", "O": "0"})


class InvalidLicenseKey(ValueError):
    pass


def _luhn_valid(body: str) -> bool:
    factor = 1
    total = 0
    for ch in reversed(body):
        addend = factor * _INDEX[ch]
        factor = 1 if factor == 2 else 2
        total += addend // 32 + addend % 32
    return total % 32 == 0


def normalize(key: str) -> str:
    text = "".join(key.split()).upper().replace("-", "")
    if text.startswith("ATI") and len(text) == 19:
        text = text[3:]
    text = text.translate(_ALIASES)
    if len(text) != 16 or any(ch not in _INDEX for ch in text):
        raise InvalidLicenseKey("Lisans anahtarı biçimi hatalı (ATI-XXXX-XXXX-XXXX-XXXX)")
    if not _luhn_valid(text):
        raise InvalidLicenseKey("Lisans anahtarında yazım hatası var; lütfen kontrol edin")
    return text


def format_key(body: str) -> str:
    return "ATI-" + "-".join(body[i : i + 4] for i in range(0, 16, 4))


def key_hint(key: str) -> str:
    return f"ATI-****-****-****-{normalize(key)[12:]}"
