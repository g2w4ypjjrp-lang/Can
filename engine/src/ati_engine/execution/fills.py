"""Sanal dolum simülasyonu (paper trading).

* **Emir defteri varsa** (odak sembolleri, yerel defter senkron): piyasa emri karşı taraftaki
  seviyeleri sırayla tüketir; dolum fiyatı tüketilen seviyelerin hacim ağırlıklı ortalamasıdır.
  Büyük emir daha fazla kayma öder. Defterin görünen derinliği yetmezse kalan miktar son
  seviyenin ötesinde ek ceza ile dolar ve bu durum işaretlenir.
* **Defter yoksa:** son işlem fiyatı + 24 saatlik hacme göre tahmini yarım spread ve kayma
  (Aşama 7 maliyet modeliyle aynı kademeler).
* Komisyon alıcı (taker) oranıyla hesaplanır.

Gerçek emir değildir; gerçek borsaya hiçbir istek gönderilmez.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ati_engine.market.orderbook import OrderBook
from ati_engine.scoring.costs import CostModel, CostSettingsView

BookProvider = Callable[[str, str], OrderBook | None]  # (piyasa, sembol) → senkron defter


@dataclass(frozen=True)
class SimulatedFill:
    price: float
    qty: float
    fee: float
    source: str  # "book" | "estimate"
    levels: int  # tüketilen defter seviyesi (tahminde 0)
    slippage_bps: float  # referans fiyata göre aleyhte fark
    depth_exhausted: bool = False


class FillSimulator:
    def __init__(
        self,
        *,
        books: BookProvider | None = None,
        spot_fee: float = 0.001,
        futures_fee: float = 0.0005,
        exhausted_penalty: float = 0.002,
    ) -> None:
        self._books = books
        self._fees = {"spot": spot_fee, "usdm_futures": futures_fee}
        self._penalty = exhausted_penalty
        self._costs = CostModel(CostSettingsView())

    def round_trip_cost(self, market: str, quote_volume_24h: float | None) -> float:
        """Tahmini gidiş-dönüş maliyet (oran): iki yön komisyon + spread + kayma."""
        cost = self._costs.estimate(
            "spot", direction=1, holding_hours=0, quote_volume_24h=quote_volume_24h
        )
        fee = self._fees.get(market, 0.001)
        return 2 * fee + (cost.spread_pct + cost.slippage_pct) / 100

    def market(
        self,
        market: str,
        symbol: str,
        side: int,
        qty: float,
        *,
        reference_price: float,
        quote_volume_24h: float | None = None,
    ) -> SimulatedFill:
        """``side`` +1 alış, -1 satış. ``reference_price`` son işlem fiyatı."""
        if qty <= 0 or reference_price <= 0:
            raise ValueError("Miktar ve referans fiyat pozitif olmalı")
        fee_rate = self._fees.get(market, 0.001)
        book = self._books(market, symbol) if self._books else None
        if book is not None:
            levels = book.top_asks(50) if side > 0 else book.top_bids(50)
            if levels:
                return self._walk(levels, side, qty, reference_price, fee_rate)
        cost = self._costs.estimate(
            "spot", direction=1, holding_hours=0, quote_volume_24h=quote_volume_24h
        )
        one_way = (cost.spread_pct + cost.slippage_pct) / 2 / 100
        price = reference_price * (1 + side * one_way)
        return SimulatedFill(
            price=price,
            qty=qty,
            fee=price * qty * fee_rate,
            source="estimate",
            levels=0,
            slippage_bps=one_way * 10_000,
        )

    def _walk(
        self,
        levels: list[tuple[float, float]],
        side: int,
        qty: float,
        reference: float,
        fee_rate: float,
    ) -> SimulatedFill:
        remaining = qty
        cost = 0.0
        used = 0
        for price, available in levels:
            take = min(remaining, available)
            cost += take * price
            remaining -= take
            used += 1
            if remaining <= 1e-15:
                break
        exhausted = remaining > 1e-15
        if exhausted:
            worst = levels[-1][0] * (1 + side * self._penalty)
            cost += remaining * worst
        price = cost / qty
        slippage = side * (price / reference - 1) * 10_000
        return SimulatedFill(
            price=price,
            qty=qty,
            fee=price * qty * fee_rate,
            source="book",
            levels=used,
            slippage_bps=slippage,
            depth_exhausted=exhausted,
        )
