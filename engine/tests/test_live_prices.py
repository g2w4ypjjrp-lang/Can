"""Açık pozisyonların anlık fiyatı: Binance işlem akışındaki her yeni fiyat beklemeden ekranlara
(masaüstü olay akışı ve telefon) gider; açık pozisyonu olmayan coinler ve değişmeyen fiyat
gönderilmez."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from ati_engine.core.events import PriceTick
from ati_engine.core.models import Market
from ati_engine.market.live_prices import LivePrices


class Bus:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.events.append(event)


class Remote:
    enabled = True

    def __init__(self) -> None:
        self.sent: list[dict[str, float]] = []

    async def send_ticks(self, prices: dict[str, float]) -> None:
        self.sent.append(prices)


def runtime(positions: dict[Market, list[str]], remote: Remote | None) -> Any:
    markets = {
        m: SimpleNamespace(
            engine=SimpleNamespace(positions=SimpleNamespace(positions=dict.fromkeys(s)))
        )
        for m, s in positions.items()
    }
    execution = SimpleNamespace(markets=markets)
    return SimpleNamespace(bus=Bus(), remote=remote, active_execution=lambda: execution)


async def test_open_position_prices_go_to_screens_on_every_change() -> None:
    remote = Remote()
    rt = runtime({Market.USDM_FUTURES: ["BTCUSDT"]}, remote)
    live = LivePrices(rt)
    live.refresh_watch()
    live.note(Market.USDM_FUTURES, "BTCUSDT", 97_250.1)
    live.note(Market.USDM_FUTURES, "ETHUSDT", 3_400.0)  # açık pozisyon yok
    live.note(Market.SPOT, "BTCUSDT", 97_249.0)  # o piyasada pozisyon yok
    await live.flush()
    assert rt.bus.events == [PriceTick(prices={"usdm_futures:BTCUSDT": 97_250.1})]
    assert remote.sent == [{"usdm_futures:BTCUSDT": 97_250.1}]

    # Aynı fiyat yeniden gönderilmez; 0,1 artış hemen gider (aradaki fiyatlardan sonuncusu).
    live.note(Market.USDM_FUTURES, "BTCUSDT", 97_250.1)
    await live.flush()
    assert len(rt.bus.events) == 1
    live.note(Market.USDM_FUTURES, "BTCUSDT", 97_250.15)
    live.note(Market.USDM_FUTURES, "BTCUSDT", 97_250.2)
    await live.flush()
    assert rt.bus.events[-1] == PriceTick(prices={"usdm_futures:BTCUSDT": 97_250.2})

    # Pozisyon kapanınca o coinin fiyatı artık gönderilmez.
    rt.active_execution().markets[Market.USDM_FUTURES].engine.positions.positions.clear()
    live.refresh_watch()
    live.note(Market.USDM_FUTURES, "BTCUSDT", 97_300.0)
    await live.flush()
    assert len(rt.bus.events) == 2


async def test_without_execution_or_phone_nothing_breaks() -> None:
    rt = runtime({}, None)
    rt.active_execution = lambda: None
    live = LivePrices(rt)
    live.refresh_watch()
    live.note(Market.USDM_FUTURES, "BTCUSDT", 1.0)
    await live.flush()
    assert rt.bus.events == []
