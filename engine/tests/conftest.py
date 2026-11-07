from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from ati_engine.config import EngineSettings
from ati_engine.core.bus import EventBus
from ati_engine.core.clock import ManualClock
from ati_engine.safety.coordinator import SafetyCoordinator
from ati_engine.safety.kill_switch import KillSwitch
from ati_engine.safety.state import EngineStateMachine
from ati_engine.storage.audit import AuditLog
from ati_engine.storage.database import Database
from ati_engine.storage.settings_store import SettingsStore


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Testlerin geliştiricinin gerçek ayarlarını/veri dizinini okumasını engelle."""
    import os

    for key in list(os.environ):
        if key.startswith("ATI_"):
            monkeypatch.delenv(key, raising=False)
    # Testler gerçek Binance'e bağlanmaz; piyasa verisi testleri sahte sunucu kullanır.
    monkeypatch.setenv("ATI_MARKET_DATA__ENABLED", "false")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))


@pytest.fixture
def settings(tmp_path: Path) -> EngineSettings:
    return EngineSettings(data_dir=tmp_path / "data", log_to_console=False)


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(tmp_path / "engine.db")
    await database.open()
    await database.migrate()
    yield database
    await database.close()


@pytest.fixture
async def bus() -> AsyncIterator[EventBus]:
    event_bus = EventBus()
    yield event_bus
    await event_bus.close()


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock(start_ms=1_700_000_000_000)


@pytest.fixture
def audit(db: Database, clock: ManualClock) -> AuditLog:
    return AuditLog(db, clock)


@pytest.fixture
async def kill_switch(
    db: Database, audit: AuditLog, bus: EventBus, clock: ManualClock
) -> KillSwitch:
    ks = KillSwitch(store=SettingsStore(db, clock), audit=audit, bus=bus, clock=clock)
    await ks.load()
    return ks


@pytest.fixture
def coordinator(bus: EventBus, kill_switch: KillSwitch) -> SafetyCoordinator:
    return SafetyCoordinator(bus=bus, state=EngineStateMachine(bus), kill_switch=kill_switch)
