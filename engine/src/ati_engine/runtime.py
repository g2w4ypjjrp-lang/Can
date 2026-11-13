"""Çalışan motorun bileşenlerine erişim noktası (yerel API ve testler tarafından kullanılır)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from ati_engine import __version__
from ati_engine.analysis.service import AnalysisService
from ati_engine.backtest.service import BacktestService
from ati_engine.config import EngineSettings
from ati_engine.core.bus import EventBus
from ati_engine.core.models import Market, TradingMode
from ati_engine.core.supervisor import TaskSupervisor
from ati_engine.execution.auto import AutoTrader
from ati_engine.execution.service import ExecutionService
from ati_engine.history.service import HistoryService
from ati_engine.licensing.manager import LicenseManager
from ati_engine.market.live_prices import LivePrices
from ati_engine.market.service import MarketDataService
from ati_engine.notify.telegram import TelegramNotifier
from ati_engine.observability.crash import CrashReporter
from ati_engine.observability.loop_monitor import LoopLagMonitor
from ati_engine.paper.competition import PaperCompetition
from ati_engine.remote.service import RemoteService
from ati_engine.safety.coordinator import SafetyCoordinator
from ati_engine.safety.trading_mode import TradingModeController
from ati_engine.scanner.scanner import MarketScanner
from ati_engine.scoring.live import OpportunityEngine
from ati_engine.security.vault import SecretVault
from ati_engine.storage.audit import AuditLog
from ati_engine.storage.database import Database
from ati_engine.whales.radar import WhaleRadar


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
    scanner: MarketScanner | None = None
    whales: WhaleRadar | None = None
    history: HistoryService | None = None
    analysis: AnalysisService | None = None
    opportunities: OpportunityEngine | None = None
    backtests: BacktestService | None = None
    paper: PaperCompetition | None = None
    execution: ExecutionService | None = None  # Demo Trading (test ağı)
    execution_live: ExecutionService | None = None  # gerçek hesap (kullanıcı onayıyla)
    execution_paper: ExecutionService | None = None
    autotrader: AutoTrader | None = None
    remote: RemoteService | None = None
    live_prices: LivePrices | None = None
    license: LicenseManager | None = None
    telegram: TelegramNotifier | None = None
    crash: CrashReporter | None = None

    def mark_price(self, market: Market, symbol: str) -> float | None:
        """Ekranda gösterilen güncel fiyat: Binance'in işlem akışındaki son işlem fiyatı (her
        işlemde anında gelir); yoksa Futures işaret fiyatı (saniyede bir), yoksa 24 saatlik özet."""
        data = self.market_data.get(market)
        if data is None:
            return None
        last = data.state.trades.get(symbol)
        if last is not None and last > 0:
            return last
        mark = data.state.marks.get(symbol)
        if mark is not None and mark.mark_price > 0:
            return mark.mark_price
        ticker = data.state.tickers.get(symbol)
        return ticker.last if ticker is not None and ticker.last > 0 else None

    def active_execution(self) -> ExecutionService | None:
        """İşlem moduna göre yürütme servisi: Gerçek para → gerçek hesap, Demo → Binance Demo
        Trading, Sanal → sanal hesap (borsaya emir gitmez)."""
        mode = self.trading_mode.mode
        if mode is TradingMode.LIVE:
            return self.execution_live
        if mode is TradingMode.PAPER and self.execution_paper is not None:
            return self.execution_paper
        return self.execution

    version: str = __version__
    started_monotonic: float = field(default_factory=time.monotonic)
    shutdown_requested: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def uptime_s(self) -> float:
        return time.monotonic() - self.started_monotonic

    def request_shutdown(self) -> None:
        self.shutdown_requested.set()
