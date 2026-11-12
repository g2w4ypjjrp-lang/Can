"""Açık pozisyonların anlık fiyatı: Binance işlem akışındaki (aggTrade) her yeni fiyat beklemeden
ekranlara gönderilir.

Binance her işlemi gerçekleştiği anda akışa yazar; motor bunu zaten alır. Burada yalnızca açık
pozisyonu olan coinlerin fiyatları toplanır ve 0,1 saniyede bir (değiştiyse) yayımlanır:

* Masaüstü: ``PriceTick`` olayı yerel olay akışıyla (WebSocket) anında ekrana düşer.
* Telefon: aynı fiyatlar uçtan uca şifreli aktarma kanalıyla telefona gider.

0,1 saniye, ekranın ve ağın izleyebileceğinden hızlıdır; daha sık yayın gözle fark edilmez ama
telefonun pilini ve bağlantıyı yorar. Binance'e ek istek yapılmaz (hız sınırı etkilenmez).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from ati_engine.core.events import PriceTick
from ati_engine.core.models import Market

if TYPE_CHECKING:
    from ati_engine.runtime import EngineRuntime

logger = logging.getLogger(__name__)

FLUSH_S = 0.1
WATCH_REFRESH_S = 0.5


class LivePrices:
    def __init__(self, runtime: EngineRuntime) -> None:
        self.runtime = runtime
        self._watch: dict[Market, set[str]] = {}
        self._pending: dict[str, float] = {}
        self._last: dict[str, float] = {}
        self.published = 0

    def note(self, market: Market, symbol: str, price: float) -> None:
        """Piyasa verisi servisinden her işlem fiyatında çağrılır (hızlı olmalı)."""
        if symbol not in self._watch.get(market, ()):
            return
        key = f"{market.value}:{symbol}"
        if self._last.get(key) != price:
            self._pending[key] = price

    def refresh_watch(self) -> None:
        execution = self.runtime.active_execution()
        watch: dict[Market, set[str]] = {}
        if execution is not None:
            for market, item in execution.markets.items():
                watch[market] = set(item.engine.positions.positions)
        self._watch = watch
        live = {f"{m.value}:{s}" for m, symbols in watch.items() for s in symbols}
        self._last = {k: v for k, v in self._last.items() if k in live}

    async def flush(self) -> None:
        if not self._pending:
            return
        prices, self._pending = self._pending, {}
        self._last.update(prices)
        self.published += 1
        await self.runtime.bus.publish(PriceTick(prices=prices))
        remote = self.runtime.remote
        if remote is not None and remote.enabled:
            try:
                await remote.send_ticks(prices)
            except Exception:  # telefon bağlantı hatası fiyat yayınını durdurmaz
                logger.debug("Telefona anlık fiyat gönderilemedi", exc_info=True)

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        next_watch = 0.0
        while True:
            now = loop.time()
            if now >= next_watch:
                self.refresh_watch()
                next_watch = now + WATCH_REFRESH_S
            await self.flush()
            await asyncio.sleep(FLUSH_S)
