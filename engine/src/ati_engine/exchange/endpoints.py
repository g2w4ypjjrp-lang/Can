"""Piyasaya göre Binance uç noktaları, yollar ve istek ağırlıkları.

Ağırlıklar resmi belgelerden alınmıştır (Spot: 2026-11-07 tarihli ``rest-api.md``). Futures
derinlik ağırlıkları belgede doğrulanamadığından ihtiyatlı (yüksek) varsayılır; bütçe zaten her
yanıttaki ``X-MBX-USED-WEIGHT-1M`` başlığıyla düzeltilir.

USDⓈ-M Futures WebSocket akışları 2026'da iki rotaya bölünmüştür; bu ortamda deneyle de
doğrulandı:
* ``/public``: derinlik (``@depth``, ``@depth<N>``) ve en iyi fiyat
  (``@bookTicker``, ``!bookTicker``)
* ``/market``: işlemler, mumlar, mark price, ticker'lar, tasfiyeler ve diğerleri
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ati_engine.config import BinanceEndpoints
from ati_engine.core.models import Market


class WsRoute(StrEnum):
    DEFAULT = "default"  # Spot: tek rota
    PUBLIC = "public"  # Futures: derinlik ve bookTicker
    MARKET = "market"  # Futures: diğer piyasa akışları


@dataclass(frozen=True)
class MarketEndpoints:
    market: Market
    rest_base: str
    time_path: str
    exchange_info_path: str
    depth_path: str
    agg_trades_path: str
    agg_trades_weight: int
    klines_path: str
    exchange_info_weight: int
    ws_bases: dict[WsRoute, str]

    def depth_weight(self, limit: int) -> int:
        if self.market is Market.SPOT:
            if limit <= 100:
                return 5
            if limit <= 500:
                return 25
            if limit <= 1000:
                return 50
            return 250
        # USDⓈ-M Futures (ihtiyatlı varsayım)
        if limit <= 50:
            return 2
        if limit <= 100:
            return 5
        if limit <= 500:
            return 10
        return 20

    def klines_weight(self, limit: int) -> int:
        if self.market is Market.SPOT:
            return 2
        if limit < 100:
            return 1
        if limit < 500:
            return 2
        if limit <= 1000:
            return 5
        return 10

    def route_for(self, stream: str) -> WsRoute:
        if self.market is Market.SPOT:
            return WsRoute.DEFAULT
        name = stream.split("@", 1)[1] if "@" in stream else stream
        if stream == "!bookTicker" or name.startswith(("depth", "bookTicker")):
            return WsRoute.PUBLIC
        return WsRoute.MARKET

    def ws_url(self, route: WsRoute) -> str:
        return self.ws_bases[route].rstrip("/") + "/stream"


def endpoints_for(market: Market, cfg: BinanceEndpoints) -> MarketEndpoints:
    if market is Market.SPOT:
        return MarketEndpoints(
            market=market,
            rest_base=cfg.spot_market_data_rest,
            time_path="/api/v3/time",
            exchange_info_path="/api/v3/exchangeInfo",
            depth_path="/api/v3/depth",
            agg_trades_path="/api/v3/aggTrades",
            agg_trades_weight=4,
            klines_path="/api/v3/klines",
            exchange_info_weight=20,
            ws_bases={WsRoute.DEFAULT: cfg.spot_market_data_ws},
        )
    return MarketEndpoints(
        market=market,
        rest_base=cfg.futures_rest,
        time_path="/fapi/v1/time",
        exchange_info_path="/fapi/v1/exchangeInfo",
        depth_path="/fapi/v1/depth",
        agg_trades_path="/fapi/v1/aggTrades",
        agg_trades_weight=20,  # yanıt başlığında gözlenen değer (2026-11-07)
        klines_path="/fapi/v1/klines",
        exchange_info_weight=1,
        ws_bases={WsRoute.PUBLIC: cfg.futures_ws_public, WsRoute.MARKET: cfg.futures_ws_market},
    )
