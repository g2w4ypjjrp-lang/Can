"""Risk bekçisi: işlem motorundan bağımsız, sürekli çalışan denetçi.

Risk kapısı işlem **açılmadan önce** karar verir; bekçi ise açık pozisyonları ve bağlantıları
**sürekli** izler. Kendi görevinde çalışır, hesap bilgisini doğrudan borsadan okur ve motorun
yeni işlem açıp açamayacağını güvenlik koordinatörünün hazırlık koşullarıyla belirler:

* ``risk.daily_loss`` — Günlük zarar (gün başı özsermayeye göre, gerçekleşmiş + gerçekleşmemiş)
  sınıra ulaşınca gün **kilitlenir**: motor SAFE_MODE'a iner ve UTC gün sonuna kadar yeni
  işlem açılmaz (özsermaye toparlansa ya da motor yeniden başlatılsa bile). Borsadaki stoplar
  yerinde kalır; ayarla açık pozisyonların kapatılması da istenebilir.
* ``exchange.<piyasa>.stream`` — Kullanıcı veri akışı ``stream_grace_s`` süreden uzun kopuksa
  yeni işlem açılmaz (dolum ve stop olayları görülemez).
* ``exchange.<piyasa>.reconciled`` — Son mutabakatta kritik fark varsa (pozisyon/bakiye
  uyuşmazlığı) yeni işlem açılmaz.

Ayrıca:

* Stopu olmayan açık pozisyon görülürse kritik olay yazılır ve mutabakat tetiklenir (koruma
  yeniden kurulur).
* Tahmini tasfiye uzaklığı sınırın altına inerse kritik uyarı; sınırın üçte birinin altına
  inerse pozisyon acil olarak kapatılır (riski azaltan tek otomatik eylem).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from ati_engine.config import RiskLimits
from ati_engine.core.bus import EventBus
from ati_engine.core.events import Alert
from ati_engine.core.models import Market, Severity
from ati_engine.execution.engine import TradingEngine
from ati_engine.execution.reconcile import Reconciler
from ati_engine.risk.account import AccountMonitor
from ati_engine.safety.coordinator import SafetyCoordinator
from ati_engine.storage.database import Database

logger = logging.getLogger(__name__)

DAILY_LOSS_CONDITION = "risk.daily_loss"


def stream_condition(market: Market) -> str:
    return f"exchange.{market.value}.stream"


def reconciled_condition(market: Market) -> str:
    return f"exchange.{market.value}.reconciled"


class GuardTarget(Protocol):
    market: Market
    engine: TradingEngine
    reconciler: Reconciler


@dataclass
class GuardReport:
    ts_ms: int
    daily_loss_pct: float | None = None
    halted: bool = False
    actions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ts_ms": self.ts_ms,
            "daily_loss_pct": self.daily_loss_pct,
            "halted": self.halted,
            "actions": self.actions,
            "errors": self.errors,
        }


class RiskGuard:
    def __init__(
        self,
        *,
        limits: RiskLimits,
        monitor: AccountMonitor,
        safety: SafetyCoordinator,
        db: Database,
        targets: Callable[[], Sequence[GuardTarget]],
        bus: EventBus | None = None,
        close_all: Callable[[str], Awaitable[int]] | None = None,
        clock: Callable[[], int] | None = None,
        prefix: str = "",
    ) -> None:
        # Gerçek hesap bekçisinin koşulları "live." önekiyle ayrılır (Demo ile çakışmaz).
        self.prefix = prefix
        self.limits = limits
        self.monitor = monitor
        self.safety = safety
        self.db = db
        self.targets = targets
        self.bus = bus
        self.close_all = close_all
        self._clock = clock or (lambda: int(time.time() * 1000))
        # Günlük kilit tek bir okumaya dayanmaz: cüzdanlar arası aktarım ya da Binance'in anlık
        # boş yanıtı özsermayeyi bir anlığına düşük gösterebilir. Sınır art arda iki okumada
        # aşılırsa gün kilitlenir; özsermaye 0 okunursa (gün başı > 0) okuma şüphelidir.
        self._loss_strikes = 0
        self._down_since: dict[Market, int] = {}
        self._alerted: set[str] = set()
        self._registered: set[str] = set()
        self.last: GuardReport | None = None
        self.checks = 0

    # --- Koşul kaydı ------------------------------------------------------------------------

    def start(self) -> None:
        self._register(self.prefix + DAILY_LOSS_CONDITION, "günlük zarar sınırı içinde")

    def _register(self, name: str, detail: str) -> None:
        if name not in self._registered:
            self.safety.register_condition(name, ready=True, detail=detail)
            self._registered.add(name)

    def attach(self, market: Market) -> None:
        """Bir piyasa bağlandı: akış ve mutabakat koşulları izlenmeye başlar."""
        self._register(self.prefix + stream_condition(market), "kullanıcı akışı bekleniyor")
        self._register(self.prefix + reconciled_condition(market), "mutabakat tamam")

    async def detach(self, market: Market) -> None:
        for name in (
            self.prefix + stream_condition(market),
            self.prefix + reconciled_condition(market),
        ):
            if name in self._registered:
                self._registered.discard(name)
                await self.safety.unregister_condition(name)
        self._down_since.pop(market, None)

    # --- Denetim ------------------------------------------------------------------------------

    async def check(self) -> GuardReport:
        now = self._clock()
        report = GuardReport(ts_ms=now)
        targets = list(self.targets())
        self.checks += 1
        if not targets:
            self.last = report
            return report
        try:
            snapshot = await self.monitor.refresh()
        except Exception as exc:
            report.errors.append(f"hesap okunamadı: {type(exc).__name__}: {exc}"[:200])
            snapshot = None
        if snapshot is not None:
            report.daily_loss_pct = round(float(snapshot.daily_loss_pct), 4)
            halted = snapshot.halted_at is not None
            over = snapshot.daily_loss_pct >= self.limits.max_daily_loss_pct
            suspicious = snapshot.equity <= 0 < snapshot.day_start_equity
            self._loss_strikes = self._loss_strikes + 1 if over and not suspicious else 0
            if suspicious:
                report.errors.append("özsermaye 0 okundu; okuma yok sayıldı")
            if not halted and over and self._loss_strikes >= 2:
                reason = (
                    f"Günlük zarar %{snapshot.daily_loss_pct:.2f} "
                    f"(sınır %{self.limits.max_daily_loss_pct}); gün sonuna kadar yeni işlem yok"
                )
                if await self.monitor.halt_day(reason):
                    report.actions.append("day_halted")
                    await self._event(
                        "guard.daily_loss",
                        "critical",
                        None,
                        "yeni işlemler durduruldu",
                        {"daily_loss_pct": report.daily_loss_pct, "equity": str(snapshot.equity)},
                    )
                    await self._alert("Günlük zarar sınırı", reason)
                    if self.limits.close_positions_on_daily_loss and self.close_all is not None:
                        closed = await self.close_all("günlük zarar sınırı")
                        report.actions.append(f"closed_all:{closed}")
                halted = True
            report.halted = halted
            await self.safety.set_ready(
                self.prefix + DAILY_LOSS_CONDITION,
                not halted,
                snapshot.halt_reason or "günlük zarar sınırı aşıldı"
                if halted
                else f"günlük zarar %{snapshot.daily_loss_pct:.2f}",
            )
            for position in snapshot.positions:
                await self._liquidation(position.market, position.symbol, position, report)
        for target in targets:
            await self._connection(target, now)
            await self._protection(target, report)
        self.last = report
        return report

    async def _connection(self, target: GuardTarget, now: int) -> None:
        connected = bool(getattr(target.engine.venue, "stream_connected", True))
        if connected:
            self._down_since.pop(target.market, None)
            ready, detail = True, "kullanıcı akışı bağlı"
        else:
            since = self._down_since.setdefault(target.market, now)
            down_s = (now - since) / 1000
            ready = down_s < self.limits.stream_grace_s
            detail = f"kullanıcı akışı {down_s:.0f} sn kopuk"
        if self.prefix + stream_condition(target.market) in self._registered:
            await self.safety.set_ready(
                self.prefix + stream_condition(target.market), ready, detail
            )
        last = target.reconciler.last
        ok = last is None or last.ok
        critical = [i.rule for i in last.issues if i.severity == "critical"] if last else []
        if self.prefix + reconciled_condition(target.market) in self._registered:
            await self.safety.set_ready(
                self.prefix + reconciled_condition(target.market),
                ok,
                "mutabakat tamam" if ok else "kritik fark: " + ", ".join(critical or ["hata"]),
            )

    async def _protection(self, target: GuardTarget, report: GuardReport) -> None:
        engine = target.engine
        missing = [s for s in engine.positions.positions if not engine.has_stop(s)]
        for symbol in missing:
            key = f"unprotected:{target.market.value}:{symbol}"
            if key not in self._alerted:
                self._alerted.add(key)
                await self._event(
                    "guard.unprotected_position",
                    "critical",
                    symbol,
                    "mutabakat tetiklendi",
                    {"market": target.market.value},
                )
        if missing:
            report.actions.append("reconcile:" + target.market.value)
            await target.reconciler.run("guard_unprotected")
        for symbol in list(engine.positions.positions):
            if engine.has_stop(symbol):
                self._alerted.discard(f"unprotected:{target.market.value}:{symbol}")

    async def _liquidation(
        self, market: Market, symbol: str, position: Any, report: GuardReport
    ) -> None:
        distance = position.liquidation_distance_pct
        key = f"liquidation:{market.value}:{symbol}"
        limit = self.limits.min_liquidation_distance_pct
        if distance is None or distance >= limit:
            self._alerted.discard(key)
            return
        details = {"distance_pct": round(float(distance), 2), "limit_pct": str(limit)}
        if key not in self._alerted:
            self._alerted.add(key)
            await self._event("guard.liquidation_near", "critical", symbol, "uyarı", details)
            await self._alert(
                "Tasfiye fiyatı yakın", f"{symbol}: tasfiyeye %{distance:.1f} (sınır %{limit})"
            )
        if distance < limit / Decimal(3):
            for target in self.targets():
                if target.market is market and symbol in target.engine.positions.positions:
                    report.actions.append(f"emergency_close:{symbol}")
                    await self._event(
                        "guard.emergency_close", "critical", symbol, "pozisyon kapatıldı", details
                    )
                    await target.engine.close(symbol, reason="tasfiye yakın", emergency=True)

    # --- Döngü --------------------------------------------------------------------------------

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.check()
            except Exception as exc:  # bekçi hiçbir hatada durmaz
                logger.error("Risk bekçisi denetimi başarısız", extra={"error": repr(exc)})
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self.limits.guard_interval_s)

    # --- Kayıt ve uyarı ------------------------------------------------------------------------

    async def _event(
        self,
        rule: str,
        severity: str,
        symbol: str | None,
        action: str,
        details: dict[str, Any],
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO risk_events (ts, rule, severity, market, symbol, details, action)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self._clock(),
                rule,
                severity,
                details.get("market"),
                symbol,
                json.dumps(details, ensure_ascii=False, default=str),
                action,
            ),
        )

    async def _alert(self, title: str, message: str) -> None:
        if self.bus is not None:
            await self.bus.publish(
                Alert(severity=Severity.CRITICAL, title=title, message=message, context={})
            )
