"""Anlık fiyatlar: Binance işlem akışındaki her yeni fiyat beklemeden ekranlara gider. Masaüstüne
bütün coinler; telefona yalnızca telefonda görünenler (açık pozisyonlar, bot adayları, en iyi
fırsatlar). Değişmeyen fiyat yeniden gönderilmez."""

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
    trader = SimpleNamespace(
        candidates=lambda limit=5: [{"market": "usdm_futures", "symbol": "AVAXUSDT"}]
    )
    opportunities = SimpleNamespace(
        top=lambda *a, **k: [SimpleNamespace(market=Market.SPOT, symbol="DOGEUSDT")]
    )
    return SimpleNamespace(
        bus=Bus(),
        remote=remote,
        active_execution=lambda: execution,
        autotrader=trader,
        opportunities=opportunities,
    )


async def test_every_coin_goes_to_desktop_and_visible_ones_to_phone() -> None:
    remote = Remote()
    rt = runtime({Market.USDM_FUTURES: ["BTCUSDT"]}, remote)
    live = LivePrices(rt)
    live.refresh_phone()
    live.note(Market.USDM_FUTURES, "BTCUSDT", 97_250.1)  # açık pozisyon
    live.note(Market.USDM_FUTURES, "AVAXUSDT", 35.12)  # bot adayı
    live.note(Market.SPOT, "DOGEUSDT", 0.2101)  # en iyi fırsat
    live.note(Market.USDM_FUTURES, "ETHUSDT", 3_400.0)  # yalnızca coin listesinde
    await live.flush()
    assert [e.prices for e in rt.bus.events] == [
        {
            "usdm_futures:BTCUSDT": 97_250.1,
            "usdm_futures:AVAXUSDT": 35.12,
            "spot:DOGEUSDT": 0.2101,
            "usdm_futures:ETHUSDT": 3_400.0,
        }
    ]
    assert all(isinstance(e, PriceTick) for e in rt.bus.events)
    assert remote.sent == [
        {"usdm_futures:BTCUSDT": 97_250.1, "usdm_futures:AVAXUSDT": 35.12, "spot:DOGEUSDT": 0.2101}
    ]

    # Aynı fiyat yeniden gönderilmez; 0,1 artış hemen gider (aradaki fiyatlardan sonuncusu).
    live.note(Market.USDM_FUTURES, "ETHUSDT", 3_400.0)
    await live.flush()
    assert len(rt.bus.events) == 1
    live.note(Market.USDM_FUTURES, "ETHUSDT", 3_400.05)
    live.note(Market.USDM_FUTURES, "ETHUSDT", 3_400.1)
    await live.flush()
    assert rt.bus.events[-1].prices == {"usdm_futures:ETHUSDT": 3_400.1}
    assert len(remote.sent) == 1  # telefonda görünmeyen coin telefona gitmez

    # Yeni bağlanan ekran/telefon ilk durumu alır (sonrakiler yalnızca değiştikçe).
    assert live.current()["usdm_futures:ETHUSDT"] == 3_400.1
    assert set(live.phone_current()) == {
        "usdm_futures:BTCUSDT",
        "usdm_futures:AVAXUSDT",
        "spot:DOGEUSDT",
    }


async def test_without_execution_or_phone_nothing_breaks() -> None:
    rt = runtime({}, None)
    rt.active_execution = lambda: None
    rt.autotrader = None
    rt.opportunities = None
    live = LivePrices(rt)
    live.refresh_phone()
    live.note(Market.USDM_FUTURES, "BTCUSDT", 1.0)
    await live.flush()
    assert [e.prices for e in rt.bus.events] == [{"usdm_futures:BTCUSDT": 1.0}]
