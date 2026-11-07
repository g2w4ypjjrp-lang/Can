"""Acil durdurma (kill switch).

* Durum SQLite'ta kalıcıdır: motor yeniden başlasa bile acil durdurma devrede kalır.
* Devreye alma her zaman serbesttir (masaüstü, iOS, risk motoru, kullanıcı).
* Serbest bırakma yalnızca açık bir onay ifadesiyle yapılabilir.
* Devreye alındığında ``KillSwitchEngaged`` olayı yayımlanır; işlem motoru (Aşama 10) bu
  olayla bekleyen giriş emirlerini iptal eder; koruyucu stop emirlerine dokunmaz.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ati_engine.core.bus import EventBus
from ati_engine.core.clock import Clock, SystemClock
from ati_engine.core.events import KillSwitchEngaged, KillSwitchReleased
from ati_engine.storage.audit import AuditLog
from ati_engine.storage.settings_store import SettingsStore

SETTINGS_KEY = "safety.kill_switch"
RELEASE_CONFIRMATION = "SERBEST BIRAK"


class KillSwitchConfirmationError(ValueError):
    pass


@dataclass(frozen=True)
class KillSwitchStatus:
    engaged: bool
    reason: str | None = None
    actor: str | None = None
    since_ms: int | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "engaged": self.engaged,
            "reason": self.reason,
            "actor": self.actor,
            "since_ms": self.since_ms,
        }


class KillSwitch:
    def __init__(
        self,
        *,
        store: SettingsStore,
        audit: AuditLog,
        bus: EventBus,
        clock: Clock | None = None,
    ) -> None:
        self._store = store
        self._audit = audit
        self._bus = bus
        self._clock = clock or SystemClock()
        self._status = KillSwitchStatus(engaged=False)

    @property
    def status(self) -> KillSwitchStatus:
        return self._status

    @property
    def engaged(self) -> bool:
        return self._status.engaged

    async def load(self) -> KillSwitchStatus:
        raw = await self._store.get(SETTINGS_KEY)
        if raw:
            self._status = KillSwitchStatus(
                engaged=bool(raw.get("engaged")),
                reason=raw.get("reason"),
                actor=raw.get("actor"),
                since_ms=raw.get("since_ms"),
            )
        return self._status

    async def engage(self, *, reason: str, actor: str) -> bool:
        """Acil durdurmayı devreye alır. Zaten devredeyse False döner."""
        if self._status.engaged:
            return False
        reason = reason.strip() or "belirtilmedi"
        self._status = KillSwitchStatus(
            engaged=True, reason=reason, actor=actor, since_ms=self._clock.now_ms()
        )
        await self._store.set(SETTINGS_KEY, self._status.to_json())
        await self._audit.record(
            actor=actor, action="kill_switch.engage", details={"reason": reason}
        )
        await self._bus.publish(KillSwitchEngaged(reason=reason, actor=actor))
        return True

    async def release(self, *, actor: str, confirmation: str) -> bool:
        if confirmation.strip().upper() != RELEASE_CONFIRMATION:
            await self._audit.record(actor=actor, action="kill_switch.release_rejected", details={})
            raise KillSwitchConfirmationError(
                f"Acil durdurmayı kaldırmak için '{RELEASE_CONFIRMATION}' yazılmalıdır"
            )
        if not self._status.engaged:
            return False
        self._status = KillSwitchStatus(engaged=False)
        await self._store.set(SETTINGS_KEY, self._status.to_json())
        await self._audit.record(actor=actor, action="kill_switch.release", details={})
        await self._bus.publish(KillSwitchReleased(actor=actor))
        return True
