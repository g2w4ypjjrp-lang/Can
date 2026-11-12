"""Açık pozisyonların anlık kâr/zararı (Long/Short, fiyat yoksa boş)."""

from decimal import Decimal as D

from ati_engine.core.models import Market
from ati_engine.execution.pnl import with_pnl


def test_long_short_and_missing_price() -> None:
    prices = {"BTCUSDT": 110.0, "ETHUSDT": 90.0}
    rows = with_pnl(
        [
            {
                "market": "usdm_futures",
                "symbol": "BTCUSDT",
                "quantity": D("2"),
                "entry_price": D(100),
            },
            {
                "market": "usdm_futures",
                "symbol": "ETHUSDT",
                "quantity": D("-3"),
                "entry_price": D(100),
            },
            {"market": "spot", "symbol": "XYZUSDT", "quantity": D("1"), "entry_price": D(5)},
        ],
        lambda market, symbol: prices.get(symbol) if market is Market.USDM_FUTURES else None,
    )
    long, short, unknown = rows
    assert long["unrealized_pnl"] == D(20) and long["pnl_pct"] == 10.0
    assert long["mark_price"] == D("110.0") and long["notional"] == D(220)
    assert short["unrealized_pnl"] == D(30) and short["pnl_pct"] == 10.0  # Short: fiyat düştü
    assert unknown["unrealized_pnl"] is None and unknown["pnl_pct"] is None
