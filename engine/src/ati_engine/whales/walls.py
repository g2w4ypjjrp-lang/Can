"""Emir defteri duvarları: ortaya çıkma, çekilme ve eritilme.

Odak sembollerinin yerel emir defterlerinde, çevresindeki kademelerin medyanından çok daha
büyük ve yeterli tutardaki seviyeler "duvar" sayılır. Bir duvar en az birkaç saniye kalırsa
"ortaya çıktı" olarak kaydedilir (anlık titreşimler yok sayılır). Duvar kaybolduğunda:

* Fiyat duvarın ötesine geçtiyse (alış duvarında en iyi alış duvarın altına indiyse) duvar
  işlemle **eritilmiştir**.
* Fiyat duvara ulaşmadan kaybolduysa duvar **çekilmiştir** (iptal). Bu, piyasayı yanıltmaya
  yönelik sahte emir (spoofing) belirtisi olabilir; tek başına kanıt değildir.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from ati_engine.core.models import Market
from ati_engine.market.orderbook import OrderBook


@dataclass
class Wall:
    side: str  # "bid" | "ask"
    price: float
    notional: float
    peak_notional: float
    first_seen_ms: int
    last_seen_ms: int
    announced: bool = False


@dataclass(frozen=True)
class WallChange:
    kind: str  # "appeared" | "pulled" | "eaten"
    market: Market
    symbol: str
    side: str
    price: float
    notional: float  # duvarın ulaştığı en yüksek tutar
    lifetime_s: float
    distance_pct: float  # duvarın orta fiyata uzaklığı


class WallTracker:
    def __init__(
        self,
        *,
        levels: int = 50,
        multiple: float = 8.0,
        min_notional: float = 250_000,
        max_distance_pct: float = 2.0,
        min_lifetime_s: float = 5.0,
        shrink_ratio: float = 0.3,
    ) -> None:
        self._levels = levels
        self._multiple = multiple
        self._min_notional = min_notional
        self._max_distance = max_distance_pct
        self._min_lifetime_ms = int(min_lifetime_s * 1000)
        self._shrink = shrink_ratio
        self._walls: dict[tuple[Market, str], dict[tuple[str, float], Wall]] = {}

    def walls(self, market: Market, symbol: str) -> list[Wall]:
        return list(self._walls.get((market, symbol), {}).values())

    def _candidates(
        self, side: str, levels: list[tuple[float, float]], mid: float
    ) -> dict[tuple[str, float], float]:
        if len(levels) < 5:
            return {}
        notionals = [p * q for p, q in levels]
        floor = max(self._multiple * statistics.median(notionals), self._min_notional)
        found: dict[tuple[str, float], float] = {}
        for (price, _), notional in zip(levels, notionals, strict=True):
            if notional >= floor and abs(price / mid - 1) * 100 <= self._max_distance:
                found[(side, price)] = notional
        return found

    def scan(self, market: Market, symbol: str, book: OrderBook, now_ms: int) -> list[WallChange]:
        best_bid, best_ask = book.best_bid(), book.best_ask()
        if best_bid is None or best_ask is None:
            return []
        mid = (best_bid[0] + best_ask[0]) / 2
        candidates = self._candidates("bid", book.top_bids(self._levels), mid)
        candidates.update(self._candidates("ask", book.top_asks(self._levels), mid))
        tracked = self._walls.setdefault((market, symbol), {})
        changes: list[WallChange] = []

        for key, notional in candidates.items():
            wall = tracked.get(key)
            if wall is None:
                tracked[key] = Wall(
                    side=key[0],
                    price=key[1],
                    notional=notional,
                    peak_notional=notional,
                    first_seen_ms=now_ms,
                    last_seen_ms=now_ms,
                )
            else:
                wall.notional = notional
                wall.peak_notional = max(wall.peak_notional, notional)
                wall.last_seen_ms = now_ms

        for key, wall in list(tracked.items()):
            if key in candidates:
                continue
            side_book = book.bids if wall.side == "bid" else book.asks
            remaining = side_book.get(wall.price, 0.0) * wall.price
            if remaining >= self._shrink * wall.peak_notional:
                wall.notional = remaining  # hâlâ büyük; yalnızca eşik (medyan) değişti
                wall.last_seen_ms = now_ms
                continue
            del tracked[key]
            if not wall.announced:
                continue  # kısa ömürlü titreşim: kayda değer değil
            crossed = best_bid[0] < wall.price if wall.side == "bid" else best_ask[0] > wall.price
            changes.append(
                WallChange(
                    kind="eaten" if crossed else "pulled",
                    market=market,
                    symbol=symbol,
                    side=wall.side,
                    price=wall.price,
                    notional=wall.peak_notional,
                    lifetime_s=(now_ms - wall.first_seen_ms) / 1000,
                    distance_pct=abs(wall.price / mid - 1) * 100,
                )
            )

        for wall in tracked.values():
            if not wall.announced and now_ms - wall.first_seen_ms >= self._min_lifetime_ms:
                wall.announced = True
                changes.append(
                    WallChange(
                        kind="appeared",
                        market=market,
                        symbol=symbol,
                        side=wall.side,
                        price=wall.price,
                        notional=wall.peak_notional,
                        lifetime_s=(now_ms - wall.first_seen_ms) / 1000,
                        distance_pct=abs(wall.price / mid - 1) * 100,
                    )
                )
        return changes

    def forget(self, market: Market, symbol: str) -> None:
        self._walls.pop((market, symbol), None)
