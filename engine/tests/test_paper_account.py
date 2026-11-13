"""Sanal hesap (Sanal mod): bot borsaya emir göndermeden, canlı fiyatlarla işlem açar; zarar
durdur fiyat akışıyla tetiklenir. Uygulama varsayılan olarak Sanal modda açıldığından bot önceden
hiç işlem açmıyordu."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ati_engine.config import AutoTradeSettings, EngineSettings
from ati_engine.core.models import EngineState, Market, SymbolInfo, TradingMode
from ati_engine.execution.auto import AutoTrader
from ati_engine.execution.paper_live import LivePaperVenue
from ati_engine.execution.service import ExecutionService, ExecutionUnavailable
from ati_engine.scoring.live import OpportunityScored
from ati_engine.security.exchange_keys import ExchangeKeyStore
from ati_engine.security.vault import AesGcmCipher, SecretVault
from ati_engine.storage.audit import AuditLog
from ati_engine.storage.database import Database

D = Decimal
BTC = SymbolInfo(
    market=Market.USDM_FUTURES,
    symbol="BTCUSDT",
    base_asset="BTC",
    quote_asset="USDT",
    status="TRADING",
    tick_size=D("0.1"),
    step_size=D("0.001"),
    min_qty=D("0.001"),
    min_notional=D("5"),
)


@pytest.fixture
async def paper(
    tmp_path: Path, db: Database
) -> AsyncIterator[tuple[ExecutionService, dict[str, float]]]:
    prices = {"BTCUSDT": 75_000.0}
    symbols: dict[str, SymbolInfo] = {}  # açılışta boş: exchangeInfo sonra gelir
    settings = EngineSettings(data_dir=tmp_path / "data", log_to_console=False)
    svc = ExecutionService(
        settings=settings,
        db=db,
        audit=AuditLog(db),
        keys=ExchangeKeyStore(SecretVault(db, AesGcmCipher(AesGcmCipher.generate_key()))),
        trading_mode=lambda: TradingMode.PAPER,
        engine_state=lambda: EngineState.RUNNING,
        environment="paper",
        paper_symbols=lambda market: symbols if market is Market.USDM_FUTURES else {},
        paper_price=lambda market, symbol: prices.get(symbol),
        paper_balance=D(10_000),
    )
    await svc.connect_configured()  # anahtar gerekmez
    symbols["BTCUSDT"] = BTC
    yield svc, prices
    await svc.close()


def signal(**kw: Any) -> OpportunityScored:
    now = int(time.time() * 1000)
    values: dict[str, Any] = {
        "market": Market.USDM_FUTURES,
        "symbol": "BTCUSDT",
        "interval": "1h",
        "bar_open_time_ms": now - 3_600_000,
        "direction": "long",
        "score": 78.0,
        "price": 75_000.0,
        "stop_price": 73_500.0,
        "target_price": 78_000.0,
        "reward_risk": 2.0,
        "cost_pct": 0.1,
        "reasons": ["trend"],
    }
    values.update(kw)
    return OpportunityScored(**values)


async def test_bot_trades_in_paper_mode_and_stop_triggers_on_live_price(
    paper: tuple[ExecutionService, dict[str, float]],
) -> None:
    svc, _prices = paper
    status = await svc.status()
    assert status["environment"] == "paper"
    assert status["markets"]["usdm_futures"]["connected"] is True
    assert status["markets"]["usdm_futures"]["key_stored"] is True
    with pytest.raises(ExecutionUnavailable):
        await svc.store_key(Market.USDM_FUTURES, "a" * 20, "b" * 20, actor="test")

    auto = AutoTrader(
        settings=AutoTradeSettings(enabled=True, trailing_runner=False),
        limits=svc.settings.risk,
        service=svc,
        trading_mode=lambda: TradingMode.PAPER,
    )
    await auto.on_opportunity(signal())
    assert auto.stats["opened"] == 1, (auto.status(), auto.recent)
    assert auto.recent[0]["decision_id"].startswith("oto-sanal-")
    execution = svc.markets[Market.USDM_FUTURES]
    venue = execution.engine.venue
    assert isinstance(venue, LivePaperVenue)
    qty = venue.futures_positions["BTCUSDT"][0]
    # Toplam sanal bakiye 10.000 (Futures ve Spot'a 5.000'er). Risk: 10.000 x %0,25 = 25 USDT;
    # stop %2 aşağıda (1.500 USDT/BTC + maliyet payı).
    assert D("0.015") <= qty <= D("0.017")
    assert "BTCUSDT" in venue.watched()

    # Canlı fiyat stopun altına iner: zarar durdur tetiklenir, pozisyon kapanır.
    await svc.feed_prices({"usdm_futures:BTCUSDT": 73_400.0, "spot:BTCUSDT": 1.0})
    await venue.drained()
    assert venue.futures_positions.get("BTCUSDT", (D(0), D(0)))[0] == 0
    assert venue.wallet["USDT"] < D(5_000)  # zarar ve komisyon sanal bakiyeden düştü
    assert "BTCUSDT" not in execution.engine.positions.positions
