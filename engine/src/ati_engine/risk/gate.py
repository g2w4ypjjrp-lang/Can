"""Risk kapısı: her işlem açılmadan önce bağımsız denetim.

İşlem motoru bir pozisyon açmak istediğinde kapı aşağıdaki kuralların **hepsini** sırayla
uygular; biri bile sağlanmazsa işlem açılmaz ve tüm gerekçeler kaydedilir:

========================  ==================================================================
Kural                     Açıklama
========================  ==================================================================
``mode_mismatch``         İşlem modu, yürütücünün moduyla aynı olmalı (ör. TESTNET)
``engine_state``          Motor RUNNING olmalı (güvenli mod / acil durdurma → ret)
``stop_required``         Zarar durdur zorunlu
``stop_side``             Zarar durdur pozisyonun doğru tarafında olmalı
``no_price``              İşlem yapılacak yerden güncel fiyat alınamadı
``price_deviation``       Niyetteki fiyat güncel fiyattan sınırdan fazla sapmış (eski sinyal)
``account_unavailable``   Hesap bilgisi (özsermaye/pozisyonlar) borsadan okunamadı
``daily_halt``            Günlük zarar sınırı bugün aşıldı: gün sonuna kadar yeni işlem yok
``no_equity``             Özsermaye sıfır veya negatif
``risk_per_trade``        Zarar durdurda kayıp + komisyon + kayma payı > özsermayenin %X'i
``daily_loss_budget``     Bugünkü kayıp + bu işlemin riski > günlük zarar sınırı
``max_open_positions``    Açık (ve açılmakta olan) pozisyon sayısı sınırda
``leverage``              Kaldıraç sınırı (Futures; verilmezse 1x kabul edilir)
``spot_leverage``         Spot'ta kaldıraç olmaz
``total_leverage``        Toplam pozisyon büyüklüğü / özsermaye sınırı aşıyor
``liquidation_distance``  Tahmini tasfiye fiyatı güncel fiyata sınırdan yakın
``stop_beyond_liq``       Zarar durdur tahmini tasfiye fiyatının ötesinde
========================  ==================================================================

Risk hesabında özsermaye olarak gün başı ve güncel özsermayenin **küçüğü** kullanılır.
Tasfiye uzaklığı, ayrık (isolated) kaldıraç formülü ile çapraz (cross) teminat yaklaşımının
**daha kötüsü** alınarak tahmin edilir.

Onaylanan işleme kapı imzalı, süreli (``approval_ttl_s``) ve tek kullanımlık bir onay verir;
emir yöneticisi giriş emrini bu onay olmadan göndermez (``execution/approval.py``).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections.abc import Callable, Mapping, Sequence
from decimal import ROUND_DOWN, Decimal
from typing import Any

from ati_engine.config import RiskLimits
from ati_engine.core.models import EngineState, Market, Side, TradingMode, format_decimal
from ati_engine.execution.approval import (
    ApprovalError,
    RiskApproval,
    RiskDecision,
    RiskReason,
)
from ati_engine.execution.engine import TradeIntent, TradingEngine
from ati_engine.execution.venue import OrderRequest
from ati_engine.risk.account import AccountMonitor, AccountSnapshot
from ati_engine.storage.database import Database

logger = logging.getLogger(__name__)

ZERO = Decimal(0)
HUNDRED = Decimal(100)
DEFAULT_FEES = {Market.SPOT: Decimal("0.001"), Market.USDM_FUTURES: Decimal("0.0005")}


def trade_risk(
    *,
    quantity: Decimal,
    entry: Decimal,
    stop: Decimal,
    fee_rate: Decimal,
    slippage_pct: Decimal,
) -> Decimal:
    """Zarar durdurda gerçekleşecek tahmini kayıp: fiyat farkı + iki yön komisyon + kayma."""
    notional = quantity * entry
    fees = notional * fee_rate * 2
    return quantity * abs(entry - stop) + fees + notional * slippage_pct / HUNDRED


def size_for_risk(
    *,
    equity: Decimal,
    risk_pct: Decimal,
    entry: Decimal,
    stop: Decimal,
    fee_rate: Decimal,
    slippage_pct: Decimal,
    step: Decimal,
) -> Decimal:
    """Belirli risk yüzdesine göre miktar (adım boyutuna aşağı yuvarlanır)."""
    per_unit = abs(entry - stop) + entry * (fee_rate * 2 + slippage_pct / HUNDRED)
    if per_unit <= 0 or equity <= 0:
        return ZERO
    raw = equity * risk_pct / HUNDRED / per_unit
    return (raw / step).to_integral_value(rounding=ROUND_DOWN) * step


def liquidation_distance_pct(
    *, leverage: int, equity: Decimal, total_notional: Decimal, maintenance_rate: Decimal
) -> Decimal:
    """Tasfiyeye kadar fiyat hareketi (%), ayrık ve çapraz tahminlerin kötüsü."""
    isolated = (Decimal(1) / Decimal(max(leverage, 1)) - maintenance_rate) * HUNDRED
    if total_notional <= 0:
        return isolated
    cross = (equity / total_notional - maintenance_rate) * HUNDRED
    return min(isolated, cross)


class RiskGate:
    def __init__(
        self,
        *,
        limits: RiskLimits,
        db: Database,
        monitor: AccountMonitor,
        engines: Callable[[], Sequence[TradingEngine]],
        trading_mode: Callable[[], TradingMode],
        engine_state: Callable[[], EngineState],
        fees: Mapping[Market, Decimal] | None = None,
        clock: Callable[[], int] | None = None,
    ) -> None:
        self.limits = limits
        self.db = db
        self.monitor = monitor
        self.engines = engines
        self.trading_mode = trading_mode
        self.engine_state = engine_state
        self.fees = dict(fees or DEFAULT_FEES)
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._key = secrets.token_bytes(32)  # yalnızca bu süreçte; diskte yok
        self._used: dict[str, int] = {}  # tüketilmiş onaylar (nonce → süre sonu)
        self._reserved: dict[tuple[Market, str], int] = {}  # onaylı, sonuçlanmamış açılışlar
        self._lock = asyncio.Lock()
        self.stats = {"approved": 0, "rejected": 0, "verify_failed": 0}

    # --- Değerlendirme ---------------------------------------------------------------------

    async def evaluate(self, intent: TradeIntent, engine: TradingEngine) -> RiskDecision:
        async with self._lock:  # eşzamanlı açılışlar sırayla değerlendirilir
            decision = await self._evaluate(intent, engine)
        if decision.approved:
            self.stats["approved"] += 1
        else:
            self.stats["rejected"] += 1
            await self._record_rejection(intent, decision)
        return decision

    async def _evaluate(self, intent: TradeIntent, engine: TradingEngine) -> RiskDecision:
        limits = self.limits
        reasons: list[RiskReason] = []
        metrics: dict[str, Any] = {}

        def reject(code: str, message: str) -> None:
            reasons.append(RiskReason(code, message))

        mode = self.trading_mode()
        if mode is not engine.mode:
            reject("mode_mismatch", f"İşlem modu {mode.value}, yürütücü {engine.mode.value}")
        state = self.engine_state()
        if state is not EngineState.RUNNING:
            reject("engine_state", f"Motor durumu {state.value}: yeni işlem açılmaz")

        direction = 1 if intent.direction > 0 else -1
        stop = intent.stop_loss
        if stop is None:
            reject("stop_required", "Zarar durdur zorunludur")
        elif (direction > 0 and stop >= intent.reference_price) or (
            direction < 0 and stop <= intent.reference_price
        ):
            reject("stop_side", "Zarar durdur fiyatı pozisyonun yanlış tarafında")

        price: Decimal | None = None
        try:
            price = await engine.venue.price(intent.symbol)
        except Exception as exc:
            logger.warning("Fiyat alınamadı", extra={"symbol": intent.symbol, "error": repr(exc)})
        if price is None or price <= 0:
            reject("no_price", f"{intent.symbol} için güncel fiyat alınamadı")
        else:
            deviation = abs(intent.reference_price - price) / price * HUNDRED
            metrics.update(price=_s(price), price_deviation_pct=_r(deviation))
            if deviation > limits.max_price_deviation_pct:
                reject(
                    "price_deviation",
                    f"Fiyat sinyalden bu yana %{deviation:.2f} değişti "
                    f"(sınır %{limits.max_price_deviation_pct})",
                )

        snapshot: AccountSnapshot | None = None
        try:
            snapshot = await self.monitor.snapshot(max_age_s=limits.max_snapshot_age_s)
        except Exception as exc:
            reject("account_unavailable", f"Hesap bilgisi borsadan okunamadı: {type(exc).__name__}")
        if snapshot is not None:
            self._account_rules(intent, engine, snapshot, price, reject, metrics)

        if intent.quantity <= 0:
            reject("quantity", "Miktar pozitif olmalı")
        if reasons:
            return RiskDecision(False, tuple(reasons), metrics)
        approval = self._issue(
            decision_id=intent.decision_id,
            mode=engine.mode,
            market=engine.market,
            symbol=intent.symbol,
            side=Side.BUY if direction > 0 else Side.SELL,
            max_quantity=intent.quantity,
        )
        self._reserved[(engine.market, intent.symbol)] = approval.expires_ms
        return RiskDecision(True, (), metrics, approval)

    def _account_rules(
        self,
        intent: TradeIntent,
        engine: TradingEngine,
        snapshot: AccountSnapshot,
        price: Decimal | None,
        reject: Callable[[str, str], None],
        metrics: dict[str, Any],
    ) -> None:
        limits = self.limits
        metrics.update(
            equity=_s(snapshot.equity),
            day_start_equity=_s(snapshot.day_start_equity),
            daily_loss_pct=_r(snapshot.daily_loss_pct),
        )
        if snapshot.halted_at is not None:
            reject(
                "daily_halt",
                "Günlük zarar sınırı bugün aşıldı; gün sonuna kadar yeni işlem açılmaz",
            )
        equity = min(snapshot.equity, snapshot.day_start_equity)
        if equity <= 0:
            reject("no_equity", "Özsermaye sıfır veya negatif")
            return
        entry = price or intent.reference_price
        qty = intent.quantity
        notional = qty * entry
        stop = intent.stop_loss
        if stop is not None:
            risk = trade_risk(
                quantity=qty,
                entry=entry,
                stop=stop,
                fee_rate=self.fees.get(engine.market, DEFAULT_FEES[engine.market]),
                slippage_pct=limits.slippage_allowance_pct,
            )
            risk_pct = risk / equity * HUNDRED
            metrics.update(trade_risk=_s(risk), trade_risk_pct=_r(risk_pct))
            if risk_pct > limits.max_risk_per_trade_pct:
                reject(
                    "risk_per_trade",
                    f"İşlem riski özsermayenin %{risk_pct:.2f}'i "
                    f"(sınır %{limits.max_risk_per_trade_pct})",
                )
            budget = snapshot.day_start_equity * limits.max_daily_loss_pct / HUNDRED
            if snapshot.daily_loss + risk > budget:
                reject(
                    "daily_loss_budget",
                    f"Bugünkü kayıp ({snapshot.daily_loss:.2f}) ile bu işlemin riski "
                    f"({risk:.2f}) günlük sınırı ({budget:.2f}) aşar",
                )

        # Açık pozisyonlar + bu kapının onaylayıp henüz sonuçlanmamış açılışları (eşzamanlı
        # açılışlar sınırı birlikte aşamaz; onaylanmamış açılışlar birbirini engellemez).
        occupied = {(p.market, p.symbol) for p in snapshot.positions}
        by_market = {e.market: e for e in self.engines()}
        for other in by_market.values():
            occupied.update((other.market, s) for s in other.positions.positions)
        now = self._clock()
        for key, expires in list(self._reserved.items()):
            owner = by_market.get(key[0])
            managed = owner.managed.get(key[1]) if owner is not None else None
            if expires < now or managed is None or managed.state not in ("evaluating", "opening"):
                del self._reserved[key]
                continue
            occupied.add(key)
        occupied.discard((engine.market, intent.symbol))
        metrics["open_positions"] = len(occupied)
        if len(occupied) >= limits.max_open_positions:
            reject(
                "max_open_positions",
                f"Açık pozisyon sayısı sınırda ({len(occupied)}/{limits.max_open_positions})",
            )

        total_after = snapshot.total_notional + notional
        effective = total_after / equity
        metrics["total_leverage"] = _r(effective)
        if effective > limits.max_total_leverage:
            reject(
                "total_leverage",
                f"Toplam pozisyon özsermayenin {effective:.2f} katı olur "
                f"(sınır {limits.max_total_leverage})",
            )
        if engine.market is Market.SPOT:
            if intent.leverage not in (None, 1):
                reject("spot_leverage", "Spot'ta kaldıraç kullanılamaz")
            return
        leverage = intent.leverage or 1
        metrics["leverage"] = leverage
        if leverage > limits.max_leverage:
            reject("leverage", f"Kaldıraç {leverage}x (sınır {limits.max_leverage}x)")
        distance = liquidation_distance_pct(
            leverage=leverage,
            equity=equity,
            total_notional=total_after,
            maintenance_rate=limits.maintenance_margin_rate,
        )
        metrics["liquidation_distance_pct"] = _r(distance)
        if distance < limits.min_liquidation_distance_pct:
            reject(
                "liquidation_distance",
                f"Tahmini tasfiye uzaklığı %{distance:.1f} "
                f"(en az %{limits.min_liquidation_distance_pct})",
            )
        if stop is not None and entry > 0:
            stop_pct = abs(entry - stop) / entry * HUNDRED
            if stop_pct >= distance:
                reject("stop_beyond_liq", "Zarar durdur tahmini tasfiye fiyatının ötesinde")

    # --- Onay ---------------------------------------------------------------------------------

    def _payload(
        self,
        decision_id: str,
        mode: TradingMode,
        market: Market,
        symbol: str,
        side: Side,
        max_quantity: Decimal,
        expires_ms: int,
        nonce: str,
    ) -> bytes:
        return "|".join(
            (
                decision_id,
                mode.value,
                market.value,
                symbol,
                side.value,
                format_decimal(max_quantity),
                str(expires_ms),
                nonce,
            )
        ).encode()

    def _issue(
        self,
        *,
        decision_id: str,
        mode: TradingMode,
        market: Market,
        symbol: str,
        side: Side,
        max_quantity: Decimal,
    ) -> RiskApproval:
        expires = self._clock() + int(self.limits.approval_ttl_s * 1000)
        nonce = secrets.token_hex(12)
        mac = hmac.new(
            self._key,
            self._payload(decision_id, mode, market, symbol, side, max_quantity, expires, nonce),
            hashlib.sha256,
        ).hexdigest()
        return RiskApproval(
            decision_id, mode, market, symbol, side, max_quantity, expires, nonce, mac
        )

    def verify(
        self,
        approval: RiskApproval | None,
        request: OrderRequest,
        *,
        mode: TradingMode,
        market: Market,
    ) -> None:
        try:
            self._verify(approval, request, mode=mode, market=market)
        except ApprovalError:
            self.stats["verify_failed"] += 1
            raise

    def _verify(
        self,
        approval: RiskApproval | None,
        request: OrderRequest,
        *,
        mode: TradingMode,
        market: Market,
    ) -> None:
        if approval is None:
            raise ApprovalError("Giriş emri risk kapısı onayı olmadan gönderilemez")
        expected = hmac.new(
            self._key,
            self._payload(
                approval.decision_id,
                approval.mode,
                approval.market,
                approval.symbol,
                approval.side,
                approval.max_quantity,
                approval.expires_ms,
                approval.nonce,
            ),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, approval.mac):
            raise ApprovalError("Risk onayının imzası geçersiz")
        now = self._clock()
        if now > approval.expires_ms:
            raise ApprovalError("Risk onayının süresi dolmuş")
        self._used = {n: exp for n, exp in self._used.items() if exp >= now}
        if approval.nonce in self._used:
            raise ApprovalError("Risk onayı daha önce kullanıldı")
        if (approval.mode, approval.market, approval.symbol, approval.side) != (
            mode,
            market,
            request.symbol,
            request.side,
        ):
            raise ApprovalError("Risk onayı bu emre ait değil")
        if request.quantity is None or request.quantity > approval.max_quantity:
            raise ApprovalError("Emir miktarı onaylanan miktarı aşıyor")
        self._used[approval.nonce] = approval.expires_ms

    # --- Kayıt --------------------------------------------------------------------------------

    async def _record_rejection(self, intent: TradeIntent, decision: RiskDecision) -> None:
        first = decision.reasons[0].code if decision.reasons else "unknown"
        await self.db.execute(
            """
            INSERT INTO risk_events (ts, rule, severity, market, symbol, details, action)
            VALUES (?, ?, 'warning', ?, ?, ?, 'işlem açılmadı')
            """,
            (
                self._clock(),
                f"gate.{first}",
                intent.market.value,
                intent.symbol,
                json.dumps(
                    {
                        "decision_id": intent.decision_id,
                        "reasons": [
                            {"code": r.code, "message": r.message} for r in decision.reasons
                        ],
                        "metrics": decision.metrics,
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            ),
        )


def _s(value: Decimal) -> str:
    return format_decimal(value)


def _r(value: Decimal) -> float:
    return round(float(value), 4)
