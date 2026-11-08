"""Motorun bileşim kökü (composition root) ve yaşam döngüsü.

Açılış sırası:
 1. Ayarlar ve dizinler      6. Acil durdurma durumunu yükle
 2. Tek örnek kilidi         7. Güvenlik koordinatörü + işlem modu (PAPER)
 3. Loglama                  8. Denetlenen görevler (kalp atışı, gecikme izleyici)
 4. SQLite + geçişler        9. Yerel API
 5. Olay veri yolu, kasa    10. Açılış tamam → SAFE_MODE → (koşullar hazırsa) RUNNING

Kapanış ters sırada yapılır; kapanış sırasında hiçbir yeni pozisyon açılamaz.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import secrets
import signal
import sys
from pathlib import Path
from typing import Any

from ati_engine import __version__
from ati_engine.analysis.service import AnalysisService
from ati_engine.api.server import bind_socket, build_server, create_app
from ati_engine.backtest.service import BacktestService
from ati_engine.config import EngineSettings
from ati_engine.core.bus import EventBus, OverflowPolicy
from ati_engine.core.events import Alert, Heartbeat
from ati_engine.core.models import EngineState, Market, Severity
from ati_engine.core.supervisor import RestartPolicy, TaskSupervisor
from ati_engine.exchange.endpoints import endpoints_for
from ati_engine.exchange.rate_limit import WeightBudget
from ati_engine.exchange.rest import BinanceRestClient
from ati_engine.execution.auto import AutoTrader
from ati_engine.execution.fills import FillSimulator
from ati_engine.execution.service import ExecutionService
from ati_engine.history.archive import INTERVAL_MS
from ati_engine.history.service import HistoryService
from ati_engine.history.store import KlineStore
from ati_engine.history.sync import RestSource
from ati_engine.market.discovery import SymbolRegistry, UniverseFilter
from ati_engine.market.events import AggTrade
from ati_engine.market.orderbook import OrderBook, SyncState
from ati_engine.market.service import DEFAULT_WEIGHT_LIMIT, MarketDataService
from ati_engine.ml.registry import ModelRegistry
from ati_engine.observability.logging import configure_logging
from ati_engine.observability.loop_monitor import LoopLagMonitor
from ati_engine.paper.competition import PaperCompetition
from ati_engine.remote.crypto import EngineIdentity, b64, unb64
from ati_engine.remote.runtime_bridge import (
    build_executors,
    build_snapshot,
    subscribe_notifications,
)
from ati_engine.remote.service import RemoteService
from ati_engine.runtime import EngineRuntime
from ati_engine.safety.coordinator import SafetyCoordinator
from ati_engine.safety.kill_switch import KillSwitch
from ati_engine.safety.state import EngineStateMachine
from ati_engine.safety.trading_mode import TradingModeController
from ati_engine.scanner.scanner import MarketScanner
from ati_engine.scoring.live import OpportunityEngine, OpportunityScored
from ati_engine.security.exchange_keys import ExchangeKeyStore
from ati_engine.security.vault import SecretVault, default_cipher
from ati_engine.storage.audit import AuditLog
from ati_engine.storage.database import Database
from ati_engine.storage.settings_store import SettingsStore
from ati_engine.system.single_instance import SingleInstanceLock
from ati_engine.whales.onchain import AddressLabels, BlockchairEthereumProvider, OnchainWatcher
from ati_engine.whales.radar import WhaleRadar

logger = logging.getLogger("ati_engine.app")

TOKEN_ENV = "ATI_LOCAL_API_TOKEN"  # noqa: S105 - ortam değişkeni adı, gizli değer değil
SYSTEM_ACTOR = "system"


def _write_runtime_file(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    if sys.platform == "win32":
        tmp.write_text(json.dumps(data), encoding="utf-8")
    else:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
    os.replace(tmp, path)


class Engine:
    def __init__(self, settings: EngineSettings) -> None:
        self.settings = settings
        self.runtime: EngineRuntime | None = None
        self.bound_port: int | None = None
        self._lock = SingleInstanceLock(settings.paths.lock_file)
        self._ready = asyncio.Event()

    @property
    def ready(self) -> asyncio.Event:
        return self._ready

    async def run(self) -> int:
        settings = self.settings
        paths = settings.paths
        paths.ensure()
        self._lock.acquire()
        db: Database | None = None
        bus: EventBus | None = None
        supervisor: TaskSupervisor | None = None
        server_task: asyncio.Task[None] | None = None
        server = None
        try:
            configure_logging(
                level=settings.log_level,
                json_output=settings.log_json,
                console=settings.log_to_console,
                log_dir=paths.logs_dir,
            )
            logger.info(
                "Motor başlatılıyor", extra={"version": __version__, "data_dir": str(paths.root)}
            )

            db = Database(paths.database)
            await db.open()
            applied = await db.migrate()
            if applied:
                logger.info("Veritabanı geçişleri uygulandı", extra={"versions": applied})

            bus = EventBus()
            audit = AuditLog(db)
            vault = SecretVault(db, default_cipher(paths.root))
            store = SettingsStore(db)
            kill_switch = KillSwitch(store=store, audit=audit, bus=bus)
            await kill_switch.load()
            state = EngineStateMachine(bus)
            safety = SafetyCoordinator(bus=bus, state=state, kill_switch=kill_switch)
            trading_mode = TradingModeController(
                settings=settings, bus=bus, audit=audit, kill_switch=kill_switch
            )

            async def on_give_up(name: str, error: BaseException | None) -> None:
                await safety.enter_safe_mode(f"kritik görev durdu: {name}")
                await bus.publish(
                    Alert(
                        severity=Severity.CRITICAL,
                        title="Kritik görev durdu",
                        message=f"'{name}' görevi tekrar tekrar çöktü; motor güvenli moda geçti.",
                        context={"error": repr(error) if error else None},
                    )
                )

            supervisor = TaskSupervisor(on_give_up=on_give_up)
            loop_monitor = LoopLagMonitor()

            token = os.environ.get(TOKEN_ENV) or secrets.token_urlsafe(32)
            token_from_env = TOKEN_ENV in os.environ
            runtime = EngineRuntime(
                settings=settings,
                db=db,
                bus=bus,
                audit=audit,
                vault=vault,
                safety=safety,
                trading_mode=trading_mode,
                supervisor=supervisor,
                loop_monitor=loop_monitor,
                api_token=token,
            )
            self.runtime = runtime

            # Önemli olayları loglara da yaz (asla kaybolmamalı -> BLOCK).
            bus.subscribe(Alert, self._log_alert, name="alert-logger", policy=OverflowPolicy.BLOCK)

            if settings.market_data.enabled:
                self._start_market_data(runtime)
            if settings.history.enabled:
                runtime.history = self._create_history(runtime)
                runtime.analysis = AnalysisService(runtime.history, ModelRegistry(paths.models_dir))
                runtime.backtests = BacktestService(runtime.history, db, paths.backtests_dir)
            if settings.scoring.enabled:
                self._start_scoring(runtime)
            if settings.paper.enabled and runtime.opportunities is not None:
                await self._start_paper(runtime)
            if settings.execution.testnet_enabled:
                self._start_execution(runtime)
            await self._start_remote(runtime)

            supervisor.spawn("loop-lag-monitor", loop_monitor.run)
            supervisor.spawn(
                "heartbeat",
                lambda: self._heartbeat(runtime),
                RestartPolicy(max_restarts=10, window_s=60),
            )

            sock = bind_socket(settings.api.host, settings.api.port)
            self.bound_port = int(sock.getsockname()[1])
            server = build_server(create_app(runtime))
            server_task = asyncio.create_task(server.serve(sockets=[sock]), name="local-api")

            runtime_info: dict[str, Any] = {
                "pid": os.getpid(),
                "host": settings.api.host,
                "port": self.bound_port,
                "version": __version__,
            }
            if not token_from_env:
                runtime_info["token"] = token
            _write_runtime_file(paths.runtime_file, runtime_info)

            await audit.record(
                actor=SYSTEM_ACTOR,
                action="engine.start",
                details={"version": __version__, "trading_mode": trading_mode.mode.value},
            )
            await safety.boot_complete()
            self._install_signal_handlers(runtime)
            self._ready.set()
            logger.info(
                "Motor hazır",
                extra={"port": self.bound_port, "state": safety.state.state.value},
            )

            stop_wait = asyncio.create_task(runtime.shutdown_requested.wait())
            done, _ = await asyncio.wait(
                {stop_wait, server_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if server_task in done and not stop_wait.done():
                stop_wait.cancel()
                exc = server_task.exception()
                logger.error("Yerel API beklenmedik şekilde durdu", extra={"error": repr(exc)})
                return 1
            return 0
        finally:
            await self._shutdown(server, server_task, supervisor, bus, db)

    @staticmethod
    async def _start_remote(runtime: EngineRuntime) -> None:
        """Uzaktan kontrol: motor kimliği (Ed25519) kasada kalıcıdır. Aktarma servisi adresi
        ayarlanmışsa servise giden bağlantı açılır; yoksa yalnızca eşleştirme ekranı kapalıdır."""
        cfg = runtime.settings.remote
        stored = await runtime.vault.get("remote.engine_key")
        if stored is None:
            identity = EngineIdentity.generate()
            await runtime.vault.put("remote.engine_key", b64(identity.private_raw()))
        else:
            identity = EngineIdentity.from_private_raw(unb64(stored.get_secret_value()))
        service = RemoteService(
            db=runtime.db,
            identity=identity,
            relay_url=cfg.relay_url,
            executors=build_executors(runtime),
            snapshot=lambda: build_snapshot(runtime),
            snapshot_interval_s=cfg.snapshot_interval_s,
            max_skew_s=cfg.max_clock_skew_s,
            pairing_ttl_s=cfg.pairing_ttl_s,
        )
        runtime.remote = service
        subscribe_notifications(runtime, service)
        if cfg.relay_url:
            runtime.supervisor.spawn(
                "remote-relay",
                service.run,
                RestartPolicy(
                    max_restarts=50, window_s=3600, backoff_initial_s=2, backoff_max_s=60
                ),
            )

    @staticmethod
    def _start_execution(runtime: EngineRuntime) -> None:
        """Test ağı yürütme servisi. Gerçek hesap bu sürümde kilitlidir (G1/G2). Kayıtlı test ağı
        anahtarı varsa bağlantı arka planda kurulur; başarısızlık motoru durdurmaz."""
        service = ExecutionService(
            settings=runtime.settings,
            db=runtime.db,
            audit=runtime.audit,
            keys=ExchangeKeyStore(runtime.vault),
            trading_mode=lambda: runtime.trading_mode.mode,
            engine_state=lambda: runtime.safety.state.state,
            safety=runtime.safety,
            bus=runtime.bus,
        )
        runtime.execution = service
        service.start_guard()
        autotrader = AutoTrader(
            settings=runtime.settings.autotrade,
            limits=runtime.settings.risk,
            service=service,
            trading_mode=lambda: runtime.trading_mode.mode,
        )
        runtime.autotrader = autotrader
        runtime.bus.subscribe(OpportunityScored, autotrader.on_opportunity, name="autotrader")

        async def connect() -> None:
            try:
                await service.connect_configured()
            except Exception as exc:
                logger.error("Test ağı yürütücüsü başlatılamadı", extra={"error": repr(exc)})

        runtime.supervisor.spawn("execution-connect", connect, RestartPolicy(restart=False))

    async def _start_paper(self, runtime: EngineRuntime) -> None:
        """Sanal işlem yarışması: hesaplar her durumda yüklenir (API için); canlı işlem ve
        mum dinleyicisi yalnızca piyasa verisi açıkken bağlanır."""
        settings = runtime.settings
        services = runtime.market_data

        def book_of(market_value: str, symbol: str) -> OrderBook | None:
            service = services.get(Market(market_value))
            sync = service.books.get(symbol) if service is not None else None
            if sync is None or sync.state is not SyncState.SYNCED:
                return None
            return sync.book

        def funding_of(market: Market, symbol: str) -> tuple[float, float] | None:
            service = services.get(market)
            mark = service.state.marks.get(symbol) if service is not None else None
            return (mark.mark_price, mark.funding_rate) if mark is not None else None

        competition = PaperCompetition(
            settings=settings.paper,
            db=runtime.db,
            bus=runtime.bus,
            fills=FillSimulator(
                books=book_of,
                spot_fee=settings.scoring.spot_taker_fee,
                futures_fee=settings.scoring.futures_taker_fee,
            ),
            interval_ms=INTERVAL_MS[settings.scoring.interval],
            funding_of=funding_of,
        )
        await competition.load(settings.markets)
        runtime.paper = competition
        if services and runtime.opportunities is not None:
            runtime.bus.subscribe(
                AggTrade, competition.on_trade, name="paper-trades", maxsize=200_000
            )
            runtime.opportunities.add_listener(competition.on_bars)

    def _start_scoring(self, runtime: EngineRuntime) -> None:
        """Fırsat motoru: piyasa verisi açıksa canlı çalışır; değilse yalnızca tarihsel veriden
        isteğe bağlı değerlendirme yapar."""
        settings = runtime.settings
        engine = OpportunityEngine(
            settings=settings.scoring,
            bus=runtime.bus,
            db=runtime.db,
            calibration_dir=settings.paths.scoring_dir,
            registry=ModelRegistry(settings.paths.models_dir),
        )
        runtime.opportunities = engine
        if runtime.market_data:
            engine.attach(
                runtime.market_data.values(),
                scanner=runtime.scanner,
                radar=runtime.whales,
                history=runtime.history,
            )
            runtime.supervisor.spawn(
                "opportunities",
                engine.run,
                RestartPolicy(max_restarts=20, window_s=600, backoff_initial_s=1, backoff_max_s=30),
            )

    def _create_history(self, runtime: EngineRuntime) -> HistoryService:
        """REST tamamlaması piyasa verisi servisinin istemcisini (ortak ağırlık bütçesi)
        kullanır; piyasa verisi kapalıysa kendi istemcisini açar."""
        settings = runtime.settings
        rest: dict[Market, RestSource] = {}
        owned: list[BinanceRestClient] = []
        for market in settings.markets:
            service = runtime.market_data.get(market)
            if service is not None:
                rest[market] = (service.rest, service.endpoints)
                continue
            endpoints = endpoints_for(market, settings.binance)
            client = BinanceRestClient(
                endpoints.rest_base, budget=WeightBudget(DEFAULT_WEIGHT_LIMIT[market])
            )
            owned.append(client)
            rest[market] = (client, endpoints)
        return HistoryService(
            KlineStore(settings.paths.history_db),
            runtime.db,
            concurrency=settings.history.download_concurrency,
            rest=rest,
            owned_rest=owned,
        )

    async def _shutdown(
        self,
        server: Any,
        server_task: asyncio.Task[None] | None,
        supervisor: TaskSupervisor | None,
        bus: EventBus | None,
        db: Database | None,
    ) -> None:
        runtime = self.runtime
        try:
            if runtime is not None:
                with contextlib.suppress(Exception):
                    await runtime.safety.shutdown("kapatma isteği")
                    await runtime.audit.record(actor=SYSTEM_ACTOR, action="engine.stop")
            if server is not None:
                server.should_exit = True
            if server_task is not None:
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await asyncio.wait_for(server_task, timeout=5)
            if supervisor is not None:
                await supervisor.stop_all()
            if runtime is not None:
                if runtime.remote is not None:
                    with contextlib.suppress(Exception):
                        await runtime.remote.stop()
                if runtime.execution is not None:
                    with contextlib.suppress(Exception):
                        await runtime.execution.close()
                for service in runtime.market_data.values():
                    with contextlib.suppress(Exception):
                        await service.close()
                if runtime.backtests is not None:
                    with contextlib.suppress(Exception):
                        await runtime.backtests.close()
                if runtime.opportunities is not None:
                    with contextlib.suppress(Exception):
                        await runtime.opportunities.close()
                if runtime.analysis is not None:
                    with contextlib.suppress(Exception):
                        await runtime.analysis.close()
                if runtime.history is not None:
                    with contextlib.suppress(Exception):
                        await runtime.history.close()
            if runtime is not None:
                with contextlib.suppress(Exception):
                    await runtime.safety.state.transition(EngineState.STOPPED, "durduruldu")
            if bus is not None:
                await bus.close()
            if db is not None:
                await db.close()
            with contextlib.suppress(FileNotFoundError):
                self.settings.paths.runtime_file.unlink()
        finally:
            self._lock.release()
            logger.info("Motor durdu")

    @staticmethod
    def _start_market_data(runtime: EngineRuntime) -> None:
        settings = runtime.settings
        cfg = settings.market_data
        registry = SymbolRegistry(
            runtime.db,
            runtime.bus,
            universe=UniverseFilter(
                quote_asset=settings.quote_asset,
                futures_contract_types=frozenset(cfg.futures_contract_types),
                allowlist=frozenset(cfg.symbol_allowlist) if cfg.symbol_allowlist else None,
                max_symbols=cfg.max_symbols,
                excluded_bases=frozenset(cfg.excluded_base_assets),
            ),
        )
        for market in settings.markets:
            condition = f"market_data.{market.value}"

            async def on_ready(ready: bool, detail: str, _condition: str = condition) -> None:
                await runtime.safety.set_ready(_condition, ready, detail)

            service = MarketDataService(
                market=market,
                settings=settings,
                registry=registry,
                bus=runtime.bus,
                on_ready=on_ready,
            )
            runtime.safety.register_condition(condition, ready=False, detail="başlatılıyor")
            runtime.market_data[market] = service
            runtime.supervisor.spawn(
                f"market-data-{market.value}",
                service.run,
                RestartPolicy(max_restarts=20, window_s=600, backoff_initial_s=1, backoff_max_s=60),
            )

        if settings.scanner.enabled:
            scanner = MarketScanner(settings=settings.scanner, bus=runtime.bus, db=runtime.db)
            scanner.attach()
            runtime.scanner = scanner
            services = list(runtime.market_data.values())
            runtime.supervisor.spawn(
                "scanner",
                lambda: scanner.run(services),
                RestartPolicy(max_restarts=20, window_s=600, backoff_initial_s=1, backoff_max_s=30),
            )

        if settings.whales.enabled:
            onchain_cfg = settings.whales.onchain
            onchain = None
            if onchain_cfg.enabled:
                labels = (
                    AddressLabels.load(onchain_cfg.labels_file)
                    if onchain_cfg.labels_file
                    else AddressLabels()
                )
                onchain = OnchainWatcher(
                    BlockchairEthereumProvider(min_usd=onchain_cfg.min_usd), labels
                )
            radar = WhaleRadar(
                settings=settings.whales, bus=runtime.bus, db=runtime.db, onchain=onchain
            )
            radar.attach()
            runtime.whales = radar
            whale_services = list(runtime.market_data.values())
            runtime.supervisor.spawn(
                "whale-radar",
                lambda: radar.run(whale_services),
                RestartPolicy(max_restarts=20, window_s=600, backoff_initial_s=1, backoff_max_s=30),
            )

    @staticmethod
    async def _log_alert(alert: Alert) -> None:
        level = logging.CRITICAL if alert.severity is Severity.CRITICAL else logging.WARNING
        logger.log(level, alert.title, extra={"alert_message": alert.message, **alert.context})

    async def _heartbeat(self, runtime: EngineRuntime) -> None:
        interval = runtime.settings.heartbeat_interval_s
        warned = False
        while True:
            await asyncio.sleep(interval)
            lag = runtime.loop_monitor.last_ms
            await runtime.bus.publish(
                Heartbeat(
                    uptime_s=round(runtime.uptime_s, 3),
                    loop_lag_ms=round(lag, 3),
                    state=runtime.safety.state.state,
                    trading_mode=runtime.trading_mode.mode,
                )
            )
            too_slow = lag > runtime.settings.loop_lag_warning_ms
            if too_slow and not warned:
                await runtime.bus.publish(
                    Alert(
                        severity=Severity.WARNING,
                        title="Olay döngüsü gecikmesi yüksek",
                        message=f"Döngü gecikmesi {lag:.0f} ms; veri işleme gecikebilir.",
                    )
                )
            warned = too_slow

    @staticmethod
    def _install_signal_handlers(runtime: EngineRuntime) -> None:
        loop = asyncio.get_running_loop()
        if sys.platform == "win32":
            # Windows'ta loop.add_signal_handler yoktur; CTRL+C / CTRL+BREAK için klasik yol.
            def _handler(signum: int, frame: object) -> None:
                loop.call_soon_threadsafe(runtime.request_shutdown)

            signal.signal(signal.SIGINT, _handler)
            if hasattr(signal, "SIGBREAK"):
                signal.signal(signal.SIGBREAK, _handler)
            return
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, runtime.request_shutdown)
