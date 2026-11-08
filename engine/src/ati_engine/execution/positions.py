"""Pozisyon defteri: dolumlardan ortalama maliyet yöntemiyle pozisyon ve gerçekleşen kâr/zarar.

* Aynı yönde dolum pozisyonu büyütür; ortalama giriş fiyatı ağırlıklı güncellenir.
* Ters yönde dolum pozisyonu küçültür; kapanan miktar için kâr/zarar gerçekleşir. Pozisyonu
  aşan miktar ters yönde yeni pozisyon açar.
* Komisyon kote varlıkta (USDT) ise doğrudan ücret sayılır. Spot alışta komisyon baz varlıkta
  kesilirse elde edilen miktar o kadar azalır ve ücret kote değere çevrilir. Başka varlıktaki
  komisyon (ör. BNB) ayrıca kaydedilir.
* Kayıtlar ``positions`` tablosundadır (``mode`` sütunu sanal/test/gerçek kayıtları ayırır;
  sembol ve yön başına tek açık pozisyon).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from ati_engine.core.models import Market, Side, TradingMode, format_decimal
from ati_engine.storage.database import Database

ZERO = Decimal(0)


@dataclass
class Position:
    id: str
    symbol: str
    quantity: Decimal  # işaretli
    entry_price: Decimal
    opened_at: int
    realized_pnl: Decimal = ZERO
    fees: Decimal = ZERO
    funding: Decimal = ZERO
    other_fees: dict[str, Decimal] = field(default_factory=dict)
    leverage: int = 1
    decision_id: str | None = None
    direction: int = 0  # açılışta belirlenir: +1 long, -1 short

    def __post_init__(self) -> None:
        if self.direction == 0:
            self.direction = 1 if self.quantity >= 0 else -1

    @property
    def side(self) -> str:
        return "LONG" if self.direction > 0 else "SHORT"

    def unrealized(self, price: Decimal) -> Decimal:
        return (price - self.entry_price) * self.quantity


@dataclass(frozen=True)
class PositionChange:
    position: Position | None  # güncel açık pozisyon (kapandıysa None)
    realized: Decimal
    closed: Position | None = None  # bu dolumla kapanan pozisyon


class PositionBook:
    def __init__(
        self,
        db: Database,
        *,
        mode: TradingMode,
        market: Market,
        quote_asset: str = "USDT",
    ) -> None:
        self.db = db
        self.mode = mode
        self.market = market
        self.quote = quote_asset
        self.positions: dict[str, Position] = {}

    async def load(self) -> None:
        rows = await self.db.fetchall(
            "SELECT id, symbol, side, quantity, entry_price, realized_pnl, fees_paid, "
            "funding_paid, opened_at, leverage, decision_id FROM positions "
            "WHERE mode = ? AND market = ? AND status <> 'closed'",
            (self.mode.value, self.market.value),
        )
        for r in rows:
            qty = Decimal(r[3]) * (1 if r[2] == "LONG" else -1)
            self.positions[r[1]] = Position(
                id=r[0],
                symbol=r[1],
                quantity=qty,
                entry_price=Decimal(r[4]),
                realized_pnl=Decimal(r[5]),
                fees=Decimal(r[6]),
                funding=Decimal(r[7]),
                opened_at=int(r[8]),
                leverage=int(r[9]),
                decision_id=r[10],
            )

    async def apply_fill(
        self,
        *,
        symbol: str,
        base_asset: str,
        side: Side,
        qty: Decimal,
        price: Decimal,
        commission: Decimal,
        commission_asset: str,
        ts: int,
        decision_id: str | None = None,
    ) -> PositionChange:
        signed = qty if side is Side.BUY else -qty
        fee_quote = ZERO
        other: tuple[str, Decimal] | None = None
        if commission_asset == self.quote:
            fee_quote = commission
        elif commission_asset == base_asset:
            fee_quote = commission * price
            if side is Side.BUY:
                signed -= commission  # komisyon alınan miktardan kesildi
        elif commission > 0:
            other = (commission_asset, commission)

        position = self.positions.get(symbol)
        realized = ZERO
        closed: Position | None = None
        if position is None or position.quantity == 0:
            position = Position(
                id=str(uuid.uuid4()),
                symbol=symbol,
                quantity=signed,
                entry_price=price,
                opened_at=ts,
                decision_id=decision_id,
            )
            self.positions[symbol] = position
        elif (position.quantity > 0) == (signed > 0):
            total = abs(position.quantity) + abs(signed)
            position.entry_price = (
                abs(position.quantity) * position.entry_price + abs(signed) * price
            ) / total
            position.quantity += signed
        else:
            closing = min(abs(signed), abs(position.quantity))
            direction = 1 if position.quantity > 0 else -1
            realized = (price - position.entry_price) * closing * direction
            position.realized_pnl += realized
            position.quantity += signed
            if position.quantity == 0 or (position.quantity > 0) != (direction > 0):
                remainder = position.quantity
                position.quantity = ZERO
                position.fees += fee_quote
                fee_quote = ZERO
                closed = position
                await self._persist(position, closed_at=ts, reason="kapandı")
                del self.positions[symbol]
                if remainder != 0:
                    position = Position(
                        id=str(uuid.uuid4()),
                        symbol=symbol,
                        quantity=remainder,
                        entry_price=price,
                        opened_at=ts,
                        decision_id=decision_id,
                    )
                    self.positions[symbol] = position
                else:
                    return PositionChange(None, realized, closed)
        position.fees += fee_quote
        if other is not None:
            position.other_fees[other[0]] = position.other_fees.get(other[0], ZERO) + other[1]
        await self._persist(position)
        return PositionChange(position, realized, closed)

    async def add_funding(self, symbol: str, amount: Decimal) -> None:
        """Ödenen funding (pozitif) veya alınan (negatif)."""
        position = self.positions.get(symbol)
        if position is None:
            return
        position.funding += amount
        await self._persist(position)

    async def _persist(
        self, position: Position, *, closed_at: int | None = None, reason: str | None = None
    ) -> None:
        status = "closed" if closed_at is not None else "open"
        side = position.side
        await self.db.execute(
            """
            INSERT INTO positions (id, mode, market, symbol, side, status, quantity, entry_price,
                leverage, realized_pnl, fees_paid, funding_paid, decision_id, opened_at,
                closed_at, close_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                status = excluded.status,
                quantity = excluded.quantity,
                entry_price = excluded.entry_price,
                realized_pnl = excluded.realized_pnl,
                fees_paid = excluded.fees_paid,
                funding_paid = excluded.funding_paid,
                closed_at = excluded.closed_at,
                close_reason = excluded.close_reason
            """,
            (
                position.id,
                self.mode.value,
                self.market.value,
                position.symbol,
                side,
                status,
                format_decimal(abs(position.quantity)),
                format_decimal(position.entry_price),
                position.leverage,
                format_decimal(position.realized_pnl),
                format_decimal(position.fees),
                format_decimal(position.funding),
                position.decision_id,
                position.opened_at,
                closed_at,
                reason,
            ),
        )

    def now_ms(self) -> int:
        return int(time.time() * 1000)
