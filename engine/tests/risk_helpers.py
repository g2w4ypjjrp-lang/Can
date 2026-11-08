"""Testler için risk kapısı kurulumu (gerçek ``RiskGate``; atlatma yok)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ati_engine.config import RiskLimits
from ati_engine.core.models import EngineState, TradingMode
from ati_engine.execution.approval import RiskApproval
from ati_engine.execution.engine import TradingEngine
from ati_engine.execution.venue import OrderRequest
from ati_engine.risk.account import AccountMonitor
from ati_engine.risk.gate import RiskGate
from ati_engine.storage.database import Database


def make_gate(
    db: Database,
    mode: TradingMode,
    engines: list[TradingEngine] | None = None,
    *,
    limits: RiskLimits | None = None,
    state: Callable[[], EngineState] | None = None,
    trading_mode: Callable[[], TradingMode] | None = None,
    **kw: Any,
) -> RiskGate:
    holder = engines if engines is not None else []
    return RiskGate(
        limits=limits or RiskLimits(),
        db=db,
        monitor=AccountMonitor(db, mode=mode, engines=lambda: holder),
        engines=lambda: holder,
        trading_mode=trading_mode or (lambda: mode),
        engine_state=state or (lambda: EngineState.RUNNING),
        **kw,
    )


def approve(gate: RiskGate, request: OrderRequest, venue: Any) -> RiskApproval:
    """Emir yöneticisi birim testleri için: kapının kendi onay üretimi (imzalı, tek kullanımlık)."""
    assert request.quantity is not None
    return gate._issue(
        decision_id="test",
        mode=venue.mode,
        market=venue.market,
        symbol=request.symbol,
        side=request.side,
        max_quantity=request.quantity,
    )
