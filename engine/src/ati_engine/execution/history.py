"""Kapanmış işlemlerin geçmişi ve özeti (gerçek hesap ya da Demo).

Kaynak: ``positions`` tablosundaki kapanmış satırlar (gerçekleşen kâr/zarar, komisyon, fonlama)
ve dolumlar (giriş tutarı, ortalama çıkış fiyatı). Net = gerçekleşen − komisyon − fonlama.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from ati_engine.storage.database import Database

ENTRY_PURPOSES = ("entry", "scale_in")


def _d(value: Any) -> Decimal:
    try:
        return Decimal(str(value)) if value not in (None, "") else Decimal(0)
    except Exception:
        return Decimal(0)


async def closed_trades(db: Database, mode: str, *, limit: int = 200) -> list[dict[str, Any]]:
    rows = await db.fetchall(
        "SELECT id, market, symbol, side, entry_price, realized_pnl, fees_paid, funding_paid, "
        "decision_id, opened_at, closed_at FROM positions WHERE mode = ? AND status = 'closed' "
        "AND closed_at IS NOT NULL ORDER BY closed_at DESC LIMIT ?",
        (mode, limit),
    )
    trades: list[dict[str, Any]] = []
    for r in rows:
        (pid, market, symbol, side, entry, realized, fees, funding, decision, opened, closed) = r
        fills = await db.fetchall(
            "SELECT o.purpose, f.price, f.quantity FROM fills f JOIN orders o ON o.id = f.order_id "
            "WHERE f.mode = ? AND f.market = ? AND f.symbol = ? AND f.ts BETWEEN ? AND ?",
            (mode, market, symbol, opened, closed),
        )
        entry_qty = entry_notional = exit_qty = exit_notional = Decimal(0)
        for purpose, price, qty in fills:
            p, q = _d(price), _d(qty)
            if purpose in ENTRY_PURPOSES:
                entry_qty += q
                entry_notional += p * q
            else:
                exit_qty += q
                exit_notional += p * q
        net = _d(realized) - _d(fees) - _d(funding)
        trades.append(
            {
                "id": pid,
                "market": market,
                "symbol": symbol,
                "side": "long" if side == "LONG" else "short",
                "entry_price": str(_d(entry)),
                "exit_price": str(exit_notional / exit_qty) if exit_qty > 0 else None,
                "quantity": str(entry_qty) if entry_qty > 0 else None,
                "notional": str(entry_notional) if entry_notional > 0 else None,
                "realized_pnl": str(_d(realized)),
                "fees": str(_d(fees)),
                "funding": str(_d(funding)),
                "net_pnl": str(net),
                "pnl_pct": round(float(net / entry_notional * 100), 3)
                if entry_notional > 0
                else None,
                "source": "bot" if str(decision or "").startswith("oto-") else "manual",
                "opened_at": opened,
                "closed_at": closed,
                "duration_s": max(0, (closed - opened) // 1000),
            }
        )
    return trades


def summarize(trades: list[dict[str, Any]], *, now_ms: int | None = None) -> dict[str, Any]:
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    today = datetime.fromtimestamp(now / 1000, tz=UTC).date()
    nets = [Decimal(t["net_pnl"]) for t in trades]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n < 0]
    today_net = sum(
        (
            Decimal(t["net_pnl"])
            for t in trades
            if datetime.fromtimestamp(t["closed_at"] / 1000, tz=UTC).date() == today
        ),
        Decimal(0),
    )
    return {
        "count": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else None,
        "net_total": str(sum(nets, Decimal(0))),
        "gross_profit": str(sum(wins, Decimal(0))),
        "gross_loss": str(sum(losses, Decimal(0))),
        "best": str(max(nets)) if nets else None,
        "worst": str(min(nets)) if nets else None,
        "today_net": str(today_net),
    }
