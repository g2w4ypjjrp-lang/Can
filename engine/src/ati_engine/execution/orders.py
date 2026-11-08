"""Emir yöneticisi: idempotent gönderim, durum takibi, kısmi dolumlar ve yeniden başlatma.

**İdempotentlik (çift emir yok):**

* Her emrin istemci kimliği (``clientOrderId``) karardan **belirleyici** olarak türetilir; aynı
  karar aynı kimliği üretir.
* Gönderim sırasında zaman aşımı / bağlantı kopması / "durum bilinmiyor" (-1007) olursa emir
  yeniden gönderilmeden önce **kimlikle sorgulanır**: borsada varsa o kabul edilir, yoksa
  aynı kimlikle yeniden gönderilir. Borsa aynı kimliği ikinci kez kabul etmez.
* Denemeler tükenirse emir ``PENDING_NEW`` olarak işaretli kalır; mutabakat döngüsü çözer.

**Dolumlar:** işlem kimliğiyle tekilleştirilir (aynı dolum iki kez sayılmaz). Koşullu (algo)
emir tetiklenince oluşan gerçek emrin dolumları, gerçek emir kimliği üzerinden koruma emrine
bağlanır; bağlantı dolumdan sonra gelirse dolum bekletilip sonra işlenir.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal

from ati_engine.core.models import (
    Market,
    OrderStatus,
    OrderType,
    Side,
    TradingMode,
    format_decimal,
)
from ati_engine.execution.approval import (
    ENTRY_PURPOSES,
    ApprovalError,
    ApprovalVerifier,
    RiskApproval,
    check_risk_reducing,
)
from ati_engine.execution.venue import (
    CONDITIONAL_TYPES,
    DuplicateOrder,
    ExchangeOrder,
    Fill,
    OcoRequest,
    OrderRejected,
    OrderRequest,
    Venue,
    VenueError,
    VenueEvent,
)
from ati_engine.storage.database import Database

logger = logging.getLogger(__name__)

PURPOSE_CODES = {
    "entry": "en",
    "scale_in": "si",
    "take_profit": "tp",
    "stop_loss": "sl",
    "trailing_stop": "ts",
    "exit": "ex",
    "emergency_close": "ec",
}


def make_client_id(mode: TradingMode, purpose: str, key: str, leg: int = 0) -> str:
    """Belirleyici istemci kimliği: ``ati`` + mod + amaç + karar özeti + bacak (≤ 36 karakter,
    Binance deseni ``^[.A-Z:/a-z0-9_-]{1,36}$``)."""
    digest = hashlib.sha256(f"{mode.value}|{purpose}|{key}".encode()).hexdigest()[:24]
    return f"ati{mode.value[0]}{PURPOSE_CODES[purpose]}{digest}{leg:02d}"


@dataclass
class OrderRecord:
    client_id: str
    market: Market
    symbol: str
    side: Side
    type: OrderType
    purpose: str
    quantity: Decimal | None
    price: Decimal | None
    trigger_price: Decimal | None
    reduce_only: bool
    decision_id: str | None
    status: OrderStatus = OrderStatus.PENDING_NEW
    exchange_id: str | None = None
    actual_order_id: str | None = None
    list_id: str | None = None
    executed_qty: Decimal = Decimal(0)
    avg_price: Decimal | None = None
    last_error: str | None = None
    created_ms: int = 0

    @property
    def conditional(self) -> bool:
        return self.type in CONDITIONAL_TYPES

    @property
    def unresolved(self) -> bool:
        """Gönderim sonucu bilinmiyor (mutabakat gerekir)."""
        return self.status is OrderStatus.PENDING_NEW and self.last_error is not None


FillCallback = Callable[[OrderRecord, Fill], Awaitable[None]]
OrderCallback = Callable[[OrderRecord], Awaitable[None]]


class OrderManager:
    def __init__(
        self,
        db: Database,
        venue: Venue,
        *,
        verifier: ApprovalVerifier,
        max_attempts: int = 3,
        backoff_s: float = 0.5,
        on_fill: FillCallback | None = None,
        on_terminal: OrderCallback | None = None,
    ) -> None:
        self.db = db
        self.venue = venue
        self.verifier = verifier
        self.mode = venue.mode
        self.market = venue.market
        self.max_attempts = max_attempts
        self.backoff_s = backoff_s
        self.on_fill = on_fill
        self.on_terminal = on_terminal
        self.records: dict[str, OrderRecord] = {}
        self._by_exchange: dict[str, str] = {}
        self._orphans: dict[str, list[Fill]] = {}
        self._waiters: dict[str, list[asyncio.Future[OrderRecord]]] = {}
        self.applied_qty: dict[str, Decimal] = {}  # emir başına işlenmiş dolum miktarı
        self.stats = {"submitted": 0, "rejected": 0, "unknown": 0, "dup_fills": 0, "retries": 0}

    # --- Kalıcılık ------------------------------------------------------------------------

    async def _insert(self, record: OrderRecord) -> None:
        now = int(time.time() * 1000)
        await self.db.execute(
            """
            INSERT OR IGNORE INTO orders (id, mode, market, symbol, side, type, time_in_force,
                quantity, price, stop_price, reduce_only, status, filled_qty, decision_id,
                purpose, created_at, updated_at, list_id)
            VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, '0', ?, ?, ?, ?, ?)
            """,
            (
                record.client_id,
                self.mode.value,
                self.market.value,
                record.symbol,
                record.side.value,
                record.type.value,
                format_decimal(record.quantity) if record.quantity is not None else "0",
                format_decimal(record.price) if record.price is not None else None,
                format_decimal(record.trigger_price) if record.trigger_price is not None else None,
                int(record.reduce_only),
                record.status.value,
                record.decision_id,
                record.purpose,
                now,
                now,
                record.list_id,
            ),
        )

    async def _save(self, record: OrderRecord) -> None:
        await self.db.execute(
            """
            UPDATE orders SET status = ?, exchange_order_id = ?, filled_qty = ?,
                avg_fill_price = ?, updated_at = ?, last_error = ?, actual_order_id = ?,
                list_id = ?
            WHERE id = ?
            """,
            (
                record.status.value,
                record.exchange_id,
                format_decimal(record.executed_qty),
                format_decimal(record.avg_price) if record.avg_price is not None else None,
                int(time.time() * 1000),
                record.last_error,
                record.actual_order_id,
                record.list_id,
                record.client_id,
            ),
        )

    async def load_open(self) -> list[OrderRecord]:
        """Yeniden başlatmada sonuçlanmamış emirleri yükler (mutabakat bunları doğrular)."""
        rows = await self.db.fetchall(
            "SELECT id, symbol, side, type, purpose, quantity, price, stop_price, reduce_only, "
            "decision_id, status, exchange_order_id, filled_qty, avg_fill_price, last_error, "
            "actual_order_id, list_id, created_at FROM orders "
            "WHERE mode = ? AND market = ? AND status IN ('PENDING_NEW', 'NEW', "
            "'PARTIALLY_FILLED')",
            (self.mode.value, self.market.value),
        )
        loaded = []
        for r in rows:
            record = OrderRecord(
                client_id=r[0],
                market=self.market,
                symbol=r[1],
                side=Side(r[2]),
                type=OrderType(r[3]),
                purpose=r[4],
                quantity=Decimal(r[5]) if r[5] not in (None, "0") else None,
                price=Decimal(r[6]) if r[6] is not None else None,
                trigger_price=Decimal(r[7]) if r[7] is not None else None,
                reduce_only=bool(r[8]),
                decision_id=r[9],
                status=OrderStatus(r[10]),
                exchange_id=r[11],
                executed_qty=Decimal(r[12]),
                avg_price=Decimal(r[13]) if r[13] is not None else None,
                last_error=r[14],
                actual_order_id=r[15],
                list_id=r[16],
                created_ms=int(r[17]),
            )
            self._remember(record)
            loaded.append(record)
        return loaded

    def _remember(self, record: OrderRecord) -> None:
        self.records[record.client_id] = record
        if record.exchange_id:
            self._by_exchange[record.exchange_id] = record.client_id
        if record.actual_order_id:
            self._by_exchange[record.actual_order_id] = record.client_id

    # --- Gönderim -------------------------------------------------------------------------

    async def submit(
        self,
        request: OrderRequest,
        *,
        decision_id: str | None = None,
        approval: RiskApproval | None = None,
    ) -> OrderRecord:
        # Tek kapı: giriş emri risk kapısının onayı olmadan, diğer emirler riski artıracak
        # biçimde gönderilemez (``ApprovalError``).
        if request.purpose in ENTRY_PURPOSES:
            self.verifier.verify(approval, request, mode=self.mode, market=self.market)
        else:
            check_risk_reducing(request, self.market)
        existing = self.records.get(request.client_id)
        if existing is not None and existing.status is not OrderStatus.PENDING_NEW:
            return existing  # aynı karar ikinci kez gönderilmez
        record = existing or OrderRecord(
            client_id=request.client_id,
            market=self.market,
            symbol=request.symbol,
            side=request.side,
            type=request.type,
            purpose=request.purpose,
            quantity=request.quantity,
            price=request.price,
            trigger_price=request.trigger_price or request.activation_price,
            reduce_only=request.reduce_only or request.close_position,
            decision_id=decision_id,
            created_ms=int(time.time() * 1000),
        )
        self._remember(record)
        await self._insert(record)
        self.stats["submitted"] += 1
        for attempt in range(self.max_attempts):
            try:
                order = await self.venue.place(request)
            except OrderRejected as exc:
                record.status = OrderStatus.REJECTED
                record.last_error = f"{exc.code}: {exc}"[:300]
                self.stats["rejected"] += 1
                await self._save(record)
                await self._finish(record)
                return record
            except DuplicateOrder:
                found = await self._query(request)
                if found is not None:
                    await self.apply_order(found)
                    return record
                continue
            except VenueError as exc:
                if not (exc.unknown or exc.retryable):
                    record.status = OrderStatus.REJECTED
                    record.last_error = f"{exc.code}: {exc}"[:300]
                    self.stats["rejected"] += 1
                    await self._save(record)
                    await self._finish(record)
                    return record
                record.last_error = f"durum bilinmiyor: {exc}"[:300]
                # Yeniden göndermeden önce: emir borsaya ulaştı mı?
                found = await self._query(request)
                if found is not None:
                    record.last_error = None
                    await self.apply_order(found)
                    return record
                self.stats["retries"] += 1
                await asyncio.sleep(self.backoff_s * (2**attempt))
                continue
            record.last_error = None
            await self.apply_order(order)
            return record
        # Denemeler tükendi: emir durumu bilinmiyor; mutabakat sonuçlandıracak.
        self.stats["unknown"] += 1
        record.last_error = record.last_error or "gönderim sonucu bilinmiyor"
        await self._save(record)
        logger.warning(
            "Emir durumu bilinmiyor; mutabakat bekleniyor",
            extra={"client_id": record.client_id, "symbol": record.symbol},
        )
        return record

    async def _query(self, request: OrderRequest) -> ExchangeOrder | None:
        try:
            return await self.venue.query(
                request.symbol, request.client_id, conditional=request.is_conditional
            )
        except VenueError:
            return None

    async def submit_oco(
        self, request: OcoRequest, *, decision_id: str | None = None
    ) -> list[OrderRecord]:
        if request.side is not Side.SELL or self.market is not Market.SPOT:
            raise ApprovalError("OCO yalnızca Spot'ta pozisyon kapatan satış olabilir")
        records = []
        for client_id, otype, price, trigger in (
            (request.tp_client_id, OrderType.LIMIT, request.take_profit_price, None),
            (request.sl_client_id, OrderType.STOP_MARKET, None, request.stop_price),
        ):
            purpose = "take_profit" if client_id == request.tp_client_id else "stop_loss"
            record = self.records.get(client_id) or OrderRecord(
                client_id=client_id,
                market=self.market,
                symbol=request.symbol,
                side=request.side,
                type=otype,
                purpose=purpose,
                quantity=request.quantity,
                price=price,
                trigger_price=trigger,
                reduce_only=True,
                decision_id=decision_id,
                list_id=request.list_client_id,
                created_ms=int(time.time() * 1000),
            )
            self._remember(record)
            await self._insert(record)
            records.append(record)
        try:
            orders = await self.venue.place_oco(request)
        except OrderRejected as exc:
            for record in records:
                record.status = OrderStatus.REJECTED
                record.last_error = f"{exc.code}: {exc}"[:300]
                await self._save(record)
                await self._finish(record)
            return records
        except VenueError as exc:
            for record in records:
                record.last_error = f"durum bilinmiyor: {exc}"[:300]
                await self._save(record)
            return records
        for order in orders:
            await self.apply_order(order)
        return records

    async def cancel(self, client_id: str) -> OrderRecord | None:
        record = self.records.get(client_id)
        if record is None or record.status.is_terminal:
            return record
        try:
            order = await self.venue.cancel(
                record.symbol, client_id, conditional=record.conditional
            )
        except VenueError as exc:
            # Zaten dolmuş/iptal edilmiş olabilir: borsadaki gerçek durumu al.
            found = await self.venue.query(record.symbol, client_id, conditional=record.conditional)
            if found is None:
                record.last_error = f"iptal edilemedi: {exc}"[:300]
                await self._save(record)
                return record
            order = found
        await self.apply_order(order)
        return record

    # --- Güncellemeler ------------------------------------------------------------------

    async def apply_order(self, order: ExchangeOrder) -> OrderRecord | None:
        record = self.records.get(order.client_id)
        if record is None:
            return None  # bu motorun emri değil
        previous = record.status
        record.status = order.status
        record.exchange_id = order.exchange_id or record.exchange_id
        if order.actual_order_id:
            record.actual_order_id = order.actual_order_id
        if order.list_id:
            record.list_id = order.list_id
        if order.executed_qty > record.executed_qty:
            record.executed_qty = order.executed_qty
        if order.avg_price:
            record.avg_price = order.avg_price
        record.last_error = (
            None if order.status is not OrderStatus.PENDING_NEW else record.last_error
        )
        self._remember(record)
        await self._save(record)
        # Bağlantı dolumdan sonra geldiyse bekleyen dolumları işle.
        for key in (record.exchange_id, record.actual_order_id):
            if key and key in self._orphans:
                for fill in self._orphans.pop(key):
                    await self.apply_fill(fill)
        if record.status.is_terminal and not previous.is_terminal:
            await self._finish(record)
        return record

    async def mark(self, record: OrderRecord, status: OrderStatus, error: str) -> None:
        """Borsada karşılığı olmayan kaydı (mutabakat kararıyla) kapatır."""
        previous = record.status
        record.status = status
        record.last_error = error[:300]
        self._remember(record)
        await self._save(record)
        if status.is_terminal and not previous.is_terminal:
            await self._finish(record)

    async def apply_fill(self, fill: Fill) -> bool:
        """Dolumu işler; daha önce işlenmişse ``False`` döner."""
        client_id = fill.client_id if fill.client_id in self.records else None
        if client_id is None:
            client_id = self._by_exchange.get(fill.exchange_order_id)
        if client_id is None:
            self._orphans.setdefault(fill.exchange_order_id, []).append(fill)
            return False
        record = self.records[client_id]
        inserted = await self.db.execute(
            """
            INSERT OR IGNORE INTO fills (order_id, mode, market, symbol, trade_id, price,
                quantity, commission, commission_asset, is_maker, realized_pnl, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client_id,
                self.mode.value,
                self.market.value,
                fill.symbol,
                fill.trade_id,
                format_decimal(fill.price),
                format_decimal(fill.qty),
                format_decimal(fill.commission),
                fill.commission_asset,
                int(fill.is_maker),
                format_decimal(fill.realized_pnl) if fill.realized_pnl is not None else None,
                fill.ts,
            ),
        )
        if not inserted:
            self.stats["dup_fills"] += 1
            return False
        self.applied_qty[client_id] = self.applied_qty.get(client_id, Decimal(0)) + fill.qty
        if self.on_fill is not None:
            await self.on_fill(record, fill)
        return True

    async def handle_event(self, event: VenueEvent) -> None:
        if event.order is not None:
            await self.apply_order(event.order)
        if event.fill is not None:
            await self.apply_fill(event.fill)

    # --- Bekleme ------------------------------------------------------------------------

    async def _finish(self, record: OrderRecord) -> None:
        for future in self._waiters.pop(record.client_id, []):
            if not future.done():
                future.set_result(record)
        if self.on_terminal is not None:
            await self.on_terminal(record)

    async def wait_terminal(self, client_id: str, within_s: float) -> OrderRecord:
        """Emir sonuçlanana kadar bekler; süre dolarsa ``TimeoutError``."""
        record = self.records[client_id]
        if record.status.is_terminal:
            return record
        future: asyncio.Future[OrderRecord] = asyncio.get_running_loop().create_future()
        self._waiters.setdefault(client_id, []).append(future)
        async with asyncio.timeout(within_s):
            return await future

    async def ensure_fills(self, record: OrderRecord, within_s: float = 2.0) -> None:
        """Emrin gerçekleşen miktarı kadar dolumun işlendiğinden emin olur. Kullanıcı akışı
        gecikirse veya koptuysa dolumlar borsadan REST ile alınır (tekilleştirme çift sayımı
        önler)."""
        target = record.executed_qty
        if target <= 0:
            return
        deadline = asyncio.get_running_loop().time() + within_s
        while self.applied_qty.get(record.client_id, Decimal(0)) < target:
            if asyncio.get_running_loop().time() >= deadline:
                break
            await asyncio.sleep(0.02)
        if self.applied_qty.get(record.client_id, Decimal(0)) >= target:
            return
        exchange_id = record.actual_order_id or record.exchange_id
        if not exchange_id:
            return
        try:
            fills = await self.venue.fills(record.symbol, exchange_id)
        except VenueError as exc:
            logger.warning("Dolumlar alınamadı", extra={"error": str(exc)})
            return
        for fill in fills:
            await self.apply_fill(
                Fill(
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
            )

    def open_records(self) -> list[OrderRecord]:
        return [r for r in self.records.values() if not r.status.is_terminal]
