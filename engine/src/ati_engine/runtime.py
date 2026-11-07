"""Çalışan motorun bileşenlerine erişim noktası (yerel API ve testler tarafından kullanılır)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from ati_engine import __version__
from ati_engine.config import EngineSettings
from ati_engine.core.bus import EventBus
from ati_engine.core.models import Market
from ati_engine.core.supervisor import TaskSupervisor
from ati_engine.market.service import MarketDataService
from ati_engine.observability.loop_monitor import LoopLagMonitor
from ati_engine.safety.coordinator import SafetyCoordinator
from ati_engine.safety.trading_mode import TradingModeController
from ati_engine.security.vault import SecretVault
from ati_engine.storage.audit import AuditLog
from ati_engine.storage.database import Database


@dataclass
class EngineRuntime:
    settings: EngineSettings
    db: Database
    bus: EventBus
    audit: AuditLog
    vault: SecretVault
    safety: SafetyCoordinator
    trading_mode: TradingModeController
    supervisor: TaskSupervisor
    loop_monitor: LoopLagMonitor
    api_token: str
    market_data: dict[Market, MarketDataService] = field(default_factory=dict)
    version: str = __version__
    started_monotonic: float = field(default_factory=time.monotonic)
    shutdown_requested: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def uptime_s(self) -> float:
        return time.monotonic() - self.started_monotonic

    def request_shutdown(self) -> None:
        self.shutdown_requested.set()
