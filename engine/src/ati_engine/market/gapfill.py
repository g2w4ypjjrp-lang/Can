"""İşlem (aggTrade) akışında boşluk tespiti ve REST ile geri doldurma.

Binance her sembolün birleşik işlemlerine ardışık bir kimlik (``a``) verir. WebSocket kopup
yeniden bağlanırken geçen sürede gelen işlemler akışta bir daha gönderilmez. Bu modül:

* Her sembolün son işlem kimliğini izler.
* Kimlikte atlama görürse eksik aralığı ``GET aggTrades?fromId=`` ile geri alır ve
  ``recovered=True`` işaretli olaylar olarak yayımlar. İstekler düşük öncelikle gönderilir;
  limite yaklaşıldığında canlı işlemlerin (emir, anlık görüntü) önüne geçmez.
* Aynı kimliği ikinci kez görürse (bağlantı yenileme anındaki örtüşme) olayı eler.

Çok uzun kesintilerde (``max_trades_per_gap`` üstü) yalnızca en yeni kısım geri alınır; daha
eskisi tarihsel veri motorunun (Aşama 5) toplu arşivlerinden tamamlanır.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ati_engine.core.models import Market
from ati_engine.exchange.endpoints import MarketEndpoints
from ati_engine.exchange.rate_limit import Priority
from ati_engine.exchange.rest import BinanceRestClient
from ati_engine.market.events import AggTrade

logger = logging.getLogger(__name__)


@dataclass
class GapStats:
    detected: int = 0
    recovered_trades: int = 0
    unrecovered_gaps: int = 0
    unrecovered_trades: int = 0
    duplicates: int = 0
    pending: int = 0


class TradeGapFiller:
    def __init__(
        self,
        *,
        market: Market,
        endpoints: MarketEndpoints,
        rest: BinanceRestClient,
        publish: Callable[[AggTrade], Awaitable[None]],
        max_trades_per_gap: int = 5_000,
        page_size: int = 1_000,
    ) -> None:
        self.market = market
        self._endpoints = endpoints
        self._rest = rest
        self._publish = publish
        self._max = max_trades_per_gap
        self._page = page_size
        self._last: dict[str, int] = {}
        self._queue: asyncio.Queue[tuple[str, int, int]] = asyncio.Queue()
        self.stats = GapStats()

    def accept(self, trade: AggTrade) -> bool:
        """Canlı işlemi değerlendirir. Tekrar ise ``False`` (yayımlanmamalı)."""
        last = self._last.get(trade.symbol)
        if last is not None:
            if trade.trade_id <= last:
                self.stats.duplicates += 1
                return False
            if trade.trade_id > last + 1:
                self.stats.detected += 1
                self._enqueue(trade.symbol, last + 1, trade.trade_id - 1)
        self._last[trade.symbol] = trade.trade_id
        return True

    def forget(self, symbol: str) -> None:
        self._last.pop(symbol, None)

    def _enqueue(self, symbol: str, first: int, last: int) -> None:
        missing = last - first + 1
        if missing > self._max:
            self.stats.unrecovered_gaps += 1
            self.stats.unrecovered_trades += missing - self._max
            first = last - self._max + 1
        self.stats.pending += 1
        self._queue.put_nowait((symbol, first, last))

    def _to_event(self, symbol: str, row: dict[str, Any]) -> AggTrade:
        return AggTrade(
            market=self.market,
            event_time_ms=int(row["T"]),
            symbol=symbol,
            trade_id=int(row["a"]),
            price=float(row["p"]),
            qty=float(row["q"]),
            trade_time_ms=int(row["T"]),
            buyer_is_maker=bool(row["m"]),
            recovered=True,
        )

    async def fill(self, symbol: str, first: int, last: int) -> int:
        """[first, last] aralığındaki işlemleri geri alır; geri alınan sayısını döner."""
        next_id = first
        recovered = 0
        while next_id <= last:
            limit = min(self._page, last - next_id + 1)
            rows = await self._rest.get(
                self._endpoints.agg_trades_path,
                params={"symbol": symbol, "fromId": next_id, "limit": limit},
                weight=self._endpoints.agg_trades_weight,
                priority=Priority.LOW,
            )
            progressed = False
            for row in rows or []:
                trade_id = int(row["a"])
                if trade_id < next_id:
                    continue
                if trade_id > last:
                    break
                await self._publish(self._to_event(symbol, row))
                recovered += 1
                next_id = trade_id + 1
                progressed = True
            if not progressed:
                break
        self.stats.recovered_trades += recovered
        missing = last - first + 1 - recovered
        if missing > 0:
            self.stats.unrecovered_gaps += 1
            self.stats.unrecovered_trades += missing
        return recovered

    async def run(self) -> None:
        while True:
            symbol, first, last = await self._queue.get()
            try:
                await self.fill(symbol, first, last)
            except Exception:
                self.stats.unrecovered_gaps += 1
                self.stats.unrecovered_trades += last - first + 1
                logger.exception(
                    "Kaçırılan işlemler geri alınamadı",
                    extra={"market": self.market.value, "symbol": symbol},
                )
                await asyncio.sleep(1)
            finally:
                self.stats.pending -= 1
