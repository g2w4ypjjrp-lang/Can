"""Güvenlik koordinatörü: durum makinesini, acil durdurmayı ve hazırlık koşullarını birleştirir.

Hazırlık koşulları (readiness conditions), motorun yeni pozisyon açabilmesi için doğru
olması gereken önermelerdir. Her alt sistem kendi koşulunu kaydeder ve günceller:

* Aşama 2: ``market_data.spot`` / ``market_data.futures`` - WebSocket akışları canlı mı?
* Aşama 10: ``exchange.reconciled`` - yerel emir/pozisyon durumu borsa ile eşleşti mi?
* Aşama 11: ``risk.daily_loss`` - günlük zarar sınırı aşılmadı mı?
* Aşama 15: ``license.valid`` - lisans kirası geçerli mi?

Koşullardan biri bile yanlışsa motor RUNNING'den SAFE_MODE'a iner; hepsi doğru olunca
(ve acil durdurma kapalıysa) SAFE_MODE'dan RUNNING'e çıkar. "Beklenmeyen bağlantı
kesintisinde güvenli moda geçme" gereksinimi bu mekanizmayla karşılanır.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ati_engine.core.bus import EventBus
from ati_engine.core.events import ReadinessChanged
from ati_engine.core.models import EngineState
from ati_engine.safety.kill_switch import KillSwitch
from ati_engine.safety.state import EngineStateMachine


@dataclass
class Condition:
    name: str
    ready: bool
    detail: str


class SafetyCoordinator:
    def __init__(
        self, *, bus: EventBus, state: EngineStateMachine, kill_switch: KillSwitch
    ) -> None:
        self._bus = bus
        self._state = state
        self._kill_switch = kill_switch
        self._conditions: dict[str, Condition] = {}
        self._lock = asyncio.Lock()
        self._booted = False

    @property
    def state(self) -> EngineStateMachine:
        return self._state

    @property
    def kill_switch(self) -> KillSwitch:
        return self._kill_switch

    def register_condition(self, name: str, *, ready: bool = False, detail: str = "") -> None:
        if name in self._conditions:
            raise ValueError(f"'{name}' hazırlık koşulu zaten kayıtlı")
        self._conditions[name] = Condition(
            name, ready, detail or ("hazır" if ready else "bekleniyor")
        )

    def conditions(self) -> list[Condition]:
        return list(self._conditions.values())

    async def set_ready(self, name: str, ready: bool, detail: str = "") -> None:
        condition = self._conditions.get(name)
        if condition is None:
            raise KeyError(f"Bilinmeyen hazırlık koşulu: {name}")
        changed = condition.ready != ready or condition.detail != detail
        condition.ready = ready
        condition.detail = detail
        if changed:
            await self._bus.publish(ReadinessChanged(condition=name, ready=ready, detail=detail))
        await self.reevaluate()

    async def boot_complete(self) -> None:
        """Açılış tamamlandı: STARTING → SAFE_MODE (veya acil durdurma devredeyse HALTED)."""
        self._booted = True
        await self.reevaluate()

    async def engage_kill_switch(self, *, reason: str, actor: str) -> bool:
        changed = await self._kill_switch.engage(reason=reason, actor=actor)
        await self.reevaluate()
        return changed

    async def release_kill_switch(self, *, actor: str, confirmation: str) -> bool:
        changed = await self._kill_switch.release(actor=actor, confirmation=confirmation)
        await self.reevaluate()
        return changed

    async def enter_safe_mode(self, reason: str) -> None:
        """Bir alt sistemin isteğiyle (ör. denetlenen görev çöktü) güvenli moda geç."""
        async with self._lock:
            if self._state.state is EngineState.RUNNING:
                await self._state.transition(EngineState.SAFE_MODE, reason)

    async def reevaluate(self) -> None:
        async with self._lock:
            current = self._state.state
            if current in (EngineState.STOPPING, EngineState.STOPPED):
                return
            if current is EngineState.STARTING and not self._booted:
                return
            if self._kill_switch.engaged:
                if current is not EngineState.HALTED:
                    reason = self._kill_switch.status.reason or "acil durdurma"
                    await self._state.transition(EngineState.HALTED, f"acil durdurma: {reason}")
                return
            if current in (EngineState.STARTING, EngineState.HALTED):
                await self._state.transition(
                    EngineState.SAFE_MODE, "güvenlik kontrolleri bekleniyor"
                )
                current = EngineState.SAFE_MODE
            not_ready = [c.name for c in self._conditions.values() if not c.ready]
            if not not_ready and current is EngineState.SAFE_MODE:
                await self._state.transition(EngineState.RUNNING, "tüm hazırlık koşulları sağlandı")
            elif not_ready and current is EngineState.RUNNING:
                await self._state.transition(
                    EngineState.SAFE_MODE, "hazır olmayan koşullar: " + ", ".join(sorted(not_ready))
                )

    async def shutdown(self, reason: str = "kapatılıyor") -> None:
        async with self._lock:
            if self._state.state not in (EngineState.STOPPING, EngineState.STOPPED):
                await self._state.transition(EngineState.STOPPING, reason)
