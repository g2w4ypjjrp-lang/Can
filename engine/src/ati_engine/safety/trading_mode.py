"""İşlem modu denetleyicisi ve gerçek işlem (LIVE) kilidi.

Motor her açılışta PAPER (sanal işlem) modunda başlar. LIVE moduna geçiş için şunların
TAMAMI gerekir:

1. Ayar dosyasında ``live_trading_enabled = true`` (kullanıcının bilinçli tercihi).
2. Çalışma anında onay ifadesinin birebir girilmesi (``LIVE_TRADING_ACK_PHRASE``).
3. Acil durdurmanın kapalı olması.
4. Kayıtlı ek kontrollerin geçmesi. Aşama 1'de "gerçek emir yürütücüsü henüz yok"
   kontrolü kayıtlıdır ve her zaman başarısız olur; yani bu aşamada gerçek işlem
   teknik olarak İMKÂNSIZDIR. Aşama 10'da yürütme kodu eklendi ancak kontrol kullanıcı
   onayları (G1: canlı anahtar, G2: ilk gerçek işlem) verilene kadar kayıtlı kalır; ayrıca
   Binance yürütücüsü LIVE modda kurulamaz ve canlı anahtar kasaya yazılamaz.

Her deneme (başarılı/başarısız) denetim kaydına yazılır.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from ati_engine.config import EngineSettings
from ati_engine.core.bus import EventBus
from ati_engine.core.events import TradingModeChanged
from ati_engine.core.models import TradingMode
from ati_engine.safety.kill_switch import KillSwitch
from ati_engine.storage.audit import AuditLog

LIVE_TRADING_ACK_PHRASE = "GERCEK PARA ILE ISLEM YAPILMASINI ONAYLIYORUM"


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    message: str


class LiveTradingCheck(Protocol):
    name: str

    async def evaluate(self) -> CheckResult: ...


LIVE_LOCKED_MESSAGE = (
    "Gerçek hesapla işlem bu sürümde kilitlidir. Yürütme kodu hazırdır ve Binance test ağında "
    "denenebilir; gerçek hesap için kullanıcının açık onayları gerekir: G1 (işlem yetkili, para "
    "çekme yetkisi KAPALI canlı API anahtarı) ve G2 (ilk gerçek para işlemi). Bu sürümde "
    "yalnızca sanal işlem (PAPER) ve test ağı (TESTNET) kullanılabilir."
)


class LiveTradingLocked(PermissionError):
    """Gerçek hesapla işlem kullanıcı onayları (G1/G2) olmadan teknik olarak imkânsızdır."""


class LiveExecutionUnavailableCheck:
    """Kullanıcı onayları (G1/G2) verilene kadar LIVE modunu kesin olarak engeller."""

    name = "live_execution_available"

    async def evaluate(self) -> CheckResult:
        return CheckResult(self.name, False, LIVE_LOCKED_MESSAGE)


@dataclass(frozen=True)
class ModeChangeResult:
    accepted: bool
    mode: TradingMode
    checks: tuple[CheckResult, ...]


class TradingModeController:
    def __init__(
        self,
        *,
        settings: EngineSettings,
        bus: EventBus,
        audit: AuditLog,
        kill_switch: KillSwitch,
        checks: Sequence[LiveTradingCheck] | None = None,
    ) -> None:
        self._settings = settings
        self._bus = bus
        self._audit = audit
        self._kill_switch = kill_switch
        self._checks: list[LiveTradingCheck] = (
            list(checks) if checks is not None else [LiveExecutionUnavailableCheck()]
        )
        self._mode = TradingMode.PAPER
        self._lock = asyncio.Lock()

    @property
    def mode(self) -> TradingMode:
        return self._mode

    def add_check(self, check: LiveTradingCheck) -> None:
        self._checks.append(check)

    async def _live_checks(self, acknowledgement: str | None) -> list[CheckResult]:
        results = [
            CheckResult(
                "config_live_enabled",
                self._settings.live_trading_enabled,
                "Ayar dosyasında live_trading_enabled = true olmalı"
                if not self._settings.live_trading_enabled
                else "Ayar dosyasında gerçek işlem etkin",
            ),
            CheckResult(
                "user_acknowledgement",
                (acknowledgement or "").strip() == LIVE_TRADING_ACK_PHRASE,
                "Onay ifadesi birebir girilmeli: " + LIVE_TRADING_ACK_PHRASE,
            ),
            CheckResult(
                "kill_switch_released",
                not self._kill_switch.engaged,
                "Acil durdurma devrede" if self._kill_switch.engaged else "Acil durdurma kapalı",
            ),
        ]
        for check in self._checks:
            try:
                results.append(await check.evaluate())
            except Exception as exc:
                results.append(CheckResult(check.name, False, f"Kontrol hata verdi: {exc}"))
        return results

    async def request_mode(
        self, target: TradingMode, *, actor: str, acknowledgement: str | None = None
    ) -> ModeChangeResult:
        async with self._lock:
            checks: list[CheckResult] = []
            if target is TradingMode.LIVE:
                checks = await self._live_checks(acknowledgement)
            accepted = all(c.passed for c in checks)
            await self._audit.record(
                actor=actor,
                action="trading_mode.request",
                details={
                    "from": self._mode.value,
                    "to": target.value,
                    "accepted": accepted,
                    "failed_checks": [c.name for c in checks if not c.passed],
                },
            )
            if not accepted:
                return ModeChangeResult(False, self._mode, tuple(checks))
            previous = self._mode
            self._mode = target
        if previous is not target:
            await self._bus.publish(
                TradingModeChanged(previous=previous, current=target, actor=actor)
            )
        return ModeChangeResult(True, target, tuple(checks))
