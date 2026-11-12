"""Anlık fiyatlar: Binance işlem akışındaki (aggTrade) her yeni fiyat beklemeden ekranlara gider.

Binance her işlemi gerçekleştiği anda akışa yazar; motor bunu zaten alır (izlenen bütün coinler).
Burada değişen fiyatlar toplanır ve 0,1 saniyede bir yayımlanır:

* Masaüstü: bütün coinlerin değişen fiyatları ``PriceTick`` olayıyla (yerel WebSocket) anında
  ekrana düşer (coin listesi, fırsatlar, pozisyonlar, bakiye).
* Telefon: telefonda görünen coinlerin (açık pozisyonlar, bot adayları, en iyi fırsatlar) fiyatları
  uçtan uca şifreli aktarma kanalıyla gider; yüzlerce coini telefona göndermek pili ve
  bağlantıyı yorardı.

0,1 saniye, ekranın ve gözün izleyebileceğinden hızlıdır. Binance'e ek istek yapılmaz (hız sınırı
etkilenmez).
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
PHONE_REFRESH_S = 0.5


class LivePrices:
    def __init__(self, runtime: EngineRuntime) -> None:
        self.runtime = runtime
        self._phone: set[str] = set()
        self._pending: dict[str, float] = {}
        self._last: dict[str, float] = {}
        self.published = 0

    def note(self, market: Market, symbol: str, price: float) -> None:
        """Piyasa verisi servisinden her işlem fiyatında çağrılır (hızlı olmalı)."""
        key = f"{market.value}:{symbol}"
        if self._last.get(key) != price:
            self._pending[key] = price

    def current(self) -> dict[str, float]:
        """Bilinen son fiyatlar (yeni bağlanan ekrana ilk durum olarak gönderilir)."""
        return {**self._last, **self._pending}

    def phone_current(self) -> dict[str, float]:
        """Telefonda görünen coinlerin bilinen son fiyatları (telefon bağlanınca ilk durum)."""
        return {k: v for k, v in self.current().items() if k in self._phone}

    def refresh_phone(self) -> None:
        """Telefonda görünen coinler: açık pozisyonlar, bot adayları ve en iyi fırsatlar."""
        keys: set[str] = set()
        execution = self.runtime.active_execution()
        if execution is not None:
            for market, item in execution.markets.items():
                keys.update(f"{market.value}:{s}" for s in item.engine.positions.positions)
        trader = self.runtime.autotrader
        if trader is not None:
            keys.update(f"{c['market']}:{c['symbol']}" for c in trader.candidates(limit=5))
        try:
            if self.runtime.opportunities is not None:
                keys.update(
                    f"{o.market}:{o.symbol}"
                    for o in self.runtime.opportunities.top(
                        None, min_score=50, direction=None, limit=5
                    )
                )
        except Exception:  # fırsat listesi hazır değilse telefon yalnızca pozisyonları alır
            logger.debug("Telefon fiyat listesi: fırsatlar atlandı", exc_info=True)
        self._phone = keys

    async def flush(self) -> None:
        if not self._pending:
            return
        prices, self._pending = self._pending, {}
        self._last.update(prices)
        self.published += 1
        await self.runtime.bus.publish(PriceTick(prices=prices))
        remote = self.runtime.remote
        if remote is not None and remote.enabled:
            phone = {k: v for k, v in prices.items() if k in self._phone}
            if phone:
                try:
                    await remote.send_ticks(phone)
                except Exception:  # telefon bağlantı hatası fiyat yayınını durdurmaz
                    logger.debug("Telefona anlık fiyat gönderilemedi", exc_info=True)

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        next_phone = 0.0
        while True:
            now = loop.time()
            if now >= next_phone:
                self.refresh_phone()
                next_phone = now + PHONE_REFRESH_S
            await self.flush()
            await asyncio.sleep(FLUSH_S)
