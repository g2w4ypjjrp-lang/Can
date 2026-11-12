"""Açık pozisyonların anlık kâr/zararı: güncel piyasa fiyatı (piyasa verisi akışı; Futures'ta
işaret fiyatı) ile giriş fiyatı arasındaki fark. Komisyon ve fonlama dahil değildir."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from ati_engine.core.models import Market

PriceOf = Callable[[Market, str], float | None]


def with_pnl(rows: list[dict[str, Any]], price_of: PriceOf) -> list[dict[str, Any]]:
    for row in rows:
        quantity = Decimal(str(row["quantity"]))
        entry = Decimal(str(row["entry_price"]))
        try:
            mark = price_of(Market(row["market"]), row["symbol"])
        except Exception:
            mark = None
        if mark and mark > 0 and entry > 0 and quantity != 0:
            price = Decimal(str(mark))
            row["mark_price"] = price
            row["unrealized_pnl"] = (price - entry) * quantity
            row["pnl_pct"] = round(
                float((price / entry - 1) * 100 * (1 if quantity > 0 else -1)), 3
            )
            row["notional"] = abs(quantity) * price
        else:
            row.update(mark_price=None, unrealized_pnl=None, pnl_pct=None, notional=None)
    return rows
