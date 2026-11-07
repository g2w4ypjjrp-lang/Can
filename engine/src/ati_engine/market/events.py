"""Normalleştirilmiş piyasa olayları.

Spot ve Futures mesajları aynı olay türlerine çevrilir; analiz katmanı (Aşama 3+) hangi
piyasadan geldiğini ``market`` alanından okur.

Fiyat/miktar alanları burada ``float``'tır: göstergeler ve modeller sayısal hesap yapar ve
saniyede binlerce olayda ``Decimal`` gereksiz maliyet getirir. Emir fiyatları her zaman
``SymbolInfo`` ile ``Decimal`` olarak yuvarlanır (bkz. ``core.models``).

Tüketiciler idempotent olmalıdır: bağlantı yenileme anında kısa süreli tekrar eden mesajlar
gelebilir. Tekilleştirme anahtarları: işlem için ``trade_id``, mum için ``open_time_ms``,
derinlik için güncelleme kimlikleri.
"""

from __future__ import annotations

import msgspec

from ati_engine.core.events import Event, SystemEvent
from ati_engine.core.models import Market


class MarketDataEvent(Event, frozen=True, kw_only=True):
    """Yüksek hacimli piyasa verisi (yalnızca motor içi)."""

    market: Market
    event_time_ms: int


class AggTrade(MarketDataEvent, frozen=True, kw_only=True):
    symbol: str
    trade_id: int
    price: float
    qty: float
    trade_time_ms: int
    buyer_is_maker: bool  # True ise agresif taraf satıcıdır (taker SELL)
    # Bağlantı kesintisinde kaçırılıp REST ile geri alınan işlem. Bu işlemler canlı akıştan
    # sonra (sırası dışında) gelebilir; tüketiciler trade_id ile sıralamalıdır.
    recovered: bool = False

    @property
    def quote_qty(self) -> float:
        return self.price * self.qty

    @property
    def taker_side(self) -> str:
        return "SELL" if self.buyer_is_maker else "BUY"


class Kline(MarketDataEvent, frozen=True, kw_only=True):
    symbol: str
    interval: str
    open_time_ms: int
    close_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trades: int
    taker_buy_volume: float
    taker_buy_quote_volume: float
    closed: bool


class Ticker24h(msgspec.Struct, frozen=True, kw_only=True):
    symbol: str
    last: float
    open: float
    high: float
    low: float
    base_volume: float
    quote_volume: float
    event_time_ms: int

    @property
    def change_pct(self) -> float:
        return (self.last / self.open - 1.0) * 100.0 if self.open else 0.0


class TickerBatch(MarketDataEvent, frozen=True, kw_only=True):
    """Tüm sembollerin 24 saatlik özetleri (her saniye, yalnızca değişenler)."""

    tickers: list[Ticker24h]


class MarkPrice(msgspec.Struct, frozen=True, kw_only=True):
    symbol: str
    mark_price: float
    index_price: float
    funding_rate: float
    next_funding_time_ms: int


class MarkPriceBatch(MarketDataEvent, frozen=True, kw_only=True):
    items: list[MarkPrice]


class Liquidation(MarketDataEvent, frozen=True, kw_only=True):
    """Futures zorunlu tasfiye emri (Binance her sembol için saniyede en büyüğünü yayınlar)."""

    symbol: str
    side: str  # tasfiye EMRİNİN yönü: SELL = long pozisyon tasfiyesi
    price: float
    avg_price: float
    qty: float
    filled_qty: float
    status: str
    trade_time_ms: int

    @property
    def notional(self) -> float:
        return self.avg_price * self.filled_qty


class BookTicker(MarketDataEvent, frozen=True, kw_only=True):
    symbol: str
    bid: float
    bid_qty: float
    ask: float
    ask_qty: float
    update_id: int


class DepthDiff(MarketDataEvent, frozen=True, kw_only=True):
    """Emir defteri fark güncellemesi (yerel defter senkronizasyonu için)."""

    symbol: str
    first_update_id: int  # U
    final_update_id: int  # u
    prev_final_update_id: int | None  # pu (yalnızca Futures)
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]


class OrderBookTop(MarketDataEvent, frozen=True, kw_only=True):
    """Senkron yerel emir defterinin özeti (sembol başına en fazla saniyede 10 kez)."""

    symbol: str
    update_id: int
    best_bid: float
    best_ask: float
    bid_notional_10: float
    ask_notional_10: float
    imbalance_10: float  # (alış - satış) / (alış + satış), -1..1


# --- Arayüze iletilen piyasa sistem olayları ------------------------------------------------


class SymbolListed(SystemEvent, frozen=True, kw_only=True):
    """Daha önce görülmemiş bir sembol işlem görmeye başladı (yeni listeleme)."""

    market: Market
    symbol: str
    onboard_date_ms: int | None = None


class SymbolDelisted(SystemEvent, frozen=True, kw_only=True):
    market: Market
    symbol: str
    status: str


class StreamConnectionChanged(SystemEvent, frozen=True, kw_only=True):
    market: Market
    connection: str
    connected: bool
    streams: int
    reason: str = ""


class OrderBookResynced(SystemEvent, frozen=True, kw_only=True):
    market: Market
    symbol: str
    reason: str


PUBLIC_MARKET_EVENT_TYPES: tuple[type[SystemEvent], ...] = (
    SymbolListed,
    SymbolDelisted,
    StreamConnectionChanged,
    OrderBookResynced,
)
