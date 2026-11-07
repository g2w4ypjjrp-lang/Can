"""Büyük oyuncu (Smart Money) pozisyonlanması: USDⓈ-M Futures istatistikleri.

Binance'in herkese açık istatistik uç noktaları (5 dakikalık periyot):
* ``topLongShortPositionRatio``: en büyük hesapların pozisyon büyüklüğüne göre long/short oranı
* ``globalLongShortAccountRatio``: tüm hesapların sayıca long/short oranı ("kalabalık")
* ``openInterestHist``: açık pozisyon (kontrat ve dolar değeri)

Son bir saatteki değişimler hesaplanır. Büyük oyuncuların long oranı artarken kalabalığın
azalması (veya tersi) **ayrışma** olarak işaretlenir. Bu istatistikler gecikmelidir (5 dk) ve
tek başına işlem sinyali değildir; fırsat puanına (Aşama 7) girdi olur.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ati_engine.exchange.rate_limit import Priority
from ati_engine.exchange.rest import BinanceRestClient

TOP_POSITION_PATH = "/futures/data/topLongShortPositionRatio"
GLOBAL_ACCOUNT_PATH = "/futures/data/globalLongShortAccountRatio"
OPEN_INTEREST_PATH = "/futures/data/openInterestHist"


@dataclass(frozen=True)
class PositioningSnapshot:
    symbol: str
    timestamp_ms: int
    top_long_pct: float  # büyük oyuncuların long payı (%)
    top_ratio: float  # büyük oyuncular long/short
    global_long_pct: float  # tüm hesapların long payı (%)
    global_ratio: float
    open_interest_usd: float
    top_long_change_pts: float  # son ~1 saatte puan değişimi
    global_long_change_pts: float
    open_interest_change_pct: float
    divergence: bool  # büyük oyuncular ile kalabalık ters yöne gidiyor


def _series(rows: list[dict[str, Any]], key: str) -> list[float]:
    ordered = sorted(rows, key=lambda r: int(r["timestamp"]))
    return [float(r[key]) for r in ordered]


def build_snapshot(
    symbol: str,
    top_rows: list[dict[str, Any]],
    global_rows: list[dict[str, Any]],
    oi_rows: list[dict[str, Any]],
    *,
    divergence_pts: float = 2.0,
) -> PositioningSnapshot | None:
    if not top_rows or not global_rows or not oi_rows:
        return None
    top_long = _series(top_rows, "longAccount")
    top_ratio = _series(top_rows, "longShortRatio")
    glob_long = _series(global_rows, "longAccount")
    glob_ratio = _series(global_rows, "longShortRatio")
    oi = _series(oi_rows, "sumOpenInterestValue")
    top_change = (top_long[-1] - top_long[0]) * 100
    glob_change = (glob_long[-1] - glob_long[0]) * 100
    oi_change = (oi[-1] / oi[0] - 1) * 100 if oi[0] > 0 else 0.0
    divergence = (
        abs(top_change) >= divergence_pts
        and abs(glob_change) >= divergence_pts
        and (top_change > 0) != (glob_change > 0)
    )
    return PositioningSnapshot(
        symbol=symbol,
        timestamp_ms=max(int(r["timestamp"]) for r in top_rows),
        top_long_pct=round(top_long[-1] * 100, 2),
        top_ratio=top_ratio[-1],
        global_long_pct=round(glob_long[-1] * 100, 2),
        global_ratio=glob_ratio[-1],
        open_interest_usd=oi[-1],
        top_long_change_pts=round(top_change, 2),
        global_long_change_pts=round(glob_change, 2),
        open_interest_change_pct=round(oi_change, 3),
        divergence=divergence,
    )


async def fetch_snapshot(
    rest: BinanceRestClient, symbol: str, *, points: int = 13
) -> PositioningSnapshot | None:
    """Son ~1 saatlik (13 x 5 dk) istatistikleri alır."""
    params = {"symbol": symbol, "period": "5m", "limit": points}
    top = await rest.get(TOP_POSITION_PATH, params=params, weight=1, priority=Priority.LOW)
    glob = await rest.get(GLOBAL_ACCOUNT_PATH, params=params, weight=1, priority=Priority.LOW)
    oi = await rest.get(OPEN_INTEREST_PATH, params=params, weight=1, priority=Priority.LOW)
    return build_snapshot(symbol, top, glob, oi)
