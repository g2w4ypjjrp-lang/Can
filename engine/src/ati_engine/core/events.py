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


class EngineStateChanged(Event, frozen=True, kw_only=True):
    previous: EngineState
    current: EngineState
    reason: str


class TradingModeChanged(Event, frozen=True, kw_only=True):
    previous: TradingMode
    current: TradingMode
    actor: str


class KillSwitchEngaged(Event, frozen=True, kw_only=True):
    reason: str
    actor: str


class KillSwitchReleased(Event, frozen=True, kw_only=True):
    actor: str


class ReadinessChanged(Event, frozen=True, kw_only=True):
    condition: str
    ready: bool
    detail: str = ""


class ServiceHealthChanged(Event, frozen=True, kw_only=True):
    service: str
    healthy: bool
    detail: str = ""


class Heartbeat(Event, frozen=True, kw_only=True):
    uptime_s: float
    loop_lag_ms: float
    state: EngineState
    trading_mode: TradingMode


class Alert(Event, frozen=True, kw_only=True):
    severity: Severity
    title: str
    message: str
    context: dict[str, Any] = msgspec.field(default_factory=dict)


# Yerel API ve protokol şeması için bilinen olay türleri.
PUBLIC_EVENT_TYPES: tuple[type[Event], ...] = (
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
