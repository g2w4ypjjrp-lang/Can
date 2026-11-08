"""Borsa arabirimi (venue): sanal, test ağı ve gerçek yürütücülerin ortak sözleşmesi.

Emir yöneticisi ve işlem motoru yalnızca bu arabirimi bilir; böylece sanal modda sınanan kod,
test ağında ve gerçek hesapta birebir aynı şekilde çalışır. Para ve miktar değerleri her
zaman ``Decimal``'dir.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, Protocol

from ati_engine.core.models import Market, OrderStatus, OrderType, Side, TimeInForce, TradingMode

CLIENT_ID_RE = re.compile(r"^[\.A-Z\:/a-z0-9_-]{1,36}$")  # Binance newClientOrderId kuralı
CONDITIONAL_TYPES = frozenset(
    {
        OrderType.STOP_MARKET,
        OrderType.TAKE_PROFIT_MARKET,
        OrderType.TRAILING_STOP_MARKET,
    }
)

Purpose = Literal[
    "entry", "scale_in", "take_profit", "stop_loss", "trailing_stop", "exit", "emergency_close"
]


class VenueError(Exception):
    """Borsa hatası. ``unknown`` = emrin borsaya ulaşıp ulaşmadığı bilinmiyor (zaman aşımı,
    bağlantı kopması, -1007); bu durumda yeniden göndermeden önce sorgu yapılmalıdır."""

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        retryable: bool = False,
        unknown: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.unknown = unknown


class OrderRejected(VenueError):
    """Borsa emri kesin olarak reddetti (yetersiz bakiye, filtre hatası vb.)."""


class DuplicateOrder(VenueError):
    """Aynı istemci kimliğiyle açık emir zaten var (önceki deneme ulaşmış)."""


@dataclass(frozen=True)
class OrderRequest:
    client_id: str
    symbol: str
    side: Side
    type: OrderType
    quantity: Decimal | None  # closePosition=True ise None
    price: Decimal | None = None
    trigger_price: Decimal | None = None
    time_in_force: TimeInForce | None = None
    reduce_only: bool = False
    close_position: bool = False
    callback_rate: Decimal | None = None  # iz süren stop (%)
    activation_price: Decimal | None = None
    working_type: str = "MARK_PRICE"
    purpose: Purpose = "entry"

    def __post_init__(self) -> None:
        if not CLIENT_ID_RE.match(self.client_id):
            raise ValueError(f"Geçersiz istemci emir kimliği: {self.client_id!r}")
        if self.close_position and (self.quantity is not None or self.reduce_only):
            raise ValueError("closePosition ile miktar veya reduceOnly birlikte kullanılamaz")
        if not self.close_position and (self.quantity is None or self.quantity <= 0):
            raise ValueError("Miktar pozitif olmalı")

    @property
    def is_conditional(self) -> bool:
        return self.type in CONDITIONAL_TYPES


@dataclass(frozen=True)
class OcoRequest:
    """Spot OCO: pozisyonu kapatan iki bacak (hedef + zarar durdur), biri dolunca diğeri iptal."""

    list_client_id: str
    symbol: str
    side: Side  # kapatma yönü (long için SELL)
    quantity: Decimal
    take_profit_price: Decimal
    stop_price: Decimal
    tp_client_id: str
    sl_client_id: str
    trailing_delta_bips: int | None = None


@dataclass
class ExchangeOrder:
    client_id: str
    exchange_id: str
    symbol: str
    side: Side
    type: OrderType
    status: OrderStatus
    quantity: Decimal
    executed_qty: Decimal = Decimal(0)
    avg_price: Decimal | None = None
    price: Decimal | None = None
    trigger_price: Decimal | None = None
    update_ms: int = 0
    list_id: str | None = None
    # Koşullu (algo) emir tetiklenince oluşan gerçek emrin borsa kimliği.
    actual_order_id: str | None = None


@dataclass(frozen=True)
class Fill:
    client_id: str
    exchange_order_id: str
    trade_id: str
    symbol: str
    side: Side
    price: Decimal
    qty: Decimal
    commission: Decimal
    commission_asset: str
    is_maker: bool
    ts: int
    realized_pnl: Decimal | None = None


@dataclass(frozen=True)
class Balance:
    asset: str
    free: Decimal
    locked: Decimal

    @property
    def total(self) -> Decimal:
        return self.free + self.locked


@dataclass(frozen=True)
class VenuePosition:
    symbol: str
    quantity: Decimal  # işaretli: + long, - short
    entry_price: Decimal
    leverage: int = 1
    unrealized_pnl: Decimal = Decimal(0)
    liquidation_price: Decimal | None = None


@dataclass(frozen=True)
class VenueEvent:
    kind: Literal["order", "account", "stream_expired", "stream_reconnected"]
    order: ExchangeOrder | None = None
    fill: Fill | None = None
    raw: dict[str, object] = field(default_factory=dict)


class Venue(Protocol):
    market: Market
    mode: TradingMode
    quote: str

    async def place(self, request: OrderRequest) -> ExchangeOrder: ...

    async def place_oco(self, request: OcoRequest) -> list[ExchangeOrder]: ...

    async def cancel(
        self, symbol: str, client_id: str, *, conditional: bool = False
    ) -> ExchangeOrder: ...

    async def query(
        self, symbol: str, client_id: str, *, conditional: bool = False
    ) -> ExchangeOrder | None: ...

    async def open_orders(self, symbol: str | None = None) -> list[ExchangeOrder]: ...

    async def fills(self, symbol: str, exchange_order_id: str) -> list[Fill]: ...

    async def balances(self) -> list[Balance]: ...

    async def positions(self) -> list[VenuePosition]: ...

    async def set_leverage(self, symbol: str, leverage: int) -> None: ...

    def events(self) -> AsyncIterator[VenueEvent]: ...

    async def close(self) -> None: ...
