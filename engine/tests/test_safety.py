from __future__ import annotations

import asyncio

import pytest

from ati_engine.config import EngineSettings
from ati_engine.core.bus import EventBus
from ati_engine.core.clock import ManualClock
from ati_engine.core.events import EngineStateChanged, Event, TradingModeChanged
from ati_engine.core.models import EngineState, TradingMode
from ati_engine.safety.coordinator import SafetyCoordinator
from ati_engine.safety.kill_switch import (
    RELEASE_CONFIRMATION,
    KillSwitch,
    KillSwitchConfirmationError,
)
from ati_engine.safety.state import EngineStateMachine, InvalidTransitionError
from ati_engine.safety.trading_mode import (
    LIVE_TRADING_ACK_PHRASE,
    CheckResult,
    TradingModeController,
)
from ati_engine.storage.audit import AuditLog
from ati_engine.storage.database import Database
from ati_engine.storage.settings_store import SettingsStore


async def _settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


class _Pass:
    name = "always_pass"

    async def evaluate(self) -> CheckResult:
        return CheckResult(self.name, True, "ok")


# --- Durum makinesi -----------------------------------------------------------------


async def test_state_machine_rejects_invalid_transition(bus: EventBus) -> None:
    sm = EngineStateMachine(bus)
    assert sm.state is EngineState.STARTING
    with pytest.raises(InvalidTransitionError):
        await sm.transition(EngineState.RUNNING, "atlama")
    await sm.transition(EngineState.SAFE_MODE, "açılış")
    assert not sm.can_open_positions()
    assert sm.can_manage_positions()
    await sm.transition(EngineState.RUNNING, "hazır")
    assert sm.can_open_positions()


async def test_state_changes_are_published(bus: EventBus) -> None:
    events: list[EngineStateChanged] = []
    bus.subscribe(EngineStateChanged, events.append, name="t")
    sm = EngineStateMachine(bus)
    await sm.transition(EngineState.SAFE_MODE, "açılış")
    await _settle()
    assert events[0].previous is EngineState.STARTING
    assert events[0].current is EngineState.SAFE_MODE


# --- Koordinatör ve hazırlık koşulları --------------------------------------------------


async def test_boot_goes_running_when_no_conditions(coordinator: SafetyCoordinator) -> None:
    await coordinator.boot_complete()
    assert coordinator.state.state is EngineState.RUNNING


async def test_lost_condition_forces_safe_mode(coordinator: SafetyCoordinator) -> None:
    coordinator.register_condition("market_data.spot")
    await coordinator.boot_complete()
    assert coordinator.state.state is EngineState.SAFE_MODE

    await coordinator.set_ready("market_data.spot", True, "bağlı")
    assert coordinator.state.state is EngineState.RUNNING

    # Bağlantı koptu: yeni pozisyon açılamaz, mevcutlar yönetilebilir.
    await coordinator.set_ready("market_data.spot", False, "bağlantı koptu")
    assert coordinator.state.state is EngineState.SAFE_MODE
    assert not coordinator.state.can_open_positions()
    assert coordinator.state.can_manage_positions()
    assert "market_data.spot" in coordinator.state.reason


async def test_unknown_condition_rejected(coordinator: SafetyCoordinator) -> None:
    with pytest.raises(KeyError):
        await coordinator.set_ready("yok", True)
    coordinator.register_condition("x")
    with pytest.raises(ValueError, match="zaten"):
        coordinator.register_condition("x")


async def test_enter_safe_mode_from_running(coordinator: SafetyCoordinator) -> None:
    await coordinator.boot_complete()
    await coordinator.enter_safe_mode("kritik görev durdu")
    assert coordinator.state.state is EngineState.SAFE_MODE


# --- Acil durdurma ----------------------------------------------------------------------


async def test_kill_switch_halts_and_requires_confirmation(coordinator: SafetyCoordinator) -> None:
    await coordinator.boot_complete()
    assert await coordinator.engage_kill_switch(reason="piyasa çöküşü", actor="kullanıcı")
    assert coordinator.state.state is EngineState.HALTED
    assert not coordinator.state.can_open_positions()
    assert coordinator.state.can_manage_positions()  # pozisyon kapatmak serbest
    # İkinci kez devreye alma değişiklik yapmaz.
    assert not await coordinator.engage_kill_switch(reason="tekrar", actor="kullanıcı")

    with pytest.raises(KillSwitchConfirmationError):
        await coordinator.release_kill_switch(actor="kullanıcı", confirmation="evet")
    assert coordinator.state.state is EngineState.HALTED

    assert await coordinator.release_kill_switch(
        actor="kullanıcı", confirmation=RELEASE_CONFIRMATION
    )
    assert coordinator.state.state is EngineState.RUNNING


async def test_kill_switch_survives_restart(
    db: Database, audit: AuditLog, clock: ManualClock
) -> None:
    bus1 = EventBus()
    ks1 = KillSwitch(store=SettingsStore(db, clock), audit=audit, bus=bus1, clock=clock)
    await ks1.load()
    await ks1.engage(reason="test", actor="kullanıcı")
    await bus1.close()

    # "Yeniden başlatma": yeni nesneler, aynı veritabanı.
    bus2 = EventBus()
    ks2 = KillSwitch(store=SettingsStore(db, clock), audit=audit, bus=bus2, clock=clock)
    status = await ks2.load()
    assert status.engaged
    assert status.reason == "test"
    coordinator = SafetyCoordinator(bus=bus2, state=EngineStateMachine(bus2), kill_switch=ks2)
    await coordinator.boot_complete()
    assert coordinator.state.state is EngineState.HALTED
    await bus2.close()


async def test_kill_switch_actions_are_audited(
    coordinator: SafetyCoordinator, audit: AuditLog
) -> None:
    await coordinator.boot_complete()
    await coordinator.engage_kill_switch(reason="r", actor="ios:cihaz-1")
    with pytest.raises(KillSwitchConfirmationError):
        await coordinator.release_kill_switch(actor="x", confirmation="")
    actions = [e["action"] for e in await audit.recent()]
    assert actions == ["kill_switch.release_rejected", "kill_switch.engage"]


# --- İşlem modu ve gerçek işlem kilidi ---------------------------------------------------


@pytest.fixture
def live_settings(tmp_path) -> EngineSettings:  # type: ignore[no-untyped-def]
    return EngineSettings(data_dir=tmp_path / "d", live_trading_enabled=True)


async def test_engine_starts_in_paper(
    settings: EngineSettings, bus: EventBus, audit: AuditLog, kill_switch: KillSwitch
) -> None:
    controller = TradingModeController(
        settings=settings, bus=bus, audit=audit, kill_switch=kill_switch
    )
    assert controller.mode is TradingMode.PAPER


async def test_live_is_impossible_in_phase_one(
    live_settings: EngineSettings, bus: EventBus, audit: AuditLog, kill_switch: KillSwitch
) -> None:
    """Ayar açık ve onay ifadesi doğru olsa bile yürütücü olmadığı için LIVE reddedilir."""
    controller = TradingModeController(
        settings=live_settings, bus=bus, audit=audit, kill_switch=kill_switch
    )
    result = await controller.request_mode(
        TradingMode.LIVE, actor="kullanıcı", acknowledgement=LIVE_TRADING_ACK_PHRASE
    )
    assert not result.accepted
    assert controller.mode is TradingMode.PAPER
    failed = {c.name for c in result.checks if not c.passed}
    assert failed == {"live_execution_available"}


async def test_live_requires_every_prerequisite(
    settings: EngineSettings, bus: EventBus, audit: AuditLog, kill_switch: KillSwitch
) -> None:
    controller = TradingModeController(
        settings=settings, bus=bus, audit=audit, kill_switch=kill_switch, checks=[_Pass()]
    )
    result = await controller.request_mode(TradingMode.LIVE, actor="u", acknowledgement="evet")
    failed = {c.name for c in result.checks if not c.passed}
    assert failed == {"config_live_enabled", "user_acknowledgement"}
    assert controller.mode is TradingMode.PAPER


async def test_live_blocked_by_kill_switch(
    live_settings: EngineSettings, bus: EventBus, audit: AuditLog, kill_switch: KillSwitch
) -> None:
    await kill_switch.engage(reason="r", actor="u")
    controller = TradingModeController(
        settings=live_settings, bus=bus, audit=audit, kill_switch=kill_switch, checks=[_Pass()]
    )
    result = await controller.request_mode(
        TradingMode.LIVE, actor="u", acknowledgement=LIVE_TRADING_ACK_PHRASE
    )
    assert not result.accepted
    assert {c.name for c in result.checks if not c.passed} == {"kill_switch_released"}


async def test_live_accepted_only_when_all_checks_pass(
    live_settings: EngineSettings, bus: EventBus, audit: AuditLog, kill_switch: KillSwitch
) -> None:
    events: list[Event] = []
    bus.subscribe(TradingModeChanged, events.append, name="t")
    controller = TradingModeController(
        settings=live_settings, bus=bus, audit=audit, kill_switch=kill_switch, checks=[_Pass()]
    )
    result = await controller.request_mode(
        TradingMode.LIVE, actor="u", acknowledgement=f"  {LIVE_TRADING_ACK_PHRASE} "
    )
    assert result.accepted
    assert controller.mode is TradingMode.LIVE
    await _settle()
    assert len(events) == 1
    # Kayıt: hem kabul hem ret denetim kaydına yazılır.
    entries = await audit.recent()
    assert entries[0]["action"] == "trading_mode.request"
    assert entries[0]["details"]["accepted"] is True


async def test_failing_check_exception_is_a_failure(
    live_settings: EngineSettings, bus: EventBus, audit: AuditLog, kill_switch: KillSwitch
) -> None:
    class Broken:
        name = "broken"

        async def evaluate(self) -> CheckResult:
            raise RuntimeError("ağ hatası")

    controller = TradingModeController(
        settings=live_settings, bus=bus, audit=audit, kill_switch=kill_switch, checks=[Broken()]
    )
    result = await controller.request_mode(
        TradingMode.LIVE, actor="u", acknowledgement=LIVE_TRADING_ACK_PHRASE
    )
    assert not result.accepted
    assert any(c.name == "broken" and "ağ hatası" in c.message for c in result.checks)


async def test_paper_and_testnet_need_no_acknowledgement(
    settings: EngineSettings, bus: EventBus, audit: AuditLog, kill_switch: KillSwitch
) -> None:
    controller = TradingModeController(
        settings=settings, bus=bus, audit=audit, kill_switch=kill_switch
    )
    assert (await controller.request_mode(TradingMode.TESTNET, actor="u")).accepted
    assert (await controller.request_mode(TradingMode.PAPER, actor="u")).accepted
