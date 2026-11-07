from __future__ import annotations

from decimal import Decimal

import msgspec
import pytest

from ati_engine.core.clock import ManualClock
from ati_engine.core.models import Market, OrderStatus, Side, SymbolInfo, format_decimal


@pytest.fixture
def btc() -> SymbolInfo:
    return SymbolInfo(
        market=Market.SPOT,
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        status="TRADING",
        tick_size=Decimal("0.01"),
        step_size=Decimal("0.00001"),
        min_qty=Decimal("0.00001"),
        min_notional=Decimal("5"),
    )


def test_price_rounding_never_worsens_price(btc: SymbolInfo) -> None:
    assert btc.quantize_price(Decimal("76098.019"), side=Side.BUY) == Decimal("76098.01")
    assert btc.quantize_price(Decimal("76098.011"), side=Side.SELL) == Decimal("76098.02")
    assert btc.quantize_price(Decimal("76098.01"), side=Side.SELL) == Decimal("76098.01")


def test_qty_rounding_always_down(btc: SymbolInfo) -> None:
    assert btc.quantize_qty(Decimal("0.123456789")) == Decimal("0.12345")
    assert btc.quantize_qty(Decimal("0.000009")) == Decimal("0.00000")


def test_non_decimal_power_tick() -> None:
    info = SymbolInfo(
        market=Market.USDM_FUTURES,
        symbol="XUSDT",
        base_asset="X",
        quote_asset="USDT",
        status="TRADING",
        tick_size=Decimal("0.05"),
        step_size=Decimal("10"),
        min_qty=Decimal("10"),
        min_notional=Decimal("5"),
    )
    assert info.quantize_price(Decimal("1.234"), side=Side.BUY) == Decimal("1.20")
    assert info.quantize_price(Decimal("1.234"), side=Side.SELL) == Decimal("1.25")
    assert info.quantize_qty(Decimal("129")) == Decimal("120")


def test_validate_order(btc: SymbolInfo) -> None:
    assert btc.validate_order(qty=Decimal("0.001"), price=Decimal("76000")) == []
    errors = btc.validate_order(qty=Decimal("0.000011"), price=Decimal("76000.005"))
    assert any("step_size" in e for e in errors)
    assert any("tick_size" in e for e in errors)
    errors = btc.validate_order(qty=Decimal("0.00001"), price=Decimal("100"))
    assert any("Emir tutarı" in e for e in errors)
    assert btc.validate_order(qty=Decimal("0"), price=Decimal("1")) == ["Miktar pozitif olmalı"]


def test_format_decimal_has_no_exponent() -> None:
    assert format_decimal(Decimal("1E+1")) == "10"
    assert format_decimal(Decimal("0.00100000")) == "0.001"
    assert format_decimal(Decimal("-0")) == "0"


def test_decimal_survives_msgspec_roundtrip(btc: SymbolInfo) -> None:
    raw = msgspec.json.encode(btc)
    assert b'"0.00001"' in raw
    decoded = msgspec.json.decode(raw, type=SymbolInfo)
    assert decoded == btc


def test_order_status_terminal() -> None:
    assert OrderStatus.FILLED.is_terminal
    assert not OrderStatus.PARTIALLY_FILLED.is_terminal


def test_manual_clock_cannot_go_back() -> None:
    clock = ManualClock(1000)
    clock.advance(500)
    assert clock.now_ms() == 1500
    with pytest.raises(ValueError, match="geriye"):
        clock.set(1000)
