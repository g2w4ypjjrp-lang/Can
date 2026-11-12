"""Uzaktan kontrolün motor bileşenlerine bağlanması: izin listesindeki komutların yürütücüleri,
telefona giden özet ve bildirim kaynakları.

Özet yalnızca durum bilgisidir. API anahtarı, emir kimliği, hesap ayrıntısı içermez. Her bölüm
ayrı denenir; bir bileşen kapalıysa o bölüm boş gelir.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ati_engine.core.events import (
    Alert,
    EngineStateChanged,
    KillSwitchEngaged,
    KillSwitchReleased,
    TradeNotice,
)
from ati_engine.paper.competition import PaperTradeEvent
from ati_engine.remote.protocol import Device
from ati_engine.remote.service import Executor
from ati_engine.safety.kill_switch import RELEASE_CONFIRMATION
from ati_engine.whales.events import WhaleAlert

if TYPE_CHECKING:
    from ati_engine.remote.service import RemoteService
    from ati_engine.runtime import EngineRuntime

logger = logging.getLogger(__name__)


def _actor(device: Device) -> str:
    return f"remote:{device.id}"


def build_executors(runtime: EngineRuntime) -> dict[str, Executor]:
    async def engage(args: dict[str, Any], device: Device) -> str:
        reason = str(args.get("reason") or "telefondan acil durdurma")[:200]
        await runtime.safety.engage_kill_switch(
            reason=f"{reason} ({device.name})", actor=_actor(device)
        )
        return "Acil durdurma devrede"

    async def release(args: dict[str, Any], device: Device) -> str:
        await runtime.safety.release_kill_switch(
            actor=_actor(device), confirmation=RELEASE_CONFIRMATION
        )
        return "Acil durdurma kaldırıldı"

    async def set_auto(enabled: bool, device: Device) -> str:
        if runtime.autotrader is None:
            raise RuntimeError("Otomatik işlem etkin değil")
        runtime.autotrader.enabled = enabled
        from ati_engine.execution.auto import ENABLED_KEY
        from ati_engine.storage.settings_store import SettingsStore

        await SettingsStore(runtime.db).set(ENABLED_KEY, enabled)
        await runtime.audit.record(
            actor=_actor(device), action="autotrade.toggle", details={"enabled": enabled}
        )
        return "Otomatik işlem başlatıldı" if enabled else "Otomatik işlem durduruldu"

    async def pause(args: dict[str, Any], device: Device) -> str:
        return await set_auto(False, device)

    async def resume(args: dict[str, Any], device: Device) -> str:
        return await set_auto(True, device)

    async def close_position(args: dict[str, Any], device: Device) -> str:
        from ati_engine.core.models import Market

        execution = runtime.active_execution()
        if execution is None:
            raise RuntimeError("Emir yürütme etkin değil")
        market = Market(str(args.get("market")))
        symbol = str(args.get("symbol", "")).upper()
        record = await execution.close_position(
            market, symbol, actor=_actor(device), reason="telefondan kapatma"
        )
        return f"{symbol} kapatıldı" if record is not None else f"{symbol} için açık pozisyon yok"

    async def close_all(args: dict[str, Any], device: Device) -> str:
        execution = runtime.active_execution()
        if execution is None:
            raise RuntimeError("Emir yürütme etkin değil")
        closed = await execution.close_all(reason="telefondan tümünü kapat", actor=_actor(device))
        return f"{closed} pozisyon kapatıldı"

    async def snapshot(args: dict[str, Any], device: Device) -> str:
        return "Güncel durum gönderiliyor"

    return {
        "engage_kill_switch": engage,
        "release_kill_switch": release,
        "pause_autotrade": pause,
        "resume_autotrade": resume,
        "close_position": close_position,
        "close_all": close_all,
        "request_snapshot": snapshot,
    }


async def build_snapshot(runtime: EngineRuntime) -> dict[str, Any]:
    state = runtime.safety.state
    ks = runtime.safety.kill_switch.status
    data: dict[str, Any] = {
        "engine": {
            "state": state.state.value,
            "reason": state.reason,
            "trading_mode": runtime.trading_mode.mode.value,
            "kill_switch": ks.engaged,
            "kill_reason": ks.reason,
            "uptime_s": int(runtime.uptime_s),
            "version": runtime.version,
        }
    }
    if runtime.license is not None:
        lic = runtime.license.status()
        # Telefona yalnızca özet: anahtar, cihaz kimliği veya sunucu ayrıntısı gönderilmez.
        data["license"] = {
            "state": lic["state"],
            "valid": lic["valid"],
            "enforced": lic["enforced"],
            "plan_name": lic["plan_name"],
            "expires_at": lic["license_expires_at"],
            "message": lic["message"],
        }
    try:
        # İşlem moduna göre Demo ya da gerçek hesap (gerçek para modunda canlı servis).
        execution = runtime.active_execution()
        if execution is not None:
            account = execution.monitor.last
            data["risk"] = (
                None
                if account is None
                else {
                    "daily_loss_pct": round(float(account.daily_loss_pct), 3),
                    "halted": account.halted_at is not None,
                    "halt_reason": account.halt_reason,
                    "equity": str(account.equity),
                    # Binance cüzdanı (piyasa başına): telefonda "Binance bakiyesi".
                    "wallets": [w.as_dict() for w in account.wallets],
                }
            )
            from ati_engine.execution.pnl import with_pnl

            data["positions"] = [
                {
                    "market": p["market"],
                    "symbol": p["symbol"],
                    "quantity": str(p["quantity"]),
                    "entry_price": str(p["entry_price"]),
                    "realized_pnl": str(p["realized_pnl"]),
                    "protected": p["protected"],
                    "mark_price": None if p["mark_price"] is None else str(p["mark_price"]),
                    "unrealized_pnl": (
                        None if p["unrealized_pnl"] is None else str(p["unrealized_pnl"])
                    ),
                    "pnl_pct": p["pnl_pct"],
                }
                for p in with_pnl(execution.positions(), runtime.mark_price)
            ]
    except Exception as exc:
        logger.debug("Özet: yürütme bölümü atlandı", extra={"error": repr(exc)})
    try:
        from ati_engine.core.models import TradingMode
        from ati_engine.execution.history import closed_trades, summarize

        mode = "live" if runtime.trading_mode.mode is TradingMode.LIVE else "testnet"
        trades = await closed_trades(runtime.db, mode, limit=100)
        keys = ("symbol", "market", "side", "net_pnl", "pnl_pct", "closed_at", "source")
        data["history"] = {
            "summary": summarize(trades),
            "trades": [{k: t[k] for k in keys} for t in trades[:15]],
        }
    except Exception as exc:
        logger.debug("Özet: geçmiş bölümü atlandı", extra={"error": repr(exc)})
    if runtime.autotrader is not None:
        trader = runtime.autotrader
        data["autotrade"] = {
            "enabled": trader.enabled,
            "opened": trader.stats["opened"],
            "rejected": trader.stats["rejected"],
            "signals": trader.stats["signals"],
            "interval": trader.interval,
            "min_score": trader.cfg.min_score,
            "next_decision_ms": trader.next_decision_ms(),
            "candidates": [
                {k: c[k] for k in ("market", "symbol", "direction", "score")}
                for c in trader.candidates(limit=5)
            ],
            "recent": [
                {k: d.get(k) for k in ("ts_ms", "market", "symbol", "direction", "score", "result")}
                for d in list(trader.recent)[:5]
            ],
        }
    try:
        if runtime.opportunities is not None:
            data["opportunities"] = [
                {
                    "market": str(o.market),
                    "symbol": o.symbol,
                    "direction": o.direction,
                    "score": round(o.score),
                    "reward_risk": None if o.reward_risk is None else round(o.reward_risk, 2),
                }
                for o in runtime.opportunities.top(None, min_score=50, direction=None, limit=5)
            ]
    except Exception as exc:
        logger.debug("Özet: fırsat bölümü atlandı", extra={"error": repr(exc)})
    if runtime.whales is not None:
        data["whales"] = [
            {"ts_ms": a.ts_ms, "symbol": a.symbol, "message": a.message[:160]}
            for a in list(runtime.whales.alerts)[-5:][::-1]
        ]
    if runtime.paper is not None:
        data["paper"] = {
            "accounts": len(runtime.paper.accounts),
            "open_positions": sum(len(a.positions) for a in runtime.paper.accounts.values()),
            "trades": sum(len(a.trades) for a in runtime.paper.accounts.values()),
            "net_pnl": round(
                sum(t.net_pnl for a in runtime.paper.accounts.values() for t in a.trades), 2
            ),
        }
    return data


def subscribe_notifications(runtime: EngineRuntime, service: RemoteService) -> None:
    """Önemli olayları telefona özet bildirim olarak iletir (hassas veri içermez)."""

    async def on_alert(event: Alert) -> None:
        await service.notify("alert", event.title, event.message)

    async def on_whale(event: WhaleAlert) -> None:
        await service.notify("whale", f"Balina: {event.symbol}", event.message)

    async def on_paper(event: PaperTradeEvent) -> None:
        if event.action == "closed" and event.net_pnl is not None:
            body = (
                f"{event.strategy}: {event.symbol} kapandı, net {event.net_pnl:+.2f} USDT (sanal)"
            )
        else:
            body = f"{event.strategy}: {event.symbol} {event.direction} açıldı (sanal)"
        await service.notify("paper", "Sanal işlem", body)

    async def on_trade(event: TradeNotice) -> None:
        money = "GERÇEK" if event.mode == "live" else "Demo"
        side = "Long" if event.side == "long" else "Short"
        if event.action == "closed":
            pnl = f", net {float(event.net_pnl):+.2f} USDT" if event.net_pnl else ""
            body = f"{event.symbol} {side} kapandı{pnl} ({money})"
        else:
            body = f"{event.symbol} {side} açıldı, fiyat {event.price} ({money})"
        await service.notify("trade", "İşlem", body)

    states = {
        "running": "Çalışıyor",
        "safe_mode": "Güvenli mod",
        "starting": "Başlıyor",
        "halted": "Durduruldu",
        "stopped": "Kapalı",
    }

    async def on_state(event: EngineStateChanged) -> None:
        label = states.get(event.current.value, event.current.value)
        await service.notify("state", f"Motor: {label}", event.reason)

    async def on_kill(event: KillSwitchEngaged) -> None:
        await service.notify("kill_switch", "Acil durdurma devrede", event.reason)

    async def on_release(event: KillSwitchReleased) -> None:
        await service.notify("kill_switch", "Acil durdurma kaldırıldı", event.actor)

    bus = runtime.bus
    bus.subscribe(Alert, on_alert, name="remote-alerts")
    bus.subscribe(WhaleAlert, on_whale, name="remote-whales")
    bus.subscribe(PaperTradeEvent, on_paper, name="remote-paper")
    bus.subscribe(TradeNotice, on_trade, name="remote-trades")
    bus.subscribe(EngineStateChanged, on_state, name="remote-state")
    bus.subscribe(KillSwitchEngaged, on_kill, name="remote-kill")
    bus.subscribe(KillSwitchReleased, on_release, name="remote-release")
