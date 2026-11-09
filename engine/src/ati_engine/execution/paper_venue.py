"""Sanal yürütücü: borsa davranışını yerelde taklit eden eşleştirme (PAPER modu).

İşlem motorunun tamamı (giriş, zarar durdur, kademeli hedef, OCO, iz süren stop, kapatma)
gerçek borsaya hiçbir istek gönderilmeden bu yürütücüyle çalışır.

* Piyasa emri o anki fiyattan dolar; kayma ve komisyon ``FillSimulator`` ile hesaplanır.
* Limit emir fiyata ulaşıldığında limit fiyattan dolar.
* Koşullu emirler (STOP_MARKET, TAKE_PROFIT_MARKET, TRAILING_STOP_MARKET) fiyat akışıyla
  tetiklenir; ``closePosition`` mevcut pozisyonun tamamını kapatır, ``reduceOnly`` pozisyonu
  aşamaz. OCO bacaklarından biri dolunca diğeri iptal edilir.
* Bakiye denetimi: Spot'ta yetersiz bakiye, Futures'ta kaldıraç sınırını aşan pozisyon
  reddedilir (borsadaki gibi).
"""

from __future__ import annotations

import asyncio
import itertools
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal

from ati_engine.core.models import Market, OrderStatus, OrderType, Side, TradingMode
from ati_engine.execution.fills import FillSimulator
from ati_engine.execution.venue import (
    Balance,
    DuplicateOrder,
    ExchangeOrder,
    Fill,
    OcoRequest,
    OrderRejected,
    OrderRequest,
    VenueEvent,
    VenuePosition,
)

ZERO = Decimal(0)


def _d(value: float) -> Decimal:
    return Decimal(repr(value))


@dataclass
class _Resting:
    order: ExchangeOrder
    request: OrderRequest | None
    sibling: str | None = None
    extreme: Decimal | None = None
    activated: bool = False


class PaperVenue:
    mode = TradingMode.PAPER

    def __init__(
        self,
        market: Market,
        *,
        fills: FillSimulator | None = None,
        initial_quote: Decimal = Decimal(10_000),
        quote_asset: str = "USDT",
    ) -> None:
        self.market = market
        self.fills_sim = fills or FillSimulator(books=lambda m, s: None)
        self.quote = quote_asset
        self.prices: dict[str, Decimal] = {}
        self.wallet: dict[str, Decimal] = {quote_asset: initial_quote}
        self.futures_positions: dict[str, tuple[Decimal, Decimal]] = {}  # qty, giriş
        self.leverage: dict[str, int] = {}
        self._orders: dict[str, ExchangeOrder] = {}
        self._resting: dict[str, _Resting] = {}
        self._fills: dict[str, list[Fill]] = {}
        self._queue: asyncio.Queue[VenueEvent] = asyncio.Queue()
        self._ids = itertools.count(1)
        self._trades = itertools.count(1)

    # --- Yardımcılar --------------------------------------------------------------------

    def _now(self) -> int:
        return int(time.time() * 1000)

    def _base(self, symbol: str) -> str:
        return symbol.removesuffix(self.quote)

    def _position_qty(self, symbol: str) -> Decimal:
        if self.market is Market.SPOT:
            return self.wallet.get(self._base(symbol), ZERO)
        return self.futures_positions.get(symbol, (ZERO, ZERO))[0]

    async def _emit(self, order: ExchangeOrder, fill: Fill | None = None) -> None:
        await self._queue.put(VenueEvent(kind="order", order=order, fill=fill))

    async def _execute(self, order: ExchangeOrder, qty: Decimal, reference: Decimal) -> None:
        side = 1 if order.side is Side.BUY else -1
        sim = self.fills_sim.market(
            self.market.value, order.symbol, side, float(qty), reference_price=float(reference)
        )
        price, fee = _d(sim.price), _d(sim.fee)
        self._settle(order.symbol, order.side, qty, price, fee)
        order.executed_qty += qty
        order.avg_price = price
        order.status = OrderStatus.FILLED
        order.update_ms = self._now()
        fill = Fill(
            client_id=order.client_id,
            exchange_order_id=order.exchange_id,
            trade_id=f"P{next(self._trades)}",
            symbol=order.symbol,
            side=order.side,
            price=price,
            qty=qty,
            commission=fee,
            commission_asset=self.quote,
            is_maker=False,
            ts=order.update_ms,
        )
        self._fills.setdefault(order.exchange_id, []).append(fill)
        await self._emit(order, fill)

    def _settle(self, symbol: str, side: Side, qty: Decimal, price: Decimal, fee: Decimal) -> None:
        if self.market is Market.SPOT:
            base = self._base(symbol)
            sign = 1 if side is Side.BUY else -1
            self.wallet[base] = self.wallet.get(base, ZERO) + sign * qty
            self.wallet[self.quote] -= sign * qty * price + fee
            return
        current, entry = self.futures_positions.get(symbol, (ZERO, ZERO))
        signed = qty if side is Side.BUY else -qty
        realized = ZERO
        if current == 0 or (current > 0) == (signed > 0):
            total = abs(current) + qty
            entry = (abs(current) * entry + qty * price) / total
            current += signed
        else:
            closing = min(qty, abs(current))
            realized = (price - entry) * closing * (1 if current > 0 else -1)
            current += signed
            if current != 0 and (current > 0) == (signed > 0):
                entry = price  # ters yöne geçti
        self.wallet[self.quote] += realized - fee
        if current == 0:
            self.futures_positions.pop(symbol, None)
        else:
            self.futures_positions[symbol] = (current, entry)

    def _check_funds(self, request: OrderRequest, price: Decimal) -> None:
        qty = request.quantity or ZERO
        if self.market is Market.SPOT:
            if request.side is Side.BUY:
                if qty * price * Decimal("1.002") > self.wallet.get(self.quote, ZERO):
                    raise OrderRejected("Account has insufficient balance", code=-2010)
            elif qty > self.wallet.get(self._base(request.symbol), ZERO):
                raise OrderRejected("Account has insufficient balance", code=-2010)
            return
        if request.reduce_only or request.close_position:
            return
        leverage = self.leverage.get(request.symbol, 1)
        exposure = sum(
            abs(q) * self.prices.get(s, e) for s, (q, e) in self.futures_positions.items()
        )
        if exposure + qty * price > self.wallet[self.quote] * leverage:
            raise OrderRejected("Margin is insufficient", code=-2019)

    # --- Venue arabirimi ----------------------------------------------------------------

    async def place(self, request: OrderRequest) -> ExchangeOrder:
        if request.client_id in self._orders:
            raise DuplicateOrder("Duplicate order sent.", code=-2010)
        price = self.prices.get(request.symbol)
        if price is None:
            raise OrderRejected(f"{request.symbol} için fiyat yok", code=-1121)
        order = ExchangeOrder(
            client_id=request.client_id,
            exchange_id=str(next(self._ids)),
            symbol=request.symbol,
            side=request.side,
            type=request.type,
            status=OrderStatus.NEW,
            quantity=request.quantity or abs(self._position_qty(request.symbol)),
            price=request.price,
            trigger_price=request.trigger_price,
            update_ms=self._now(),
        )
        if request.type in (OrderType.MARKET, OrderType.LIMIT) and not request.reduce_only:
            self._check_funds(request, request.price or price)
        self._orders[request.client_id] = order
        if request.type is OrderType.MARKET:
            qty = self._reduce_qty(request, order.quantity)
            if qty <= 0:
                order.status = OrderStatus.EXPIRED
                await self._emit(order)
                return order
            await self._execute(order, qty, price)
            return order
        if request.type is OrderType.LIMIT and self._limit_crossed(order, price):
            await self._execute(order, order.quantity, order.price or price)
            return order
        self._resting[request.client_id] = _Resting(order, request)
        await self._emit(order)
        return order

    def _reduce_qty(self, request: OrderRequest, qty: Decimal) -> Decimal:
        if not (request.reduce_only or request.close_position):
            return qty
        position = self._position_qty(request.symbol)
        closing = (position > 0 and request.side is Side.SELL) or (
            position < 0 and request.side is Side.BUY
        )
        if not closing:
            return ZERO
        return abs(position) if request.close_position else min(qty, abs(position))

    @staticmethod
    def _limit_crossed(order: ExchangeOrder, price: Decimal) -> bool:
        if order.price is None:
            return False
        return price <= order.price if order.side is Side.BUY else price >= order.price

    async def place_oco(self, request: OcoRequest) -> list[ExchangeOrder]:
        if self.market is not Market.SPOT:
            raise OrderRejected("OCO yalnızca Spot'ta")
        if request.quantity > self.wallet.get(self._base(request.symbol), ZERO):
            raise OrderRejected("Account has insufficient balance", code=-2010)
        list_id = str(next(self._ids))
        tp = ExchangeOrder(
            client_id=request.tp_client_id,
            exchange_id=str(next(self._ids)),
            symbol=request.symbol,
            side=request.side,
            type=OrderType.LIMIT,
            status=OrderStatus.NEW,
            quantity=request.quantity,
            price=request.take_profit_price,
            update_ms=self._now(),
            list_id=list_id,
        )
        sl = ExchangeOrder(
            client_id=request.sl_client_id,
            exchange_id=str(next(self._ids)),
            symbol=request.symbol,
            side=request.side,
            type=OrderType.STOP_MARKET,
            status=OrderStatus.NEW,
            quantity=request.quantity,
            trigger_price=request.stop_price,
            update_ms=self._now(),
            list_id=list_id,
        )
        for order, sibling in ((tp, sl.client_id), (sl, tp.client_id)):
            self._orders[order.client_id] = order
            self._resting[order.client_id] = _Resting(order, None, sibling=sibling)
            await self._emit(order)
        return [tp, sl]

    async def cancel(
        self, symbol: str, client_id: str, *, conditional: bool = False
    ) -> ExchangeOrder:
        order = self._orders.get(client_id)
        if order is None:
            raise OrderRejected("Unknown order sent.", code=-2011)
        if client_id in self._resting:
            del self._resting[client_id]
            order.status = OrderStatus.CANCELED
            order.update_ms = self._now()
            await self._emit(order)
        return order

    async def query(
        self, symbol: str, client_id: str, *, conditional: bool = False
    ) -> ExchangeOrder | None:
        return self._orders.get(client_id)

    async def open_orders(self, symbol: str | None = None) -> list[ExchangeOrder]:
        return [
            r.order for r in self._resting.values() if symbol is None or r.order.symbol == symbol
        ]

    async def fills(self, symbol: str, exchange_order_id: str) -> list[Fill]:
        return list(self._fills.get(exchange_order_id, []))

    async def balances(self) -> list[Balance]:
        return [Balance(asset, amount, ZERO) for asset, amount in self.wallet.items()]

    async def price(self, symbol: str) -> Decimal | None:
        return self.prices.get(symbol)

    async def positions(self) -> list[VenuePosition]:
        return [
            VenuePosition(symbol=s, quantity=q, entry_price=e, leverage=self.leverage.get(s, 1))
            for s, (q, e) in self.futures_positions.items()
        ]

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        self.leverage[symbol] = leverage

    def events(self) -> AsyncIterator[VenueEvent]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[VenueEvent]:
        while True:
            event = await self._queue.get()
            try:
                yield event
            finally:
                # Tüketici bir sonraki olayı istediğinde önceki olayın işlenmesi bitmiştir.
                self._queue.task_done()

    async def drained(self) -> None:
        """Üretilen tüm olaylar tüketici tarafından işlenene kadar bekler (testler ve
        deterministik geri test için; sabit uyku sürelerine bağlı kalmamak adına)."""
        await self._queue.join()

    async def close(self) -> None:
        return None

    # --- Fiyat akışı ----------------------------------------------------------------------

    async def on_price(self, symbol: str, price: Decimal) -> None:
        """Yeni işlem fiyatı: limit ve koşullu emirleri denetler."""
        self.prices[symbol] = price
        for client_id, resting in list(self._resting.items()):
            order = resting.order
            if order.symbol != symbol or client_id not in self._resting:
                continue
            if not self._triggered(resting, price):
                continue
            del self._resting[client_id]
            if order.type is OrderType.LIMIT:
                await self._execute(order, order.quantity, order.price or price)
            else:
                qty = order.quantity
                if resting.request is not None:
                    qty = self._reduce_qty(resting.request, order.quantity)
                if qty <= 0:
                    order.status = OrderStatus.EXPIRED
                    await self._emit(order)
                else:
                    await self._execute(order, qty, price)
            if resting.sibling and resting.sibling in self._resting:
                await self.cancel(symbol, resting.sibling)

    @staticmethod
    def _triggered(resting: _Resting, price: Decimal) -> bool:
        order = resting.order
        sell = order.side is Side.SELL
        if order.type is OrderType.LIMIT:
            return price >= (order.price or price) if sell else price <= (order.price or price)
        if order.type is OrderType.STOP_MARKET:
            trigger = order.trigger_price or ZERO
            return price <= trigger if sell else price >= trigger
        if order.type is OrderType.TAKE_PROFIT_MARKET:
            trigger = order.trigger_price or ZERO
            return price >= trigger if sell else price <= trigger
        if order.type is OrderType.TRAILING_STOP_MARKET and resting.request is not None:
            request = resting.request
            rate = (request.callback_rate or ZERO) / 100
            activation = request.activation_price
            if not resting.activated:
                if activation is None or (price >= activation if sell else price <= activation):
                    resting.activated = True
                    resting.extreme = price
                return False
            extreme = resting.extreme or price
            extreme = max(extreme, price) if sell else min(extreme, price)
            resting.extreme = extreme
            return price <= extreme * (1 - rate) if sell else price >= extreme * (1 + rate)
        return False
