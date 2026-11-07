"""Zincir üstü büyük transferler ve borsa giriş/çıkış sınıflandırması.

Bu katman sağlayıcıdan bağımsızdır: herhangi bir sağlayıcı ``OnchainProvider`` arayüzünü
uygulayarak büyük transferleri döndürür; sınıflandırma ise adres etiketleriyle yapılır.

* Alıcı adres bir borsaya aitse → **borsaya giriş** (genellikle satış hazırlığı olarak okunur)
* Gönderen adres bir borsaya aitse → **borsadan çıkış** (genellikle soğuk cüzdana çekme)
* İkisi de borsa ise → borsalar arası / borsa içi
* Hiçbiri değilse → cüzdanlar arası transfer

**Önemli (onay kapısı G4):** Ücretsiz herkese açık veri servislerinin çoğu ticari kullanıma
izin vermez ve paylaşılan IP adreslerini sınırlar (2026-11-07 denemesinde bir servis Bitcoin
sorgusuna 430 hatası döndürdü). Bu yüzden zincir üstü izleme varsayılan olarak **kapalıdır**;
ticari kullanım için anahtarlı bir sağlayıcı seçilmesi ve onayınız gerekir. Adres etiketleri
(hangi adres hangi borsaya ait) kullanıcının sağladığı bir JSON dosyasından okunur; motor
etiket uydurmaz.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

import httpx


class FlowType(StrEnum):
    EXCHANGE_INFLOW = "exchange_inflow"
    EXCHANGE_OUTFLOW = "exchange_outflow"
    EXCHANGE_INTERNAL = "exchange_internal"
    TRANSFER = "transfer"


@dataclass(frozen=True)
class RawTransfer:
    chain: str
    tx_hash: str
    time_ms: int
    asset: str
    amount: float
    amount_usd: float
    sender: str
    recipient: str


@dataclass(frozen=True)
class OnchainTransfer:
    chain: str
    tx_hash: str
    time_ms: int
    asset: str
    amount: float
    amount_usd: float
    sender: str
    recipient: str
    sender_label: str | None
    recipient_label: str | None
    flow: FlowType


_EVM_CHAINS = frozenset({"ethereum", "bsc", "polygon", "arbitrum", "base", "optimism"})


class AddressLabels:
    """Zincir başına adres → etiket (ör. "Binance"). EVM adresleri küçük harfe çevrilir."""

    def __init__(self, labels: Mapping[str, Mapping[str, str]] | None = None) -> None:
        self._labels: dict[str, dict[str, str]] = {}
        for chain, entries in (labels or {}).items():
            for address, label in entries.items():
                self.add(chain, address, label)

    @staticmethod
    def _norm(chain: str, address: str) -> str:
        return address.lower() if chain in _EVM_CHAINS else address

    def add(self, chain: str, address: str, label: str) -> None:
        self._labels.setdefault(chain, {})[self._norm(chain, address)] = label

    def lookup(self, chain: str, address: str) -> str | None:
        return self._labels.get(chain, {}).get(self._norm(chain, address))

    def __len__(self) -> int:
        return sum(len(v) for v in self._labels.values())

    @classmethod
    def load(cls, path: Path) -> AddressLabels:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Etiket dosyası {zincir: {adres: etiket}} biçiminde olmalı")
        return cls(data)


def classify(sender_label: str | None, recipient_label: str | None) -> FlowType:
    if sender_label and recipient_label:
        return FlowType.EXCHANGE_INTERNAL
    if recipient_label:
        return FlowType.EXCHANGE_INFLOW
    if sender_label:
        return FlowType.EXCHANGE_OUTFLOW
    return FlowType.TRANSFER


class OnchainProvider(Protocol):
    name: str

    async def fetch(self) -> list[RawTransfer]: ...


class OnchainWatcher:
    """Sağlayıcıdan gelen transferleri etiketler, sınıflandırır ve tekrarları eler."""

    def __init__(
        self, provider: OnchainProvider, labels: AddressLabels, *, memory: int = 5_000
    ) -> None:
        self.provider = provider
        self.labels = labels
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._memory = memory

    async def poll(self) -> list[OnchainTransfer]:
        result: list[OnchainTransfer] = []
        for raw in await self.provider.fetch():
            key = f"{raw.chain}:{raw.tx_hash}"
            if key in self._seen:
                continue
            self._seen[key] = None
            if len(self._seen) > self._memory:
                self._seen.popitem(last=False)
            sender_label = self.labels.lookup(raw.chain, raw.sender)
            recipient_label = self.labels.lookup(raw.chain, raw.recipient)
            result.append(
                OnchainTransfer(
                    chain=raw.chain,
                    tx_hash=raw.tx_hash,
                    time_ms=raw.time_ms,
                    asset=raw.asset,
                    amount=raw.amount,
                    amount_usd=raw.amount_usd,
                    sender=raw.sender,
                    recipient=raw.recipient,
                    sender_label=sender_label,
                    recipient_label=recipient_label,
                    flow=classify(sender_label, recipient_label),
                )
            )
        return result


class BlockchairEthereumProvider:
    """Blockchair üzerinden büyük ETH transferleri (değerlendirme amaçlı örnek sağlayıcı).

    Ücretsiz kullanım sınırlıdır ve ticari kullanım için anahtarlı plan gerekir (G4).
    """

    name = "blockchair_ethereum"

    def __init__(
        self,
        *,
        min_usd: float = 5_000_000,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        base_url: str = "https://api.blockchair.com",
    ) -> None:
        self._min_usd = min_usd
        self._key = api_key
        self._client = client or httpx.AsyncClient(timeout=15)
        self._base = base_url.rstrip("/")

    @staticmethod
    def parse(payload: Mapping[str, Any]) -> list[RawTransfer]:
        context = payload.get("context") or {}
        if context.get("code") != 200:
            raise RuntimeError(f"Blockchair yanıt kodu {context.get('code')}")
        transfers = []
        for row in payload.get("data") or []:
            stamp = datetime.strptime(str(row["time"]), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            transfers.append(
                RawTransfer(
                    chain="ethereum",
                    tx_hash=str(row["hash"]),
                    time_ms=int(stamp.timestamp() * 1000),
                    asset="ETH",
                    amount=float(Decimal(str(row["value"])) / Decimal(10**18)),
                    amount_usd=float(row.get("value_usd") or 0.0),
                    sender=str(row["sender"]),
                    recipient=str(row["recipient"]),
                )
            )
        return transfers

    async def fetch(self) -> list[RawTransfer]:
        params: dict[str, str | int] = {
            "q": f"value_usd({int(self._min_usd)}..)",
            "s": "id(desc)",
            "limit": 10,
        }
        if self._key:
            params["key"] = self._key
        response = await self._client.get(f"{self._base}/ethereum/transactions", params=params)
        response.raise_for_status()
        return self.parse(response.json())
