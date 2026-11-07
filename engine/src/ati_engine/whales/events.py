"""Balina radarı olayları.

* ``WhaleTrade`` (motor içi): eşiği aşan tek agresif emir. Saniyede birkaç tane olabilir;
  masaüstüne doğrudan gönderilmez, ``/v1/whales/*`` uç noktalarıyla sunulur.
* ``WhaleAlert`` (masaüstü ve iOS bildirimi): kümelenme, çok büyük emir, duvar çekilmesi,
  tasfiye zinciri, büyük oyuncu pozisyon değişimi, zincir üstü büyük transfer. Sembol ve tür
  başına bekleme süresiyle sınırlanır.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from ati_engine.core.events import SystemEvent
from ati_engine.core.models import Market, Severity
from ati_engine.market.events import MarketDataEvent


class WhaleTrade(MarketDataEvent, frozen=True, kw_only=True):
    symbol: str
    side: str  # "buy" = agresif alış, "sell" = agresif satış
    notional: float
    avg_price: float
    qty: float
    fills: int  # süpürülen fiyat kademesi / birleştirilen işlem sayısı
    sweep_pct: float  # emrin kendi içinde süpürdüğü fiyat aralığı
    threshold: float  # o anki sembole özel balina eşiği


class WhaleAlertKind(StrEnum):
    MEGA_TRADE = "mega_trade"
    ACCUMULATION = "accumulation"  # aynı yönde art arda büyük alımlar
    DISTRIBUTION = "distribution"  # aynı yönde art arda büyük satışlar
    WALL_PULLED = "wall_pulled"  # büyük emir duvarı fiyat ulaşmadan çekildi
    WALL_EATEN = "wall_eaten"  # büyük emir duvarı işlemle eritildi
    LIQUIDATION_CASCADE = "liquidation_cascade"
    POSITIONING_SHIFT = "positioning_shift"
    ONCHAIN_TRANSFER = "onchain_transfer"


class WhaleAlert(SystemEvent, frozen=True, kw_only=True):
    market: Market | None
    symbol: str
    kind: WhaleAlertKind
    severity: Severity
    side: str
    notional: float
    message: str
    details: dict[str, Any] = {}  # noqa: RUF012 - msgspec her örnek için kopyalar
