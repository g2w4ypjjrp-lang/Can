"""Sanal hesap (Sanal mod): botun ve elle işlemin borsaya hiç emir göndermeden, canlı Binance
fiyatlarıyla çalıştığı yürütücü.

* Fiyatlar piyasa verisi akışından gelir (``PriceTick``; en çok 0,1 sn'de bir). Henüz fiyat
  gelmemiş sembolde güncel fiyat ekrandaki son fiyattan alınır (risk kapısı emirden önce fiyatı
  sorar; böylece emir anında fiyat hazırdır).
* Zarar durdur, hedef ve iz süren stop her fiyat değişiminde denetlenir (``PaperVenue``).
* Sembol kuralları (fiyat/miktar adımı, en küçük emir) Binance'in herkese açık exchangeInfo
  verisinden, piyasa verisi servisiyle aynı kaynaktan okunur.
* Sanal bakiye bellektedir: motor yeniden başlayınca sanal hesap baştan başlar.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from decimal import Decimal

from ati_engine.core.models import Market, SymbolInfo
from ati_engine.execution.fills import FillSimulator
from ati_engine.execution.paper_venue import PaperVenue

PriceSource = Callable[[Market, str], float | None]


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
