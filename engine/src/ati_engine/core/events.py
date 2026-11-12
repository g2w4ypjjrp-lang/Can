"""Motor içi olaylar.

Bütün olaylar ``Event`` sınıfından türer ve msgspec ile etiketli (tagged) olarak
serileştirilir: ``{"type": "KillSwitchEngaged", "ts_ms": ..., ...}``. Aynı biçim yerel
API'nin WebSocket akışında masaüstü ve iOS istemcilerine de gönderilir; şeması
``shared/protocol`` altında yayımlanır.

Piyasa verisi olayları (ticker, kline, aggTrade, derinlik) Aşama 2'de ``market``
paketinde bu temel sınıftan türetilecektir.
"""

from __future__ import annotations

from typing import Any

import msgspec

from ati_engine.core.clock import now_ms
from ati_engine.core.models import EngineState, Severity, TradingMode


class Event(msgspec.Struct, frozen=True, kw_only=True, tag_field="type", tag=True):
    ts_ms: int = msgspec.field(default_factory=now_ms)


class SystemEvent(Event, frozen=True, kw_only=True):
    """Arayüze ve iOS'a iletilen, düşük hacimli sistem olayları.

    Yüksek hacimli piyasa verisi olayları (işlemler, mumlar, derinlik) bu sınıftan türemez;
    yalnızca motor içinde dolaşır ve masaüstüne ayrı, hız sınırlı uç noktalarla sunulur.
    """


class EngineStateChanged(SystemEvent, frozen=True, kw_only=True):
    previous: EngineState
    current: EngineState
    reason: str


class TradingModeChanged(SystemEvent, frozen=True, kw_only=True):
    previous: TradingMode
    current: TradingMode
    actor: str


class KillSwitchEngaged(SystemEvent, frozen=True, kw_only=True):
    reason: str
    actor: str


class KillSwitchReleased(SystemEvent, frozen=True, kw_only=True):
    actor: str


class ReadinessChanged(SystemEvent, frozen=True, kw_only=True):
    condition: str
    ready: bool
    detail: str = ""


class ServiceHealthChanged(SystemEvent, frozen=True, kw_only=True):
    service: str
    healthy: bool
    detail: str = ""


class Heartbeat(SystemEvent, frozen=True, kw_only=True):
    uptime_s: float
    loop_lag_ms: float
    state: EngineState
    trading_mode: TradingMode


class Alert(SystemEvent, frozen=True, kw_only=True):
    severity: Severity
    title: str
    message: str
    context: dict[str, Any] = msgspec.field(default_factory=dict)


class TradeNotice(SystemEvent, frozen=True, kw_only=True):
    """Pozisyon açıldı / kapandı özeti (bildirimler için; emir ayrıntısı ve anahtar içermez)."""

    market: str
    mode: str
    symbol: str
    action: str  # "opened" | "closed"
    side: str  # "long" | "short"
    quantity: str
    price: str
    net_pnl: str | None = None
    # Ayrıntılar (varsa): açılışta stop/hedef/puan/gerekçe, kapanışta giriş fiyatı, yüzde
    # kâr/zarar, kapanış nedeni ve süre. Bildirimlerde gösterilir.
    stop_loss: str | None = None
    take_profit: str | None = None
    score: float | None = None
    reason: str | None = None
    leverage: int | None = None
    entry_price: str | None = None
    pnl_pct: float | None = None
    close_reason: str | None = None
    duration_s: int | None = None


# Yerel API ve protokol şeması için bilinen çekirdek sistem olayları
# (piyasa sistem olayları ``market.events.PUBLIC_MARKET_EVENT_TYPES`` içindedir).
PUBLIC_EVENT_TYPES: tuple[type[SystemEvent], ...] = (
    EngineStateChanged,
    TradingModeChanged,
    KillSwitchEngaged,
    KillSwitchReleased,
    ReadinessChanged,
    ServiceHealthChanged,
    Heartbeat,
    Alert,
)

_encoder = msgspec.json.Encoder(decimal_format="string")


def encode_event(event: Event) -> bytes:
    return _encoder.encode(event)
