"""İşlem bildirimlerinin metni (telefon sayfası, telefon bildirimi ve Telegram için ortak).

Kazanç vaadi içermez; yalnızca gerçekleşen işlemi ve ayrıntılarını yazar.
"""

from __future__ import annotations

from ati_engine.core.events import TradeNotice

MODES = {"live": "GERÇEK", "testnet": "Demo", "paper": "Sanal"}


def _market(n: TradeNotice) -> str:
    return "Futures" if n.market == "usdm_futures" else "Spot"


def _side(n: TradeNotice) -> str:
    return "Long" if n.side == "long" else "Short"


def _duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} sn"
    if seconds < 3600:
        return f"{seconds // 60} dk"
    if seconds < 86400:
        return f"{seconds // 3600} sa {(seconds % 3600) // 60} dk"
    return f"{seconds // 86400} gün {(seconds % 86400) // 3600} sa"


def _money(value: str | None) -> str:
    if value is None:
        return "—"
    try:
        n = float(value)
    except ValueError:
        return value
    return f"{n:+.2f}"


def trade_title(n: TradeNotice) -> str:
    if n.action == "opened":
        return f"📈 {n.symbol} {_side(n)} açıldı"
    pnl = ""
    if n.net_pnl is not None:
        pct = f" (%{n.pnl_pct:+.2f})" if n.pnl_pct is not None else ""
        pnl = f" · {_money(n.net_pnl)} USDT{pct}"
    try:
        loss = n.net_pnl is not None and float(n.net_pnl) < 0
    except ValueError:
        loss = False
    icon = "🔻" if loss else "✅"
    return f"{icon} {n.symbol} {_side(n)} kapandı{pnl}"


def trade_details(n: TradeNotice) -> list[str]:
    """Ayrıntı satırları (her biri kısa)."""
    lines = [f"{MODES.get(n.mode, n.mode)} · {_market(n)} · {n.quantity} @ {n.price}"]
    if n.action == "opened":
        levels = []
        if n.stop_loss:
            levels.append(f"stop {n.stop_loss}")
        if n.take_profit:
            levels.append(f"hedef {n.take_profit}")
        if n.leverage and n.leverage > 1:
            levels.append(f"{n.leverage}x")
        if levels:
            lines.append(" · ".join(levels))
        if n.score is not None:
            lines.append(f"puan {n.score:g}" + (f" · {n.reason}" if n.reason else ""))
        elif n.reason:
            lines.append(n.reason)
    else:
        info = []
        if n.entry_price:
            info.append(f"giriş {n.entry_price} → çıkış {n.price}")
        if n.close_reason:
            info.append(n.close_reason)
        if n.duration_s is not None:
            info.append(_duration(n.duration_s))
        if info:
            lines.append(" · ".join(info))
    return lines


def trade_body(n: TradeNotice) -> str:
    return "\n".join(trade_details(n))
