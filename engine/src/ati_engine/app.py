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
from ati_engine.api.server import bind_socket, build_server, create_app
from ati_engine.config import EngineSettings
from ati_engine.core.bus import EventBus, OverflowPolicy
from ati_engine.core.events import Alert, Heartbeat
from ati_engine.core.models import EngineState, Severity
from ati_engine.core.supervisor import RestartPolicy, TaskSupervisor
from ati_engine.observability.logging import configure_logging
from ati_engine.observability.loop_monitor import LoopLagMonitor
from ati_engine.runtime import EngineRuntime
from ati_engine.safety.coordinator import SafetyCoordinator
from ati_engine.safety.kill_switch import KillSwitch
from ati_engine.safety.state import EngineStateMachine
from ati_engine.safety.trading_mode import TradingModeController
from ati_engine.security.vault import SecretVault, default_cipher
from ati_engine.storage.audit import AuditLog
from ati_engine.storage.database import Database
from ati_engine.storage.settings_store import SettingsStore
from ati_engine.system.single_instance import SingleInstanceLock

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
