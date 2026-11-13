"""Sanal hesap (Sanal mod): botun ve elle işlemin borsaya hiç emir göndermeden, canlı Binance
fiyatlarıyla çalıştığı yürütücü.

* Fiyatlar piyasa verisi akışından gelir (``PriceTick``; en çok 0,1 sn'de bir). Henüz fiyat
  gelmemiş sembolde güncel fiyat ekrandaki son fiyattan alınır (risk kapısı emirden önce fiyatı
  sorar; böylece emir anında fiyat hazırdır).
* Zarar durdur, hedef ve iz süren stop her fiyat değişiminde denetlenir (``PaperVenue``).
* Sembol kuralları (fiyat/miktar adımı, en küçük emir) Binance'in herkese açık exchangeInfo
  verisinden, piyasa verisi servisiyle aynı kaynaktan okunur.
* Sanal hesap kalıcıdır: bakiye, pozisyonlar ve bekleyen stop / hedef emirleri birkaç saniyede
  bir veritabanına yazılır, motor yeniden başlayınca kaldığı yerden sürer. Ayarlar'dan sıfırlanır.
"""

from __future__ import annotations

import itertools
import types
import typing
from collections.abc import Callable, Iterator, Mapping
from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from ati_engine.core.models import Market, SymbolInfo
from ati_engine.execution.fills import FillSimulator
from ati_engine.execution.paper_venue import PaperVenue, _Resting
from ati_engine.execution.venue import ExchangeOrder, Fill, OrderRequest

PriceSource = Callable[[Market, str], float | None]


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return value


def to_dict(obj: Any) -> dict[str, Any]:
    """Veri sınıfı → JSON'a yazılabilir sözlük (Decimal metin, Enum değer)."""
    if not is_dataclass(obj):
        raise TypeError("veri sınıfı bekleniyordu")
    return {f.name: _plain(getattr(obj, f.name)) for f in fields(obj)}


def _convert(hint: Any, value: Any) -> Any:
    if value is None:
        return None
    options = (
        typing.get_args(hint)
        if typing.get_origin(hint) in (typing.Union, types.UnionType)
        else (hint,)
    )
    for option in options:
        if option is Decimal:
            return Decimal(str(value))
        if isinstance(option, type) and issubclass(option, Enum):
            return option(value)
    return value


def from_dict[T](cls: type[T], data: Mapping[str, Any]) -> T:
    hints = typing.get_type_hints(cls)
    names = {f.name for f in fields(cls)}  # type: ignore[arg-type]
    return cls(**{k: _convert(hints[k], v) for k, v in data.items() if k in names})


class LivePaperVenue(PaperVenue):
    def __init__(
        self,
        market: Market,
        *,
        price_source: PriceSource,
        initial_quote: Decimal,
        quote_asset: str = "USDT",
        fills: FillSimulator | None = None,
    ) -> None:
        super().__init__(market, fills=fills, initial_quote=initial_quote, quote_asset=quote_asset)
        self._source = price_source
        self.stream_connected = True
        # Kaydedilmemiş değişiklik var mı (emir, dolum, bakiye): kalıcı kayıt bunu izler.
        self.dirty = False

    async def _emit(self, order: ExchangeOrder, fill: Fill | None = None) -> None:
        self.dirty = True
        await super()._emit(order, fill)

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        self.dirty = True
        await super().set_leverage(symbol, leverage)

    # --- Kalıcılık ------------------------------------------------------------------------

    def snapshot(self, *, keep_orders: int = 300) -> dict[str, Any]:
        """Bakiye, pozisyonlar, bekleyen emirler ve son emirler (sıfırlamadan sonra da geçerli)."""
        resting_ids = set(self._resting)
        recent = sorted(self._orders.values(), key=lambda o: o.update_ms)[-keep_orders:]
        kept = {o.client_id: o for o in recent} | {c: self._orders[c] for c in resting_ids}
        return {
            "version": 1,
            "wallet": {k: str(v) for k, v in self.wallet.items()},
            "positions": {
                s: [str(q), str(e)] for s, (q, e) in self.futures_positions.items() if q != 0
            },
            "leverage": dict(self.leverage),
            "orders": [to_dict(o) for o in kept.values()],
            "resting": [
                {
                    "client_id": cid,
                    "request": to_dict(r.request) if r.request is not None else None,
                    "sibling": r.sibling,
                    "extreme": str(r.extreme) if r.extreme is not None else None,
                    "activated": r.activated,
                }
                for cid, r in self._resting.items()
            ],
            "fills": {
                o.exchange_id: [to_dict(f) for f in self._fills.get(o.exchange_id, [])]
                for o in kept.values()
                if o.exchange_id in self._fills
            },
        }

    def restore(self, data: Mapping[str, Any]) -> None:
        self.wallet = {k: Decimal(v) for k, v in data.get("wallet", {}).items()}
        self.futures_positions = {
            s: (Decimal(q), Decimal(e)) for s, (q, e) in data.get("positions", {}).items()
        }
        self.leverage = {k: int(v) for k, v in data.get("leverage", {}).items()}
        self._orders = {o["client_id"]: from_dict(ExchangeOrder, o) for o in data.get("orders", [])}
        self._resting = {}
        for item in data.get("resting", []):
            order = self._orders.get(item["client_id"])
            if order is None:
                continue
            request = item.get("request")
            self._resting[item["client_id"]] = _Resting(
                order,
                from_dict(OrderRequest, request) if request else None,
                sibling=item.get("sibling"),
                extreme=Decimal(item["extreme"]) if item.get("extreme") is not None else None,
                activated=bool(item.get("activated")),
            )
        self._fills = {k: [from_dict(Fill, f) for f in v] for k, v in data.get("fills", {}).items()}
        numeric = [int(o.exchange_id) for o in self._orders.values() if o.exchange_id.isdigit()]
        self._ids = itertools.count(max(numeric, default=0) + 1)
        trades = [
            int(f.trade_id[1:])
            for fills in self._fills.values()
            for f in fills
            if f.trade_id[1:].isdigit()
        ]
        self._trades = itertools.count(max(trades, default=0) + 1)
        self.dirty = False

    def reset(self, balance: Decimal) -> None:
        """Sanal hesabı başlangıç bakiyesine döndürür (pozisyon ve emirler silinir)."""
        self.wallet = {self.quote: balance}
        self.futures_positions = {}
        self.leverage = {}
        self._orders = {}
        self._resting = {}
        self._fills = {}
        self.dirty = True

    def _seed(self, symbol: str) -> Decimal | None:
        price = self.prices.get(symbol)
        if price is None:
            value = self._source(self.market, symbol)
            if value is not None and value > 0:
                price = Decimal(repr(value))
                self.prices[symbol] = price
        return price

    async def price(self, symbol: str) -> Decimal | None:
        return self._seed(symbol)

    def watched(self) -> set[str]:
        """Fiyatı izlenmesi gereken semboller: bekleyen emri ya da açık pozisyonu olanlar."""
        symbols = {r.order.symbol for r in self._resting.values()}
        symbols.update(s for s, (q, _) in self.futures_positions.items() if q != 0)
        return symbols

    async def feed(self, prices: Mapping[str, float]) -> None:
        """Değişen fiyatlar: hepsi kaydedilir; emri/pozisyonu olanlarda tetikler denetlenir."""
        watched = self.watched()
        for symbol, value in prices.items():
            if value <= 0:
                continue
            price = Decimal(repr(value))
            if symbol in watched:
                await self.on_price(symbol, price)
            else:
                self.prices[symbol] = price


class LiveSymbols(Mapping[str, SymbolInfo]):
    """Piyasa verisi servisinin güncel sembol kurallarına canlı görünüm (açılışta boş olabilir;
    exchangeInfo gelince dolar)."""

    def __init__(self, source: Callable[[], Mapping[str, SymbolInfo]]) -> None:
        self._source = source

    def __getitem__(self, key: str) -> SymbolInfo:
        return self._source()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._source())

    def __len__(self) -> int:
        return len(self._source())
