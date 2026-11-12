"""Aşama 11: risk kapısı (her kural için ret), kapıyı atlayan kod yolu olmadığı, hesap
izleyici (kalıcı gün başı özsermaye) ve bağımsız risk bekçisi."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ati_engine.config import RiskLimits
from ati_engine.core.bus import EventBus
from ati_engine.core.events import Alert
from ati_engine.core.models import (
    EngineState,
    Market,
    OrderStatus,
    OrderType,
    Side,
    TradingMode,
)
from ati_engine.execution.approval import ApprovalError, RiskApproval, RiskRejected
from ati_engine.execution.engine import TakeProfit, TradeIntent, TradingEngine
from ati_engine.execution.orders import OrderManager
from ati_engine.execution.paper_venue import PaperVenue
from ati_engine.execution.reconcile import Reconciler
from ati_engine.execution.venue import OcoRequest, OrderRequest, VenuePosition
from ati_engine.risk.account import AccountMonitor
from ati_engine.risk.gate import (
    RiskGate,
    liquidation_distance_pct,
    size_for_risk,
    trade_risk,
)
from ati_engine.risk.guard import DAILY_LOSS_CONDITION, RiskGuard, stream_condition
from ati_engine.safety.coordinator import SafetyCoordinator
from ati_engine.storage.database import Database
from risk_helpers import approve, make_gate
from test_execution import ExactFills, info

D = Decimal
DAY_MS = 86_400_000
T0 = 1_794_085_000_000  # 2026-11-07 20:56 (UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> int:
        return self.now


@dataclass
class Setup:
    engine: TradingEngine
    venue: PaperVenue
    gate: RiskGate
    monitor: AccountMonitor
    clock: Clock
    state: list[EngineState]
    mode: list[TradingMode]


async def setup(
    db: Database,
    market: Market = Market.USDM_FUTURES,
    *,
    equity: str = "10000",
    limits: RiskLimits | None = None,
    venue: PaperVenue | None = None,
) -> Setup:
    venue = venue or PaperVenue(market, fills=ExactFills(), initial_quote=D(equity))
    venue.prices["BTCUSDT"] = D(100)
    clock = Clock()
    state = [EngineState.RUNNING]
    mode = [venue.mode]
    holder: list[TradingEngine] = []
    gate = make_gate(
        db,
        venue.mode,
        holder,
        limits=limits,
        state=lambda: state[0],
        trading_mode=lambda: mode[0],
        clock=clock,
    )
    gate.monitor._clock = clock
    engine = TradingEngine(
        venue=venue,
        db=db,
        symbols=lambda s: info(s, market),
        risk_gate=gate,
        engine_state=lambda: EngineState.RUNNING,  # motorun kendi denetimi ayrı test edilir
        fill_timeout_s=2.0,
    )
    holder.append(engine)
    await engine.start()
    return Setup(engine, venue, gate, gate.monitor, clock, state, mode)


def intent(**kw: Any) -> TradeIntent:
    values: dict[str, Any] = {
        "decision_id": f"risk-{kw.pop('n', 1)}",
        "market": Market.USDM_FUTURES,
        "symbol": "BTCUSDT",
        "direction": 1,
        "quantity": D("1"),
        "reference_price": D(100),
        "stop_loss": D(98),
        "take_profits": (TakeProfit(D(106), D(1)),),
        "leverage": 2,
    }
    values.update(kw)
    return TradeIntent(**values)


async def codes(s: Setup, i: TradeIntent) -> list[str]:
    decision = await s.gate.evaluate(i, s.engine)
    assert decision.approved is (not decision.reasons)
    return [r.code for r in decision.reasons]


# --- Hesaplamalar ----------------------------------------------------------------------------------


def test_risk_math() -> None:
    risk = trade_risk(
        quantity=D(2), entry=D(100), stop=D(95), fee_rate=D("0.0005"), slippage_pct=D("0.05")
    )
    assert risk == D(10) + D("0.2") + D("0.1")
    qty = size_for_risk(
        equity=D(10_000),
        risk_pct=D("0.5"),
        entry=D(100),
        stop=D(95),
        fee_rate=D("0.0005"),
        slippage_pct=D("0.05"),
        step=D("0.001"),
    )
    assert qty == D("9.708")  # 50 / 5.15, aşağı yuvarlandı
    risk_at_size = trade_risk(
        quantity=qty, entry=D(100), stop=D(95), fee_rate=D("0.0005"), slippage_pct=D("0.05")
    )
    assert risk_at_size <= D(50)
    assert (
        liquidation_distance_pct(
            leverage=3, equity=D(10_000), total_notional=D(1000), maintenance_rate=D("0.01")
        )
        == D("100") / 3 - 1
    )
    # Çapraz teminatta toplam pozisyon büyükse daha yakın tahmin kullanılır.
    assert liquidation_distance_pct(
        leverage=10, equity=D(10_000), total_notional=D(100_000), maintenance_rate=D("0.01")
    ) == D(9)


# --- Her kural için ret ----------------------------------------------------------------------------


async def test_clean_intent_is_approved_with_signed_approval(db: Database) -> None:
    s = await setup(db)
    decision = await s.gate.evaluate(intent(), s.engine)
    assert decision.approved and decision.approval is not None
    assert decision.approval.max_quantity == D(1) and decision.approval.side is Side.BUY
    # (1 x 2 fiyat farkı + 0,1 komisyon + 0,05 kayma) / 10.000
    assert decision.metrics["trade_risk_pct"] == pytest.approx(0.0215)
    await s.engine.stop()


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"stop_loss": None}, "stop_required"),
        ({"stop_loss": D(101)}, "stop_side"),
        ({"direction": -1, "stop_loss": D(99)}, "stop_side"),
        ({"symbol": "ETHUSDT"}, "no_price"),
        ({"reference_price": D(102), "stop_loss": D(100)}, "price_deviation"),
        ({"quantity": D(20), "stop_loss": D(95)}, "risk_per_trade"),
        ({"leverage": 5}, "leverage"),
        ({"quantity": D(400), "stop_loss": D("99.99")}, "total_leverage"),
    ],
)
async def test_intent_rules_reject(db: Database, change: dict[str, Any], code: str) -> None:
    s = await setup(db)
    assert code in await codes(s, intent(**change))
    await s.engine.stop()


async def test_engine_state_and_mode_rules(db: Database) -> None:
    s = await setup(db)
    s.state[0] = EngineState.SAFE_MODE
    assert "engine_state" in await codes(s, intent())
    s.state[0] = EngineState.HALTED
    assert "engine_state" in await codes(s, intent())
    s.state[0] = EngineState.RUNNING
    s.mode[0] = TradingMode.LIVE
    assert "mode_mismatch" in await codes(s, intent())
    await s.engine.stop()


async def test_account_rules(db: Database) -> None:
    s = await setup(db)

    async def broken() -> list[Any]:
        raise ConnectionError("borsa yok")

    original = s.venue.balances
    s.venue.balances = broken  # type: ignore[method-assign]
    assert "account_unavailable" in await codes(s, intent())
    s.venue.balances = original  # type: ignore[method-assign]
    s.venue.wallet["USDT"] = D(0)
    s.monitor.last = None
    assert "no_equity" in await codes(s, intent())
    await s.engine.stop()


async def test_daily_loss_budget_and_halt(db: Database) -> None:
    s = await setup(db)
    await s.monitor.refresh()  # gün başı: 10.000
    s.venue.wallet["USDT"] = D(9_820)  # bugün %1,8 kayıp
    s.monitor.last = None
    # Kalan bütçe 20; bu işlemin riski ~41 → ret (işlem başına risk sınırı içinde olsa da).
    assert await codes(s, intent(quantity=D("1.9"), stop_loss=D(78))) == ["daily_loss_budget"]
    assert await codes(s, intent(quantity=D("0.1"))) == []
    await s.monitor.halt_day("test")
    assert "daily_halt" in await codes(s, intent(quantity=D("0.1")))
    await s.engine.stop()


async def test_max_open_positions(db: Database) -> None:
    s = await setup(db)
    for symbol in ("AUSDT", "BUSDT", "CUSDT"):
        s.venue.futures_positions[symbol] = (D("0.1"), D(10))
        s.venue.prices[symbol] = D(10)
    s.monitor.last = None
    assert "max_open_positions" in await codes(s, intent())
    await s.engine.stop()


async def test_liquidation_rules(db: Database) -> None:
    loose = RiskLimits(max_leverage=10, max_total_leverage=D(20))
    s = await setup(db, limits=loose)
    # 10x: ayrık tasfiye uzaklığı %9 < %15
    assert "liquidation_distance" in await codes(s, intent(leverage=10))
    # 5x: uzaklık %19 ama stop %20 uzakta → stop tasfiyenin ötesinde
    assert await codes(s, intent(leverage=5, quantity=D("0.1"), stop_loss=D(80))) == [
        "stop_beyond_liq"
    ]
    await s.engine.stop()


async def test_spot_leverage_rule(db: Database) -> None:
    s = await setup(db, Market.SPOT)
    assert "spot_leverage" in await codes(s, intent(market=Market.SPOT, leverage=2))
    assert await codes(s, intent(market=Market.SPOT, leverage=None)) == []
    await s.engine.stop()


async def test_rejection_is_recorded_and_no_order_is_sent(db: Database) -> None:
    s = await setup(db)
    placed: list[OrderRequest] = []
    original = s.venue.place

    async def spy(request: OrderRequest) -> Any:
        placed.append(request)
        return await original(request)

    s.venue.place = spy  # type: ignore[method-assign]
    with pytest.raises(RiskRejected) as caught:
        await s.engine.open(intent(quantity=D(50), stop_loss=D(90), n=7))
    assert [r.code for r in caught.value.decision.reasons] == [
        "risk_per_trade",
        "daily_loss_budget",
    ]
    assert placed == [] and s.venue.leverage == {}  # kaldıraç bile ayarlanmadı
    row = await db.fetchone(
        "SELECT risk_verdict, risk_reasons, outcome FROM decisions WHERE id = 'risk-7'"
    )
    assert row is not None and row[0] == "rejected" and row[2] == "not_executed"
    assert "risk_per_trade" in row[1]
    event = await db.fetchone("SELECT rule, action FROM risk_events ORDER BY id DESC LIMIT 1")
    assert event == ("gate.risk_per_trade", "işlem açılmadı")
    assert s.engine.managed["BTCUSDT"].state == "rejected"
    managed = await s.engine.open(intent(n=8))  # aynı sembolde sonraki uygun işlem açılabilir
    assert managed.state == "open"
    row = await db.fetchone("SELECT risk_verdict FROM decisions WHERE id = 'risk-8'")
    assert row == ("approved",)
    await s.engine.stop()


async def test_concurrent_opens_respect_position_limit(db: Database) -> None:
    import asyncio

    s = await setup(db, limits=RiskLimits(max_open_positions=1))
    s.venue.prices["ETHUSDT"] = D(100)
    results = await asyncio.gather(
        s.engine.open(intent(n=1)),
        s.engine.open(intent(n=2, symbol="ETHUSDT")),
        return_exceptions=True,
    )
    rejected = [r for r in results if isinstance(r, RiskRejected)]
    opened = [r for r in results if not isinstance(r, BaseException)]
    assert len(opened) == 1 and len(rejected) == 1
    assert [r.code for r in rejected[0].decision.reasons] == ["max_open_positions"]
    await s.engine.stop()


# --- Kapıyı atlayan kod yolu yok ------------------------------------------------------------------


async def test_entry_orders_require_valid_single_use_approval(db: Database) -> None:
    s = await setup(db)
    manager: OrderManager = s.engine.orders
    request = OrderRequest("atitenBYPASS01", "BTCUSDT", Side.BUY, OrderType.MARKET, D(1))

    with pytest.raises(ApprovalError, match="onayı olmadan"):
        await manager.submit(request)
    good = approve(s.gate, request, s.venue)
    forged = RiskApproval(**{**good.__dict__, "max_quantity": D(1000)})
    with pytest.raises(ApprovalError, match="imzası"):
        await manager.submit(
            OrderRequest("atitenBYPASS02", "BTCUSDT", Side.BUY, OrderType.MARKET, D(1000)),
            approval=forged,
        )
    with pytest.raises(ApprovalError, match="miktarı"):
        await manager.submit(
            OrderRequest("atitenBYPASS03", "BTCUSDT", Side.BUY, OrderType.MARKET, D(2)),
            approval=good,
        )
    with pytest.raises(ApprovalError, match="ait değil"):
        await manager.submit(
            OrderRequest("atitenBYPASS04", "BTCUSDT", Side.SELL, OrderType.MARKET, D(1)),
            approval=approve(s.gate, request, s.venue),
        )
    other = OrderManager(db, PaperVenue(Market.SPOT, fills=ExactFills()), verifier=s.gate)
    with pytest.raises(ApprovalError, match="ait değil"):
        await other.submit(request, approval=approve(s.gate, request, s.venue))
    expired = approve(s.gate, request, s.venue)
    s.clock.now += 61_000
    with pytest.raises(ApprovalError, match="süresi"):
        await manager.submit(request, approval=expired)
    fresh = approve(s.gate, request, s.venue)
    record = await manager.submit(request, approval=fresh)
    assert record.status is OrderStatus.FILLED
    with pytest.raises(ApprovalError, match="daha önce"):
        await manager.submit(
            OrderRequest("atitenBYPASS05", "BTCUSDT", Side.BUY, OrderType.MARKET, D(1)),
            approval=fresh,
        )
    assert s.gate.stats["verify_failed"] == 7
    assert list(s.venue._orders) == ["atitenBYPASS01"]  # yalnızca onaylı emir borsaya gitti
    await s.engine.stop()


async def test_non_entry_orders_cannot_increase_risk(db: Database) -> None:
    s = await setup(db)
    with pytest.raises(ApprovalError, match="reduceOnly"):
        await s.engine.orders.submit(
            OrderRequest(
                "atitexBYPASS06", "BTCUSDT", Side.BUY, OrderType.MARKET, D(5), purpose="exit"
            )
        )
    spot = await setup(db, Market.SPOT)
    with pytest.raises(ApprovalError, match="satış"):
        await spot.engine.orders.submit(
            OrderRequest(
                "atitexBYPASS07",
                "BTCUSDT",
                Side.BUY,
                OrderType.MARKET,
                D(5),
                purpose="take_profit",
            )
        )
    oco = OcoRequest("atitlBYPASS08", "BTCUSDT", Side.BUY, D(1), D(110), D(90), "a1", "a2")
    with pytest.raises(ApprovalError, match="OCO"):
        await s.engine.orders.submit_oco(oco)
    assert s.venue._orders == {} and spot.venue._orders == {}
    await s.engine.stop()
    await spot.engine.stop()


def test_no_code_path_sends_orders_around_the_order_manager() -> None:
    """Statik denetim: borsaya emir gönderen çağrılar yalnızca emir yöneticisindedir; emir
    yöneticisi ve işlem motoru risk kapısı olmadan kurulamaz."""
    import inspect

    root = Path(__file__).resolve().parents[1] / "src" / "ati_engine"
    callers = set()
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"\.(place|place_oco)\(", text):
            callers.add(path.relative_to(root).as_posix())
    assert callers == {"execution/orders.py"}
    manager_params = inspect.signature(OrderManager.__init__).parameters
    assert manager_params["verifier"].default is inspect.Parameter.empty
    engine_params = inspect.signature(TradingEngine.__init__).parameters
    assert engine_params["risk_gate"].default is inspect.Parameter.empty


# --- Hesap izleyici ---------------------------------------------------------------------------------


async def test_day_start_equity_survives_restart_and_resets_next_day(db: Database) -> None:
    s = await setup(db)
    first = await s.monitor.refresh()
    assert first.day == "2026-11-07" and first.day_start_equity == D(10_000)
    s.venue.wallet["USDT"] = D(9_900)
    restarted = AccountMonitor(db, mode=s.venue.mode, engines=lambda: [s.engine], clock=s.clock)
    snap = await restarted.refresh()
    assert snap.day_start_equity == D(10_000) and snap.daily_loss_pct == D(1)
    s.clock.now += DAY_MS
    tomorrow = await restarted.refresh()
    assert tomorrow.day == "2026-11-08" and tomorrow.day_start_equity == D(9_900)
    await s.engine.stop()


async def test_unrealized_pnl_counts_toward_equity(db: Database) -> None:
    s = await setup(db)
    await s.engine.open(intent(quantity=D(10), stop_loss=D(99)))
    s.venue.prices["BTCUSDT"] = D(95)  # stop henüz tetiklenmedi (on_price çağrılmadı)
    snap = await s.monitor.refresh()
    assert snap.equity == D(10_000) - D(50)
    (position,) = snap.positions
    assert position.notional == D(950) and position.leverage == 2
    await s.engine.stop()


# --- Risk bekçisi ------------------------------------------------------------------------------------


@dataclass
class Target:
    market: Market
    engine: TradingEngine
    reconciler: Reconciler


def make_guard(
    s: Setup,
    coordinator: SafetyCoordinator,
    db: Database,
    bus: EventBus | None = None,
    *,
    limits: RiskLimits | None = None,
    close_all: Callable[[str], Any] | None = None,
) -> tuple[RiskGuard, Target]:
    target = Target(s.engine.market, s.engine, Reconciler(s.engine))
    guard = RiskGuard(
        limits=limits or RiskLimits(),
        monitor=s.monitor,
        safety=coordinator,
        db=db,
        targets=lambda: [target],
        bus=bus,
        close_all=close_all,
        clock=s.clock,
    )
    guard.start()
    guard.attach(target.market)
    return guard, target


async def test_guard_halts_day_on_daily_loss_and_stays_latched(
    db: Database, coordinator: SafetyCoordinator, bus: EventBus
) -> None:
    alerts: list[Alert] = []

    async def on_alert(event: Alert) -> None:
        alerts.append(event)

    subscription = bus.subscribe(Alert, on_alert, name="test-alerts")
    s = await setup(db)
    closed: list[str] = []

    async def close_all(reason: str) -> int:
        closed.append(reason)
        return 0

    guard, _ = make_guard(
        s,
        coordinator,
        db,
        bus,
        limits=RiskLimits(close_positions_on_daily_loss=True),
        close_all=close_all,
    )
    await coordinator.boot_complete()
    await guard.check()
    assert coordinator.state.state is EngineState.RUNNING
    s.venue.wallet["USDT"] = D(9_790)  # %2,1 kayıp
    report = await guard.check()
    assert not report.halted  # tek okuma yetmez (anlık hatalı okuma kilitlemesin)
    report = await guard.check()
    assert report.halted and "day_halted" in report.actions
    assert coordinator.state.state is EngineState.SAFE_MODE
    assert closed == ["günlük zarar sınırı"]
    s.venue.wallet["USDT"] = D(10_500)  # toparlansa bile gün kilitli
    await guard.check()
    assert coordinator.state.state is EngineState.SAFE_MODE
    assert "daily_halt" in await codes(s, intent())
    rule = await db.fetchone("SELECT rule, severity FROM risk_events WHERE rule LIKE 'guard.%'")
    assert rule == ("guard.daily_loss", "critical")
    await subscription.drain(1.0)
    assert [a.title for a in alerts] == ["Günlük zarar sınırı"]
    s.clock.now += DAY_MS  # yeni UTC günü
    await guard.check()
    assert coordinator.state.state is EngineState.RUNNING
    await s.engine.stop()


async def test_guard_stream_and_reconcile_conditions(
    db: Database, coordinator: SafetyCoordinator
) -> None:
    s = await setup(db)
    guard, target = make_guard(s, coordinator, db, limits=RiskLimits(stream_grace_s=10))
    await coordinator.boot_complete()
    s.venue.stream_connected = False  # type: ignore[attr-defined]
    await guard.check()
    assert coordinator.state.state is EngineState.RUNNING  # tolerans süresi içinde
    s.clock.now += 11_000
    await guard.check()
    assert coordinator.state.state is EngineState.SAFE_MODE
    detail = {c.name: c for c in coordinator.conditions()}[stream_condition(Market.USDM_FUTURES)]
    assert not detail.ready and "kopuk" in detail.detail
    s.venue.stream_connected = True  # type: ignore[attr-defined]
    await guard.check()
    assert coordinator.state.state is EngineState.RUNNING

    s.venue.futures_positions["XUSDT"] = (D(1), D(1))  # bilinmeyen pozisyon: yalnızca uyarı
    await target.reconciler.run("test")
    await guard.check()
    assert coordinator.state.state is EngineState.RUNNING
    await s.engine.open(intent())
    s.venue.futures_positions["BTCUSDT"] = (D("0.5"), D(100))  # yerel 1 ≠ borsa 0,5
    await target.reconciler.run("test")
    await guard.check()
    assert coordinator.state.state is EngineState.SAFE_MODE
    names = {c.name for c in coordinator.conditions() if not c.ready}
    assert names == {"exchange.usdm_futures.reconciled"}
    await guard.detach(Market.USDM_FUTURES)
    assert coordinator.state.state is EngineState.RUNNING
    assert {c.name for c in coordinator.conditions()} == {DAILY_LOSS_CONDITION}
    await s.engine.stop()


async def test_guard_rebuilds_missing_stop(db: Database, coordinator: SafetyCoordinator) -> None:
    s = await setup(db)
    guard, _ = make_guard(s, coordinator, db)
    await s.engine.open(intent())
    stop = next(r for r in s.engine.orders.open_records() if r.purpose == "stop_loss")
    await s.engine.orders.cancel(stop.client_id)
    assert not s.engine.has_stop("BTCUSDT")
    report = await guard.check()
    assert "reconcile:usdm_futures" in report.actions
    assert s.engine.has_stop("BTCUSDT")
    event = await db.fetchone(
        "SELECT severity FROM risk_events WHERE rule = 'guard.unprotected_position'"
    )
    assert event == ("critical",)
    await s.engine.stop()


class LiquidationVenue(PaperVenue):
    liquidation: Decimal = D(0)

    async def positions(self) -> list[VenuePosition]:
        return [
            VenuePosition(s, q, e, leverage=2, liquidation_price=self.liquidation)
            for s, (q, e) in self.futures_positions.items()
        ]


async def test_guard_alerts_and_closes_near_liquidation(
    db: Database, coordinator: SafetyCoordinator
) -> None:
    venue = LiquidationVenue(Market.USDM_FUTURES, fills=ExactFills(), initial_quote=D(10_000))
    s = await setup(db, venue=venue)
    guard, _ = make_guard(s, coordinator, db)
    await s.engine.open(intent())
    venue.liquidation = D(90)  # %10 uzakta: uyarı
    report = await guard.check()
    assert report.actions == [] and "BTCUSDT" in s.engine.positions.positions
    venue.liquidation = D(97)  # %3 (< 15/3): acil kapatma
    report = await guard.check()
    assert report.actions == ["emergency_close:BTCUSDT"]
    assert "BTCUSDT" not in s.engine.positions.positions
    rules = [r[0] for r in await db.fetchall("SELECT rule FROM risk_events ORDER BY id")]
    assert rules == ["guard.liquidation_near", "guard.emergency_close"]
    await s.engine.stop()


async def test_transient_low_or_zero_reading_does_not_latch_the_day(
    db: Database, coordinator: SafetyCoordinator, bus: EventBus
) -> None:
    """Cüzdanlar arası aktarım ya da boş yanıt özsermayeyi bir anlığına düşük gösterir: tek okuma
    ya da 0 okuma günü kilitlemez. Hatalı kilit, zarar sınırın altındaysa kaldırılabilir."""
    s = await setup(db)
    guard, _ = make_guard(s, coordinator, db, bus)
    await coordinator.boot_complete()
    await guard.check()
    s.venue.wallet["USDT"] = D(0)  # boş yanıt
    report = await guard.check()
    assert not report.halted and any("0 okundu" in e for e in report.errors)
    report = await guard.check()
    assert not report.halted  # 0 okumalar art arda gelse de kilitlemez
    s.venue.wallet["USDT"] = D(9_500)  # tek düşük okuma
    assert not (await guard.check()).halted
    s.venue.wallet["USDT"] = D(10_000)  # toparlandı: sayaç sıfırlanır
    assert not (await guard.check()).halted
    s.venue.wallet["USDT"] = D(9_500)
    assert not (await guard.check()).halted
    assert coordinator.state.state is EngineState.RUNNING

    # Eski bir hatalı kilit: zarar şu an %0 ise kaldırılabilir; gün başı güncel değere çekilir.
    s.venue.wallet["USDT"] = D(10_000)
    await s.monitor.halt_day("eski hatalı okuma")
    assert (await s.monitor.refresh()).halted_at is not None
    assert await s.monitor.release_day()
    snapshot = await s.monitor.refresh()
    assert snapshot.halted_at is None and snapshot.day_start_equity == D(10_000)
    await s.engine.stop()
