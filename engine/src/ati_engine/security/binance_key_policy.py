"""Binance API anahtar yetki politikası.

Motor, kullanıcının girdiği anahtarın yetkilerini ``GET /sapi/v1/account/apiRestrictions``
uç noktasından okur (imzalı istek Aşama 2/10'da eklenir) ve bu modül ile değerlendirir.

Kurallar (en az yetki ilkesi):
* Para çekme yetkisi (``enableWithdrawals``) AÇIKSA anahtar REDDEDİLİR.
* Hesaplar arası/iç transfer yetkileri açıksa anahtar REDDEDİLİR; bu yetkiler fonların
  başka hesaplara taşınmasına izin verir.
* Okuma yetkisi yoksa REDDEDİLİR.
* İstenen piyasa için işlem yetkisi yoksa (gerçek/test işlem modunda) REDDEDİLİR.
* IP kısıtlaması yoksa, marjin/opsiyon/portföy marjini yetkileri açıksa UYARI verilir.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ati_engine.core.models import Market


class PolicyLevel(StrEnum):
    BLOCK = "block"
    WARN = "warn"


@dataclass(frozen=True)
class PolicyFinding:
    level: PolicyLevel
    code: str
    message: str


@dataclass(frozen=True)
class KeyPolicyVerdict:
    findings: tuple[PolicyFinding, ...] = field(default_factory=tuple)

    @property
    def accepted(self) -> bool:
        return not any(f.level is PolicyLevel.BLOCK for f in self.findings)

    @property
    def blocking(self) -> tuple[PolicyFinding, ...]:
        return tuple(f for f in self.findings if f.level is PolicyLevel.BLOCK)

    @property
    def warnings(self) -> tuple[PolicyFinding, ...]:
        return tuple(f for f in self.findings if f.level is PolicyLevel.WARN)


_BLOCK_IF_TRUE: tuple[tuple[str, str, str], ...] = (
    (
        "enableWithdrawals",
        "withdrawals_enabled",
        "API anahtarında PARA ÇEKME yetkisi açık. Güvenlik için bu anahtar kullanılamaz; "
        "Binance'te para çekme yetkisi kapalı yeni bir anahtar oluşturun.",
    ),
    (
        "enableInternalTransfer",
        "internal_transfer_enabled",
        "API anahtarında iç transfer yetkisi açık; fonlar başka hesaplara taşınabilir.",
    ),
    (
        "permitsUniversalTransfer",
        "universal_transfer_enabled",
        "API anahtarında evrensel transfer yetkisi açık; bu yetki kapatılmalı.",
    ),
)

_WARN_IF_TRUE: tuple[tuple[str, str, str], ...] = (
    ("enableMargin", "margin_enabled", "Marjin (borçlanma) yetkisi açık; ürün bunu kullanmaz."),
    (
        "enablePortfolioMarginTrading",
        "portfolio_margin_enabled",
        "Portföy marjini yetkisi açık; ürün bunu kullanmaz.",
    ),
    ("enableVanillaOptions", "options_enabled", "Opsiyon yetkisi açık; ürün bunu kullanmaz."),
)


def evaluate_api_restrictions(
    restrictions: Mapping[str, Any],
    *,
    required_markets: Iterable[Market],
    trading_required: bool,
) -> KeyPolicyVerdict:
    findings: list[PolicyFinding] = []

    for key, code, message in _BLOCK_IF_TRUE:
        # Alan yoksa güvenli tarafta kal: bilinmeyen durum = yetki açık kabul edilir.
        if restrictions.get(key, True) is not False:
            findings.append(PolicyFinding(PolicyLevel.BLOCK, code, message))

    if restrictions.get("enableReading") is not True:
        findings.append(
            PolicyFinding(PolicyLevel.BLOCK, "reading_disabled", "Okuma yetkisi kapalı.")
        )

    if trading_required:
        markets = set(required_markets)
        if Market.SPOT in markets and restrictions.get("enableSpotAndMarginTrading") is not True:
            findings.append(
                PolicyFinding(
                    PolicyLevel.BLOCK,
                    "spot_trading_disabled",
                    "Spot işlem yetkisi kapalı; spot işlemler için gereklidir.",
                )
            )
        if Market.USDM_FUTURES in markets and restrictions.get("enableFutures") is not True:
            findings.append(
                PolicyFinding(
                    PolicyLevel.BLOCK,
                    "futures_trading_disabled",
                    "Futures yetkisi kapalı; futures işlemleri için gereklidir.",
                )
            )

    if restrictions.get("ipRestrict") is not True:
        findings.append(
            PolicyFinding(
                PolicyLevel.WARN,
                "no_ip_restriction",
                "Anahtar IP ile kısıtlanmamış. Mümkünse yalnızca bu bilgisayarın IP adresine "
                "izin verin.",
            )
        )

    for key, code, message in _WARN_IF_TRUE:
        if restrictions.get(key) is True:
            findings.append(PolicyFinding(PolicyLevel.WARN, code, message))

    return KeyPolicyVerdict(tuple(findings))
