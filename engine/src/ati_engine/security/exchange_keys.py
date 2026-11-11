"""Borsa API anahtarlarının saklanması ve doğrulanması.

* Anahtarlar yalnızca şifreli kasada (Windows'ta DPAPI) tutulur; günlüklere, API yanıtlarına ve
  hata mesajlarına yazılmaz (yalnızca son 4 karakter gösterilir).
* **Demo Trading (test ağı)** anahtarları Demo modunda kullanılır.
* **Gerçek hesap (canlı)** anahtarı kullanıcının onayıyla (G1, 2026-11-11) açıldı. Saklanmadan
  önce ``/sapi/v1/account/apiRestrictions`` ile yetkileri okunur: **para çekme** veya transfer
  yetkisi açıksa ya da işlem yetkisi yoksa anahtar REDDEDİLİR ve saklanmaz (bkz.
  ``binance_key_policy``). İki ortamın anahtarları kasada ayrı adlarla tutulur.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import SecretStr

from ati_engine.core.models import Market
from ati_engine.exchange.rate_limit import Priority
from ati_engine.exchange.rest import BinanceRestClient
from ati_engine.exchange.signing import HmacSigner, RequestSigner
from ati_engine.security.binance_key_policy import KeyPolicyVerdict, evaluate_api_restrictions
from ati_engine.security.vault import SecretVault

KeyEnvironment = Literal["testnet", "live"]
_KEY_RE = re.compile(r"^[A-Za-z0-9]{16,128}$")


@dataclass(frozen=True)
class StoredKey:
    environment: KeyEnvironment
    market: Market
    api_key_hint: str  # yalnızca son 4 karakter


def _hint(api_key: str) -> str:
    return f"…{api_key[-4:]}"


class ExchangeKeyStore:
    def __init__(self, vault: SecretVault) -> None:
        self._vault = vault

    @staticmethod
    def _names(environment: KeyEnvironment, market: Market) -> tuple[str, str]:
        base = f"binance.{environment}.{market.value}"
        return f"{base}.api_key", f"{base}.secret"

    @staticmethod
    def _check_environment(environment: str) -> None:
        if environment not in ("testnet", "live"):
            raise ValueError("Ortam 'testnet' ya da 'live' olmalı")

    async def store(
        self,
        environment: KeyEnvironment,
        market: Market,
        api_key: str | SecretStr,
        secret: str | SecretStr,
    ) -> StoredKey:
        self._check_environment(environment)
        key = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        sec = secret.get_secret_value() if isinstance(secret, SecretStr) else secret
        key, sec = key.strip(), sec.strip()
        if not _KEY_RE.match(key) or not _KEY_RE.match(sec):
            raise ValueError("API anahtarı ve gizli anahtar 16-128 harf/rakam olmalı")
        key_name, secret_name = self._names(environment, market)
        await self._vault.put(key_name, key)
        await self._vault.put(secret_name, sec)
        return StoredKey(environment, market, _hint(key))

    async def load(
        self, environment: KeyEnvironment, market: Market
    ) -> tuple[str, RequestSigner] | None:
        self._check_environment(environment)
        key_name, secret_name = self._names(environment, market)
        key = await self._vault.get(key_name)
        secret = await self._vault.get(secret_name)
        if key is None or secret is None:
            return None
        return key.get_secret_value(), HmacSigner(secret.get_secret_value())

    async def info(self, environment: KeyEnvironment, market: Market) -> StoredKey | None:
        loaded = await self.load(environment, market)
        return StoredKey(environment, market, _hint(loaded[0])) if loaded else None

    async def delete(self, environment: KeyEnvironment, market: Market) -> bool:
        # Silme her ortamda serbesttir (eski bir sürümden kalmış olabilecek anahtar dahil).
        key_name, secret_name = self._names(environment, market)
        removed = await self._vault.delete(key_name)
        return await self._vault.delete(secret_name) or removed


@dataclass(frozen=True)
class KeyCheck:
    ok: bool
    message: str
    can_trade: bool | None = None


async def verify_key(
    rest: BinanceRestClient, market: Market, *, help_text: str | None = None
) -> KeyCheck:
    """Anahtarı imzalı salt-okunur bir istekle dener (bakiye/hesap). Emir göndermez."""
    help_text = help_text or KEY_HELP
    try:
        if market is Market.SPOT:
            data: Any = await rest.request(
                "GET",
                "/api/v3/account",
                params={"omitZeroBalances": "true"},
                weight=20,
                priority=Priority.HIGH,
                signed=True,
            )
            can_trade = bool(data.get("canTrade")) if isinstance(data, dict) else None
            return KeyCheck(True, "Anahtar doğrulandı (spot hesap okundu)", can_trade)
        await rest.request(
            "GET", "/fapi/v3/balance", params={}, weight=5, priority=Priority.HIGH, signed=True
        )
        return KeyCheck(True, "Anahtar doğrulandı (futures bakiyesi okundu)", None)
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code in (-2014, -2015, -1022):
            return KeyCheck(False, f"Binance anahtarı reddetti ({code}). {help_text}")
        if code == -1021:
            return KeyCheck(
                False,
                "Bilgisayarın saati Binance'ten farklı (-1021). Windows Ayarlar → Saat ve dil → "
                "'Saati otomatik ayarla'yı açıp 'Şimdi eşitle'ye basın.",
            )
        if code is not None:
            return KeyCheck(False, f"Binance hata verdi ({code}): {exc}")
        return KeyCheck(
            False,
            f"Binance'e ulaşılamadı ({type(exc).__name__}). İnternet bağlantısını kontrol edin.",
        )


# Gerçek hesap anahtarı reddinin olası nedenleri.
LIVE_KEY_HELP = (
    "Anahtar binance.com → Hesap → API Yönetimi'nde oluşturulmalı (Demo Trading anahtarı gerçek "
    "hesapta çalışmaz). Gizli anahtarı eksiksiz yapıştırın. IP kısıtı koyduysanız bu bilgisayarın "
    "IP adresini ekleyin."
)

# Anahtar reddinin olası nedenleri (en sık görülenden başlayarak).
KEY_HELP = (
    "Anahtar demo.binance.com → API Yönetimi'nde (Demo Trading) oluşturulmalı; gerçek hesap "
    "anahtarı ve eski testnet.binance.vision anahtarı burada çalışmaz. Gizli anahtarı eksiksiz "
    "yapıştırın. Anahtara IP kısıtı koyduysanız bu bilgisayarın IP adresini ekleyin ya da kısıtı "
    "kaldırın."
)


async def check_live_key_policy(
    rest: BinanceRestClient, *, markets: list[Market], trading_required: bool = True
) -> KeyPolicyVerdict:
    """Canlı anahtarın yetkilerini okur ve değerlendirir (para çekme açıksa REDDEDİLİR).
    Canlı anahtar kabulünün ön koşuludur."""
    restrictions = await rest.request(
        "GET",
        "/sapi/v1/account/apiRestrictions",
        params={},
        weight=1,
        priority=Priority.HIGH,
        signed=True,
    )
    if not isinstance(restrictions, dict):
        restrictions = {}
    return evaluate_api_restrictions(
        restrictions, required_markets=markets, trading_required=trading_required
    )
