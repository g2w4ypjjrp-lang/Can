"""İşlem motoru: işlem niyetini (intent) emirlere çevirir ve pozisyonun yaşam döngüsünü yönetir.

* **Ön koşullar:** motor ``RUNNING`` olmalı (güvenli mod veya acil durdurmada yeni pozisyon
  açılmaz), sembol başına tek pozisyon, Spot'ta yalnızca long. Miktar ve fiyat borsa
  filtrelerine yuvarlanır; en düşük emir değeri denetlenir.
* **Giriş:** piyasa (veya limit) emri; dolum beklenir. Kısmi dolumda koruma, gerçekleşen
  miktara göre kurulur.
* **Koruma (borsa tarafında):**
  - Futures: zarar durdur ``STOP_MARKET closePosition``, kademeli hedefler
    ``TAKE_PROFIT_MARKET reduceOnly``, isteğe bağlı iz süren stop ``TRAILING_STOP_MARKET``.
  - Spot: her hedef için OCO (hedef limit + zarar durdur); OCO'da bir bacak dolunca diğeri
    borsa tarafından iptal edilir.
* **Kademeli kâr alma:** ilk hedef dolunca zarar durdur giriş fiyatına çekilir.
* **Çıkış:** koruma emirleri iptal edilir, kalan pozisyon piyasa emriyle (reduceOnly) kapanır.

Yuvarlama yönü: zarar durdur hiçbir zaman istenenden daha uzağa, hedef hiçbir zaman daha
uzağa yuvarlanmaz.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Any

from ati_engine.core.models import EngineState, Market, OrderStatus, OrderType, Side, SymbolInfo
from ati_engine.execution.orders import OrderManager, OrderRecord, make_client_id
from ati_engine.execution.positions import PositionBook
from ati_engine.execution.venue import Fill, OcoRequest, OrderRequest, Purpose, Venue
from ati_engine.storage.database import Database

logger = logging.getLogger(__name__)

PROTECTIVE = frozenset({"stop_loss", "take_profit", "trailing_stop"})


class ExecutionBlocked(RuntimeError):
    """Ön koşul sağlanmadığı için işlem açılmadı (gerekçe mesajdadır)."""


@dataclass(frozen=True)
class TakeProfit:
    price: Decimal
    fraction: Decimal  # pozisyonun oranı (toplam 1)


@dataclass(frozen=True)
class TradeIntent:
    decision_id: str
    market: Market
    symbol: str
    direction: int  # +1 long, -1 short
    quantity: Decimal
    reference_price: Decimal  # en düşük emir değeri denetimi ve limit için
    stop_loss: Decimal | None = None
    take_profits: tuple[TakeProfit, ...] = ()
    trailing_callback_pct: Decimal | None = None
    trailing_activation: Decimal | None = None
    leverage: int | None = None
    limit_price: Decimal | None = None  # verilirse IOC limit giriş
    breakeven_after_first_tp: bool = True
    reason: str = ""
    strategy_id: str | None = None
    opportunity_score: float | None = None
    signals: tuple[str, ...] = ()
    # Aşama 11'de risk kapısı kararı; risk kapısı bağlanana kadar "pending" kaydedilir.
    risk_verdict: str = "pending"


@dataclass
class ManagedPosition:
    intent: TradeIntent
    entry_client_id: str
    state: str = "opening"  # opening | open | closing | closed | failed
    protection: list[str] = field(default_factory=list)
    filled_qty: Decimal = Decimal(0)
    tp_filled: int = 0
    generation: int = 0  # koruma yeniden kurulduğunda artar (benzersiz istemci kimlikleri)
    error: str | None = None


class TradingEngine:
    def __init__(
        self,
        *,
        venue: Venue,
        db: Database,
        symbols: Callable[[str], SymbolInfo | None],
        engine_state: Callable[[], EngineState] | None = None,
        fill_timeout_s: float = 30.0,
    ) -> None:
        self.venue = venue
        self.db = db
        self.market = venue.market
        self.mode = venue.mode
        self.symbols = symbols
        self.engine_state = engine_state or (lambda: EngineState.RUNNING)
        self.fill_timeout_s = fill_timeout_s
        self.positions = PositionBook(db, mode=self.mode, market=self.market)
        self.orders = OrderManager(db, venue, on_fill=self._on_fill, on_terminal=self._on_terminal)
        self.managed: dict[str, ManagedPosition] = {}
        self._events_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._background: set[asyncio.Task[Any]] = set()
        self._side_tasks: set[asyncio.Task[Any]] = set()
        self.on_stream_reset: Callable[[], Any] | None = None  # mutabakat tetikleyicisi

    def _spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def settle(self) -> None:
        """Arka plandaki koruma işlemlerinin (iptal/yeniden kurma) bitmesini bekler."""
        while self._background:
            await asyncio.gather(*list(self._background), return_exceptions=True)

    # --- Yaşam döngüsü ------------------------------------------------------------------

    async def start(self) -> None:
        await self.positions.load()
        await self.orders.load_open()
        await self._restore_managed()
        self._events_task = asyncio.create_task(self._consume_events())

    async def _restore_managed(self) -> None:
        """Yeniden başlatmada açık pozisyonların yönetimini karar kaydından geri kurar:
        koruma emirleri, dolmuş hedef sayısı ve kullanılmış koruma kuşakları (yeni istemci
        kimliklerinin eskilerle çakışmaması için)."""
        for symbol, position in self.positions.positions.items():
            if symbol in self.managed or not position.decision_id:
                continue
            row = await self.db.fetchone(
                "SELECT direction, features, strategy_id FROM decisions WHERE id = ?",
                (position.decision_id,),
            )
            if row is None:
                continue
            features = json.loads(row[1])
            intent = TradeIntent(
                decision_id=position.decision_id,
                market=self.market,
                symbol=symbol,
                direction=1 if row[0] == "long" else -1,
                quantity=_dec(features.get("quantity")) or abs(position.quantity),
                reference_price=_dec(features.get("reference_price")) or position.entry_price,
                stop_loss=_dec(features.get("stop_loss")),
                take_profits=tuple(
                    TakeProfit(Decimal(price), Decimal(fraction))
                    for price, fraction in features.get("take_profits") or []
                ),
                trailing_callback_pct=_dec(features.get("trailing_callback_pct")),
                trailing_activation=_dec(features.get("trailing_activation")),
                leverage=features.get("leverage"),
                breakeven_after_first_tp=bool(features.get("breakeven_after_first_tp", True)),
                strategy_id=row[2],
            )
            counts = await self.db.fetchone(
                """
                SELECT COUNT(*),
                       COALESCE(SUM(purpose = 'take_profit' AND status = 'FILLED'), 0)
                FROM orders
                WHERE decision_id = ? AND mode = ?
                  AND purpose IN ('stop_loss', 'take_profit', 'trailing_stop')
                """,
                (position.decision_id, self.mode.value),
            )
            used, tp_filled = (int(counts[0]), int(counts[1])) if counts else (0, 0)
            self.managed[symbol] = ManagedPosition(
                intent=intent,
                entry_client_id=make_client_id(self.mode, "entry", position.decision_id),
                state="open",
                protection=[
                    r.client_id
                    for r in self.orders.open_records()
                    if r.decision_id == position.decision_id and r.purpose in PROTECTIVE
                ],
                filled_qty=abs(position.quantity),
                tp_filled=tp_filled,
                # Her kuşak en az bir emir gönderir: emir sayısı kullanılmış kuşakların üst sınırı.
                generation=used,
            )

    async def stop(self) -> None:
        tasks = [t for t in (self._events_task, *self._side_tasks) if t is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await self.venue.close()

    async def _consume_events(self) -> None:
        async for event in self.venue.events():
            try:
                if event.kind == "order":
                    await self.orders.handle_event(event)
                elif event.kind in ("stream_reconnected", "stream_expired"):
                    if self.on_stream_reset is not None:
                        result = self.on_stream_reset()
                        if asyncio.iscoroutine(result):
                            # Olay tüketimi durmasın: mutabakat ayrı görevde çalışır.
                            task = asyncio.create_task(result)
                            self._side_tasks.add(task)
                            task.add_done_callback(self._side_tasks.discard)
                elif event.kind == "account":
                    await self._on_account(event.raw)
            except Exception as exc:  # bir olayın hatası akışı durdurmaz
                logger.error("Yürütme olayı işlenemedi", extra={"error": repr(exc)})

    async def _on_account(self, raw: dict[str, Any]) -> None:
        if "algo" in raw:
            # Koşullu emir değişti: belgelenmiş REST sorgusuyla güncel durumu al.
            for record in self.orders.open_records():
                if record.conditional:
                    found = await self.venue.query(
                        record.symbol, record.client_id, conditional=True
                    )
                    if found is not None:
                        await self.orders.apply_order(found)
            return
        account = raw.get("a")
        if isinstance(account, dict) and account.get("m") == "FUNDING_FEE":
            # Fonlama olayında ``P`` yalnızca ilgili pozisyonu taşır; birden fazla sembol
            # varsa ücret hangisine ait belirsizdir ve mutabakata bırakılır.
            symbols = {str(p.get("s")) for p in account.get("P") or [] if p.get("s")}
            if len(symbols) != 1:
                return
            symbol = symbols.pop()
            for balance in account.get("B") or []:
                change = Decimal(str(balance.get("bc", "0")))
                if change and balance.get("a") == self.venue.quote:
                    await self.positions.add_funding(symbol, -change)

    # --- Açılış ---------------------------------------------------------------------------

    def _check(self, intent: TradeIntent, info: SymbolInfo | None) -> SymbolInfo:
        state = self.engine_state()
        if state is not EngineState.RUNNING:
            raise ExecutionBlocked(f"Motor durumu {state.value}: yeni pozisyon açılmaz")
        if intent.market is not self.market:
            raise ExecutionBlocked("Niyet bu yürütücünün piyasasına ait değil")
        if info is None or not info.is_trading:
            raise ExecutionBlocked(f"{intent.symbol} işlem görmüyor")
        if self.market is Market.SPOT and intent.direction < 0:
            raise ExecutionBlocked("Spot'ta short açılamaz")
        if intent.symbol in self.managed and self.managed[intent.symbol].state in (
            "opening",
            "open",
            "closing",
        ):
            raise ExecutionBlocked(f"{intent.symbol} için açık pozisyon zaten var")
        if intent.take_profits and sum(tp.fraction for tp in intent.take_profits) > 1:
            raise ExecutionBlocked("Hedef oranlarının toplamı 1'i aşamaz")
        return info

    async def open(self, intent: TradeIntent) -> ManagedPosition:
        async with self._lock:
            info = self._check(intent, self.symbols(intent.symbol))
            qty = info.quantize_qty(intent.quantity)
            if qty < info.min_qty or qty * intent.reference_price < info.min_notional:
                raise ExecutionBlocked(
                    f"Emir borsa en düşük miktar/değer sınırının altında ({qty} x "
                    f"{intent.reference_price})"
                )
            entry_side = Side.BUY if intent.direction > 0 else Side.SELL
            managed = ManagedPosition(
                intent=intent,
                entry_client_id=make_client_id(self.mode, "entry", intent.decision_id),
            )
            self.managed[intent.symbol] = managed
        await self._record_decision(intent)
        if intent.leverage and self.market is Market.USDM_FUTURES:
            await self.venue.set_leverage(intent.symbol, intent.leverage)
        if intent.limit_price is not None:
            price = info.quantize_price(intent.limit_price, side=entry_side)
            request = OrderRequest(
                client_id=managed.entry_client_id,
                symbol=intent.symbol,
                side=entry_side,
                type=OrderType.LIMIT,
                quantity=qty,
                price=price,
                time_in_force=None,
                purpose="entry",
            )
        else:
            request = OrderRequest(
                client_id=managed.entry_client_id,
                symbol=intent.symbol,
                side=entry_side,
                type=OrderType.MARKET,
                quantity=qty,
                purpose="entry",
            )
        record = await self.orders.submit(request, decision_id=intent.decision_id)
        try:
            record = await self.orders.wait_terminal(record.client_id, self.fill_timeout_s)
        except TimeoutError:
            if intent.limit_price is not None:
                await self.orders.cancel(record.client_id)
        await self.orders.ensure_fills(record)
        position = self.positions.positions.get(intent.symbol)
        filled = abs(position.quantity) if position is not None else Decimal(0)
        managed.filled_qty = filled
        if filled == 0:
            managed.state = "failed"
            managed.error = record.last_error or f"giriş emri {record.status.value}"
            return managed
        managed.state = "open"
        await self._protect(managed, info)
        return managed

    async def _record_decision(self, intent: TradeIntent) -> None:
        """Karar günlüğü: "işlem neden açıldı" kaydı (emir ve pozisyon buna bağlanır)."""
        await self.db.execute(
            """
            INSERT OR IGNORE INTO decisions (id, created_at, mode, market, symbol, direction,
                strategy_id, opportunity_score, signals, features, risk_verdict)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                intent.decision_id,
                int(time.time() * 1000),
                self.mode.value,
                self.market.value,
                intent.symbol,
                "long" if intent.direction > 0 else "short",
                intent.strategy_id,
                intent.opportunity_score,
                json.dumps(list(intent.signals), ensure_ascii=False),
                json.dumps(
                    {
                        "reason": intent.reason,
                        "quantity": str(intent.quantity),
                        "reference_price": str(intent.reference_price),
                        "stop_loss": str(intent.stop_loss) if intent.stop_loss else None,
                        "take_profits": [
                            [str(tp.price), str(tp.fraction)] for tp in intent.take_profits
                        ],
                        "trailing_callback_pct": (
                            str(intent.trailing_callback_pct)
                            if intent.trailing_callback_pct
                            else None
                        ),
                        "leverage": intent.leverage,
                        "trailing_activation": (
                            str(intent.trailing_activation) if intent.trailing_activation else None
                        ),
                        "breakeven_after_first_tp": intent.breakeven_after_first_tp,
                    },
                    ensure_ascii=False,
                ),
                intent.risk_verdict,
            ),
        )

    # --- Koruma -------------------------------------------------------------------------

    def _stop_price(self, info: SymbolInfo, price: Decimal, direction: int) -> Decimal:
        # Long'da stop aşağıdadır: yukarı (fiyata doğru) yuvarlanır; short'ta tersi.
        return info.quantize_price(price, side=Side.SELL if direction > 0 else Side.BUY)

    def _tp_price(self, info: SymbolInfo, price: Decimal, direction: int) -> Decimal:
        # Long'da hedef yukarıdadır: aşağı (fiyata doğru) yuvarlanır; short'ta tersi.
        return info.quantize_price(price, side=Side.BUY if direction > 0 else Side.SELL)

    def _legs(
        self, info: SymbolInfo, qty: Decimal, intent: TradeIntent
    ) -> list[tuple[Decimal, Decimal]]:
        """Hedef bacakları: (fiyat, miktar); sonuncusu kalan miktarı alır."""
        legs: list[tuple[Decimal, Decimal]] = []
        remaining = qty
        for index, tp in enumerate(intent.take_profits):
            last = (
                index == len(intent.take_profits) - 1
                and sum(t.fraction for t in intent.take_profits) == 1
            )
            amount = remaining if last else info.quantize_qty(qty * tp.fraction)
            amount = min(amount, remaining)
            if amount < info.min_qty:
                continue
            legs.append((self._tp_price(info, tp.price, intent.direction), amount))
            remaining -= amount
        return legs

    async def _protect(
        self, managed: ManagedPosition, info: SymbolInfo, *, stop: Decimal | None = None
    ) -> None:
        intent = managed.intent
        position = self.positions.positions.get(intent.symbol)
        if position is None:
            return
        qty = info.quantize_qty(abs(position.quantity))
        if qty <= 0:
            return
        direction = intent.direction
        exit_side = Side.SELL if direction > 0 else Side.BUY
        stop_price = stop if stop is not None else intent.stop_loss
        managed.generation += 1
        key = f"{intent.decision_id}#{managed.generation}"
        legs = (
            self._legs(info, qty, intent)
            if managed.tp_filled == 0
            else self._legs(info, qty, _remaining_targets(intent, managed.tp_filled))
        )
        if self.market is Market.USDM_FUTURES:
            if stop_price is not None:
                request = OrderRequest(
                    client_id=make_client_id(self.mode, "stop_loss", key),
                    symbol=intent.symbol,
                    side=exit_side,
                    type=OrderType.STOP_MARKET,
                    quantity=None,
                    trigger_price=self._stop_price(info, stop_price, direction),
                    close_position=True,
                    purpose="stop_loss",
                )
                await self._submit_protection(managed, request)
            for leg, (price, amount) in enumerate(legs):
                request = OrderRequest(
                    client_id=make_client_id(self.mode, "take_profit", key, leg),
                    symbol=intent.symbol,
                    side=exit_side,
                    type=OrderType.TAKE_PROFIT_MARKET,
                    quantity=amount,
                    trigger_price=price,
                    reduce_only=True,
                    purpose="take_profit",
                )
                await self._submit_protection(managed, request)
            if intent.trailing_callback_pct is not None:
                request = OrderRequest(
                    client_id=make_client_id(self.mode, "trailing_stop", key),
                    symbol=intent.symbol,
                    side=exit_side,
                    type=OrderType.TRAILING_STOP_MARKET,
                    quantity=qty,
                    reduce_only=True,
                    callback_rate=intent.trailing_callback_pct,
                    activation_price=(
                        self._tp_price(info, intent.trailing_activation, direction)
                        if intent.trailing_activation is not None
                        else None
                    ),
                    purpose="trailing_stop",
                )
                await self._submit_protection(managed, request)
            return
        # Spot (yalnızca long): hedef bacakları OCO, hedef yoksa tek zarar durdur.
        if stop_price is None and not legs:
            return
        trailing_bips = (
            int((intent.trailing_callback_pct * 100).to_integral_value(rounding=ROUND_DOWN))
            if intent.trailing_callback_pct is not None
            else None
        )
        covered = sum((amount for _, amount in legs), Decimal(0))
        if stop_price is not None:
            for leg, (price, amount) in enumerate(legs):
                oco = OcoRequest(
                    list_client_id=make_client_id(self.mode, "exit", key, leg),
                    symbol=intent.symbol,
                    side=Side.SELL,
                    quantity=amount,
                    take_profit_price=price,
                    stop_price=self._stop_price(info, stop_price, direction),
                    tp_client_id=make_client_id(self.mode, "take_profit", key, leg),
                    sl_client_id=make_client_id(self.mode, "stop_loss", key, leg),
                    trailing_delta_bips=trailing_bips,
                )
                records = await self.orders.submit_oco(oco, decision_id=intent.decision_id)
                managed.protection.extend(r.client_id for r in records)
            rest = qty - covered
            if rest >= info.min_qty:
                request = OrderRequest(
                    client_id=make_client_id(self.mode, "stop_loss", key, 99),
                    symbol=intent.symbol,
                    side=Side.SELL,
                    type=OrderType.STOP_MARKET,
                    quantity=info.quantize_qty(rest),
                    trigger_price=self._stop_price(info, stop_price, direction),
                    purpose="stop_loss",
                )
                await self._submit_protection(managed, request)
        else:
            for leg, (price, amount) in enumerate(legs):
                request = OrderRequest(
                    client_id=make_client_id(self.mode, "take_profit", key, leg),
                    symbol=intent.symbol,
                    side=Side.SELL,
                    type=OrderType.LIMIT,
                    quantity=amount,
                    price=price,
                    purpose="take_profit",
                )
                await self._submit_protection(managed, request)

    async def _submit_protection(self, managed: ManagedPosition, request: OrderRequest) -> None:
        record = await self.orders.submit(request, decision_id=managed.intent.decision_id)
        managed.protection.append(record.client_id)
        if record.status is OrderStatus.REJECTED:
            logger.error(
                "Koruma emri reddedildi",
                extra={
                    "symbol": request.symbol,
                    "purpose": request.purpose,
                    "error": record.last_error,
                },
            )

    async def _cancel_protection(self, managed: ManagedPosition) -> None:
        for client_id in list(managed.protection):
            record = self.orders.records.get(client_id)
            if record is not None and not record.status.is_terminal:
                await self.orders.cancel(client_id)
        managed.protection.clear()

    # --- Dolum ve sonuç olayları -----------------------------------------------------------

    async def _on_fill(self, record: OrderRecord, fill: Fill) -> None:
        info = self.symbols(record.symbol)
        base = info.base_asset if info else record.symbol.removesuffix("USDT")
        change = await self.positions.apply_fill(
            symbol=record.symbol,
            base_asset=base,
            side=fill.side,
            qty=fill.qty,
            price=fill.price,
            commission=fill.commission,
            commission_asset=fill.commission_asset,
            ts=fill.ts,
            decision_id=record.decision_id,
        )
        managed = self.managed.get(record.symbol)
        if managed is None or record.purpose not in PROTECTIVE | {"exit", "emergency_close"}:
            return
        if change.position is None:
            # Pozisyon tamamen kapandı: kalan koruma emirleri iptal edilir.
            managed.state = "closed"
            self._spawn(self._cancel_protection(managed))
            return

    async def _on_terminal(self, record: OrderRecord) -> None:
        managed = self.managed.get(record.symbol)
        if managed is None or record.client_id not in managed.protection:
            return
        if record.purpose != "take_profit" or record.status is not OrderStatus.FILLED:
            return
        managed.tp_filled += 1
        position = self.positions.positions.get(record.symbol)
        if position is None or managed.state != "open":
            return
        if managed.tp_filled == 1 and managed.intent.breakeven_after_first_tp:
            info = self.symbols(record.symbol)
            if info is None:
                return
            # İlk hedef doldu: kalan koruma iptal edilip zarar durdur girişe çekilir.
            self._spawn(self._rebuild(managed, info, position.entry_price))

    async def _rebuild(
        self, managed: ManagedPosition, info: SymbolInfo, stop: Decimal | None
    ) -> None:
        await self._cancel_protection(managed)
        await self._protect(managed, info, stop=stop)

    def has_stop(self, symbol: str) -> bool:
        """Sembolde etkin bir zarar durdur / iz süren stop emri var mı?"""
        return any(
            r.symbol == symbol and r.purpose in ("stop_loss", "trailing_stop")
            for r in self.orders.open_records()
        )

    async def reprotect(self, symbol: str) -> bool:
        """Pozisyonun koruma emirlerini (kalan hedefler ve uygun stop ile) yeniden kurar."""
        managed = self.managed.get(symbol)
        info = self.symbols(symbol)
        if managed is None or info is None or symbol not in self.positions.positions:
            return False
        if managed.state != "open":
            return False
        position = self.positions.positions[symbol]
        stop = (
            position.entry_price
            if managed.tp_filled > 0 and managed.intent.breakeven_after_first_tp
            else None
        )
        await self._rebuild(managed, info, stop)
        return True

    # --- Kapatma ------------------------------------------------------------------------

    async def close(
        self, symbol: str, *, reason: str = "kullanıcı", emergency: bool = False
    ) -> OrderRecord | None:
        managed = self.managed.get(symbol)
        position = self.positions.positions.get(symbol)
        if managed is not None:
            managed.state = "closing"
            await self._cancel_protection(managed)
        if position is None or position.quantity == 0:
            if managed is not None:
                managed.state = "closed"
            return None
        info = self.symbols(symbol)
        qty = info.quantize_qty(abs(position.quantity)) if info else abs(position.quantity)
        if qty <= 0:
            return None
        decision = managed.intent.decision_id if managed else position.decision_id
        purpose: Purpose = "emergency_close" if emergency else "exit"
        request = OrderRequest(
            client_id=make_client_id(self.mode, purpose, f"{position.id}|{reason}"),
            symbol=symbol,
            side=Side.SELL if position.quantity > 0 else Side.BUY,
            type=OrderType.MARKET,
            quantity=qty,
            reduce_only=self.market is Market.USDM_FUTURES,
            purpose=purpose,
        )
        record = await self.orders.submit(request, decision_id=decision)
        with contextlib.suppress(TimeoutError):
            record = await self.orders.wait_terminal(record.client_id, self.fill_timeout_s)
        await self.orders.ensure_fills(record)
        if managed is not None and symbol not in self.positions.positions:
            managed.state = "closed"
        return record

    async def close_all(self, *, reason: str, emergency: bool = True) -> int:
        closed = 0
        for symbol in list(self.positions.positions):
            if await self.close(symbol, reason=reason, emergency=emergency) is not None:
                closed += 1
        return closed


def _dec(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value not in (None, "") else None


def _remaining_targets(intent: TradeIntent, filled: int) -> TradeIntent:
    from dataclasses import replace

    remaining = intent.take_profits[filled:]
    total = sum((tp.fraction for tp in remaining), Decimal(0))
    scaled = tuple(TakeProfit(tp.price, tp.fraction / total) for tp in remaining) if total else ()
    return replace(intent, take_profits=scaled)
