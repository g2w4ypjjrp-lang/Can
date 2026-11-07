"""Motor durum makinesi.

::

    STARTING ──► SAFE_MODE ◄──► RUNNING
                    ▲  │           │
                    │  ▼           ▼
                    └─ HALTED ◄────┘        (acil durdurma)
    Her durumdan ──► STOPPING ──► STOPPED

* SAFE_MODE: Yeni pozisyon açılmaz. Açılışta, veri bağlantısı koptuğunda, borsa ile
  mutabakat tamamlanmadığında veya kritik bir görev çöktüğünde bu duruma geçilir.
* HALTED: Acil durdurma devrede. Yalnızca kullanıcı serbest bıraktığında SAFE_MODE'a döner.
"""

from __future__ import annotations

import asyncio

from ati_engine.core.bus import EventBus
from ati_engine.core.events import EngineStateChanged
from ati_engine.core.models import EngineState

ALLOWED_TRANSITIONS: dict[EngineState, frozenset[EngineState]] = {
    EngineState.STARTING: frozenset(
        {EngineState.SAFE_MODE, EngineState.HALTED, EngineState.STOPPING}
    ),
    EngineState.SAFE_MODE: frozenset(
        {EngineState.RUNNING, EngineState.HALTED, EngineState.STOPPING}
    ),
    EngineState.RUNNING: frozenset(
        {EngineState.SAFE_MODE, EngineState.HALTED, EngineState.STOPPING}
    ),
    EngineState.HALTED: frozenset({EngineState.SAFE_MODE, EngineState.STOPPING}),
    EngineState.STOPPING: frozenset({EngineState.STOPPED}),
    EngineState.STOPPED: frozenset(),
}

_MANAGE_ALLOWED = frozenset({EngineState.RUNNING, EngineState.SAFE_MODE, EngineState.HALTED})


class InvalidTransitionError(RuntimeError):
    pass


class EngineStateMachine:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._state = EngineState.STARTING
        self._reason = "açılış"
        self._lock = asyncio.Lock()

    @property
    def state(self) -> EngineState:
        return self._state

    @property
    def reason(self) -> str:
        return self._reason

    def can_open_positions(self) -> bool:
        return self._state is EngineState.RUNNING

    def can_manage_positions(self) -> bool:
        """Mevcut pozisyonları yönetme/kapatma (reduce-only) izni."""
        return self._state in _MANAGE_ALLOWED

    async def transition(self, target: EngineState, reason: str) -> bool:
        """Durum değiştirir. Zaten hedef durumdaysa False döner."""
        async with self._lock:
            if target is self._state:
                return False
            if target not in ALLOWED_TRANSITIONS[self._state]:
                raise InvalidTransitionError(
                    f"Geçersiz durum geçişi: {self._state.value} → {target.value}"
                )
            previous = self._state
            self._state = target
            self._reason = reason
        await self._bus.publish(
            EngineStateChanged(previous=previous, current=target, reason=reason)
        )
        return True
