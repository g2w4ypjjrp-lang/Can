"""Borsa ↔ yerel kayıt mutabakatı.

Kullanıcı akışı koptuğunda, motor yeniden başladığında ve düzenli aralıklarla çalışır. Borsa
**tek doğru kaynaktır**; yerel kayıt borsaya göre düzeltilir, düzeltilemeyen her fark
``risk_events`` tablosuna yazılır ve rapora eklenir.

Denetimler:

1. **Açık emirler:** yerelde açık görünen her emir borsada aranır (açık emir listesi, yoksa
   istemci kimliğiyle sorgu). Durumu bilinmeyen (gönderim sonucu belirsiz) emirler borsada
   yoksa ve bekleme süresi geçtiyse "gönderilmedi" olarak kapatılır.
2. **Kaçırılan dolumlar:** borsada gerçekleşen ama yerelde işlenmemiş miktar REST'ten alınır
   (tekilleştirme çift sayımı önler). Tetiklenen koşullu emirde dolum, oluşan gerçek emrin
   kimliğiyle alınır.
3. **Bilinmeyen emirler:** borsada olup bu motorun kaydında olmayan emirler. Bu motorun önekini
   taşıyorsa uyarı; kullanıcının elle verdiği emirlere **dokunulmaz** (yalnızca bilgi).
4. **Pozisyonlar:** Futures'ta borsa pozisyonu yerel pozisyonla, Spot'ta temel varlık bakiyesi
   yerel pozisyon miktarıyla karşılaştırılır. Fark kritik olaydır.
5. **Korumasız pozisyon:** açık pozisyonun etkin bir stop emri yoksa koruma yeniden kurulur;
   kurulamazsa kritik olay.
6. **Artık koruma emri:** pozisyon kapanmışken açık kalan koruma emirleri iptal edilir.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from ati_engine.core.models import Market, OrderStatus
from ati_engine.execution.engine import PROTECTIVE, TradingEngine
from ati_engine.execution.orders import OrderRecord
from ati_engine.execution.venue import ExchangeOrder, Fill, VenueError

logger = logging.getLogger(__name__)

Severity = Literal["info", "warning", "critical"]
ZERO = Decimal(0)


@dataclass(frozen=True)
class ReconcileIssue:
    rule: str
    severity: Severity
    symbol: str | None
    action: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReconcileReport:
    started_ms: int
    market: str
    mode: str
    trigger: str
    finished_ms: int = 0
    orders_checked: int = 0
    orders_updated: int = 0
    fills_recovered: int = 0
    reprotected: int = 0
    issues: list[ReconcileIssue] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and not any(i.severity == "critical" for i in self.issues)

    def as_dict(self) -> dict[str, Any]:
        return {
            "started_ms": self.started_ms,
            "finished_ms": self.finished_ms,
            "market": self.market,
            "mode": self.mode,
            "trigger": self.trigger,
            "ok": self.ok,
            "orders_checked": self.orders_checked,
            "orders_updated": self.orders_updated,
            "fills_recovered": self.fills_recovered,
            "reprotected": self.reprotected,
            "error": self.error,
            "issues": [
                {
                    "rule": i.rule,
                    "severity": i.severity,
                    "symbol": i.symbol,
                    "action": i.action,
                    "details": i.details,
                }
                for i in self.issues
            ],
        }


class Reconciler:
    def __init__(
        self,
        engine: TradingEngine,
        *,
        unknown_grace_s: float = 60.0,
        qty_tolerance: Decimal = Decimal("0.00000001"),
    ) -> None:
        self.engine = engine
        self.unknown_grace_s = unknown_grace_s
        self.qty_tolerance = qty_tolerance
        self._lock = asyncio.Lock()
        self.last: ReconcileReport | None = None
        self.runs = 0

    @property
    def _prefix(self) -> str:
        return f"ati{self.engine.mode.value[0]}"

    async def run(self, trigger: str = "periodic") -> ReconcileReport:
        async with self._lock:  # aynı anda tek mutabakat
            engine = self.engine
            report = ReconcileReport(
                started_ms=_now_ms(),
                market=engine.market.value,
                mode=engine.mode.value,
                trigger=trigger,
            )
            try:
                touched = await self._orders(report)
                await self._fills(report, touched)
                await engine.settle()
                await self._positions(report)
                await self._protection(report)
            except VenueError as exc:
                report.error = f"borsaya ulaşılamadı: {exc}"[:300]
                report.issues.append(
                    ReconcileIssue(
                        "reconcile_failed", "warning", None, "sonraki denemede tekrar", {}
                    )
                )
            report.finished_ms = _now_ms()
            await self._record(report)
            self.last = report
            self.runs += 1
            return report

    async def run_forever(self, interval_s: float, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.run("periodic")
            except Exception as exc:  # mutabakat döngüsü hiçbir hatada durmaz
                logger.error("Mutabakat başarısız", extra={"error": repr(exc)})
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=interval_s)

    # --- 1. Açık emirler ve 3. bilinmeyen emirler -----------------------------------------

    async def _orders(self, report: ReconcileReport) -> list[OrderRecord]:
        engine = self.engine
        orders = engine.orders
        exchange_open = {o.client_id: o for o in await engine.venue.open_orders()}
        touched: list[OrderRecord] = []
        for record in list(orders.open_records()):
            report.orders_checked += 1
            before = (record.status, record.executed_qty)
            found: ExchangeOrder | None = exchange_open.get(record.client_id)
            if found is None:
                found = await engine.venue.query(
                    record.symbol, record.client_id, conditional=record.conditional
                )
            if found is not None:
                await orders.apply_order(found)
                touched.append(record)
                if (record.status, record.executed_qty) != before:
                    report.orders_updated += 1
                continue
            age_s = (_now_ms() - record.created_ms) / 1000
            if record.status is OrderStatus.PENDING_NEW and age_s < self.unknown_grace_s:
                continue  # gönderim henüz sürüyor olabilir
            unresolved = record.status is OrderStatus.PENDING_NEW
            await orders.mark(
                record,
                OrderStatus.REJECTED if unresolved else OrderStatus.EXPIRED,
                "borsada bulunamadı (mutabakat)",
            )
            report.orders_updated += 1
            report.issues.append(
                ReconcileIssue(
                    "order_not_found" if unresolved else "order_vanished",
                    "info" if unresolved else "warning",
                    record.symbol,
                    "yerel kayıt kapatıldı",
                    {"client_id": record.client_id, "purpose": record.purpose},
                )
            )
        for client_id, order in exchange_open.items():
            if client_id in orders.records:
                continue
            own = client_id.startswith(self._prefix)
            report.issues.append(
                ReconcileIssue(
                    "unknown_own_order" if own else "foreign_order",
                    "warning" if own else "info",
                    order.symbol,
                    "dokunulmadı",
                    {"client_id": client_id, "type": order.type.value, "side": order.side.value},
                )
            )
        return touched

    # --- 2. Kaçırılan dolumlar ----------------------------------------------------------------

    async def _fills(self, report: ReconcileReport, touched: list[OrderRecord]) -> None:
        orders = self.engine.orders
        for record in touched:
            before = orders.applied_qty.get(record.client_id, ZERO)
            if record.conditional and record.actual_order_id:
                if before > 0:
                    continue
                fills = await self.engine.venue.fills(record.symbol, record.actual_order_id)
                for fill in fills:
                    await orders.apply_fill(_as_fill_of(record, fill))
            elif record.executed_qty > before:
                await orders.ensure_fills(record, within_s=0)
            if orders.applied_qty.get(record.client_id, ZERO) > before:
                report.fills_recovered += 1
                report.issues.append(
                    ReconcileIssue(
                        "missed_fills",
                        "info",
                        record.symbol,
                        "dolumlar REST'ten işlendi",
                        {"client_id": record.client_id},
                    )
                )

    # --- 4. Pozisyonlar -------------------------------------------------------------------------

    async def _positions(self, report: ReconcileReport) -> None:
        engine = self.engine
        local = {s: p.quantity for s, p in engine.positions.positions.items()}
        if engine.market is Market.USDM_FUTURES:
            remote = {p.symbol: p.quantity for p in await engine.venue.positions()}
            for symbol in sorted(set(local) | set(remote)):
                mine, theirs = local.get(symbol, ZERO), remote.get(symbol, ZERO)
                if abs(mine - theirs) <= self.qty_tolerance:
                    continue
                foreign = symbol not in local
                report.issues.append(
                    ReconcileIssue(
                        "foreign_position" if foreign else "position_mismatch",
                        "warning" if foreign else "critical",
                        symbol,
                        "dokunulmadı" if foreign else "yeni işlemler durdurulmalı",
                        {"local": str(mine), "exchange": str(theirs)},
                    )
                )
            return
        balances = {b.asset: b.free + b.locked for b in await engine.venue.balances()}
        for symbol, qty in local.items():
            info = engine.symbols(symbol)
            base = info.base_asset if info else symbol.removesuffix(engine.venue.quote)
            held = balances.get(base, ZERO)
            if held + self.qty_tolerance < qty:
                report.issues.append(
                    ReconcileIssue(
                        "balance_shortfall",
                        "critical",
                        symbol,
                        "yeni işlemler durdurulmalı",
                        {"local": str(qty), "exchange": str(held), "asset": base},
                    )
                )

    # --- 5-6. Koruma emirleri --------------------------------------------------------------------

    async def _protection(self, report: ReconcileReport) -> None:
        engine = self.engine
        open_positions = set(engine.positions.positions)
        for record in list(engine.orders.open_records()):
            if record.purpose in PROTECTIVE and record.symbol not in open_positions:
                if record.status is OrderStatus.PENDING_NEW:
                    continue
                await engine.orders.cancel(record.client_id)
                report.issues.append(
                    ReconcileIssue(
                        "stale_protection",
                        "info",
                        record.symbol,
                        "iptal edildi",
                        {"client_id": record.client_id},
                    )
                )
        for symbol in sorted(open_positions):
            managed = engine.managed.get(symbol)
            if engine.has_stop(symbol) or managed is None:
                if managed is None and not engine.has_stop(symbol):
                    report.issues.append(
                        ReconcileIssue(
                            "unprotected_position",
                            "critical",
                            symbol,
                            "karar kaydı yok: koruma kurulamadı",
                            {},
                        )
                    )
                continue
            wants_stop = (
                managed.intent.stop_loss is not None
                or managed.intent.trailing_callback_pct is not None
                or managed.tp_filled > 0
            )
            if not wants_stop:
                continue
            ok = await engine.reprotect(symbol)
            await engine.settle()
            if ok and engine.has_stop(symbol):
                report.reprotected += 1
                report.issues.append(
                    ReconcileIssue(
                        "unprotected_position", "warning", symbol, "koruma yeniden kuruldu"
                    )
                )
            else:
                report.issues.append(
                    ReconcileIssue("unprotected_position", "critical", symbol, "koruma kurulamadı")
                )

    # --- Kayıt ------------------------------------------------------------------------------------

    async def _record(self, report: ReconcileReport) -> None:
        db = self.engine.db
        for issue in report.issues:
            if issue.severity == "info" and issue.rule not in ("missed_fills", "stale_protection"):
                continue
            await db.execute(
                """
                INSERT INTO risk_events (ts, rule, severity, market, symbol, details, action)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.finished_ms,
                    f"reconcile.{issue.rule}",
                    issue.severity,
                    report.market,
                    issue.symbol,
                    json.dumps(
                        {"mode": report.mode, "trigger": report.trigger, **issue.details},
                        ensure_ascii=False,
                    ),
                    issue.action,
                ),
            )


def _as_fill_of(record: OrderRecord, fill: Fill) -> Fill:
    return Fill(
        client_id=record.client_id,
        exchange_order_id=fill.exchange_order_id,
        trade_id=fill.trade_id,
        symbol=fill.symbol,
        side=fill.side,
        price=fill.price,
        qty=fill.qty,
        commission=fill.commission,
        commission_asset=fill.commission_asset,
        is_maker=fill.is_maker,
        ts=fill.ts,
        realized_pnl=fill.realized_pnl,
    )


def _now_ms() -> int:
    return int(time.time() * 1000)
