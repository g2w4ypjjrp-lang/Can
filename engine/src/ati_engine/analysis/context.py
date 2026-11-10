"""Piyasa bağlamı: rejim (trend / yatay / aşırı oynak / karışık) ve üst zaman dilimi trendi.

* **Rejim**, puanlama aralığındaki mumlardan hesaplanır: ADX (trendin gücü), Kaufman verimlilik
  oranı (son 20 mumda net hareketin toplam harekete oranı) ve oynaklık sırası (ATR/fiyat'ın son
  200 mumdaki yüzdelik sırası).
* **Üst zaman dilimi**, aynı mumlar ``factor`` katına (varsayılan 4: 1 saat → 4 saat)
  birleştirilerek hesaplanır; yalnızca **tamamlanmış** üst mumlar kullanılır (ileriye bakma yok).
  Değer -1 (güçlü düşüş) ile +1 (güçlü yükseliş) arasıdır.

Fırsat puanı bu bağlamla stratejileri ağırlıklandırır: trend rejiminde trend ve kırılım
stratejileri, yatay rejimde ortalamaya dönüş stratejileri öne çıkar; aşırı oynaklıkta ve üst zaman
dilimi trendine karşı işlemlerde puan düşürülür.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict, dataclass
from itertools import pairwise
from typing import Any, Literal

from ati_engine.analysis.indicators import ADX, ATR, EMA

Regime = Literal["trend", "range", "volatile", "mixed"]

REGIME_TITLES: dict[str, str] = {
    "trend": "Trend",
    "range": "Yatay",
    "volatile": "Aşırı oynak",
    "mixed": "Karışık",
}


@dataclass(frozen=True)
class MarketContext:
    regime: Regime
    adx: float | None
    plus_di: float | None
    minus_di: float | None
    efficiency: float  # 0-1
    vol_rank: float  # 0-1
    htf_trend: float | None  # -1..+1
    htf_label: str  # ör. "4 saatlik"
    detail: str
    htf_detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["regime_title"] = REGIME_TITLES[self.regime]
        return data


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _label(ms: int) -> str:
    hours = ms / 3_600_000
    if hours >= 24 and hours % 24 == 0:
        return f"{hours / 24:g} günlük"
    if hours >= 1:
        return f"{hours:g} saatlik"
    return f"{ms / 60_000:g} dakikalık"


class _HigherTimeframe:
    def __init__(self, factor: int) -> None:
        self.factor = factor
        self.ema21, self.ema50, self.atr = EMA(21), EMA(50), ATR(14)
        self._key: int | None = None
        self._bar: list[float] | None = None  # açılış, yüksek, düşük, kapanış
        self.trend: float | None = None
        self.detail = ""

    def _finish(self) -> None:
        if self._bar is None:
            return
        _, high, low, close = self._bar
        self._bar = None
        e21, e50 = self.ema21.update(close), self.ema50.update(close)
        atr = self.atr.update(high, low, close)
        if e21 is None or e50 is None or atr is None or atr <= 0:
            return
        alignment = _clamp((e21 - e50) / atr / 2)
        position = math.copysign(min(abs(close - e50) / atr / 3, 1.0), close - e50)
        self.trend = 0.5 * alignment + 0.5 * position
        self.detail = (
            f"EMA21-EMA50 {(e21 - e50) / atr:+.1f} ATR, fiyat EMA50'nin "
            f"{'üstünde' if close >= e50 else 'altında'}"
        )

    def update(self, open_ms: int, step: int, o: float, h: float, low: float, c: float) -> None:
        span = step * self.factor
        key = open_ms // span
        if self._key is not None and key != self._key:
            self._finish()  # boşluk nedeniyle eksik kalan üst mum
        self._key = key
        if self._bar is None:
            self._bar = [o, h, low, c]
        else:
            self._bar[1] = max(self._bar[1], h)
            self._bar[2] = min(self._bar[2], low)
            self._bar[3] = c
        if open_ms + step >= (key + 1) * span:
            self._finish()  # üst mumun son alt mumu kapandı


class MarketContextTracker:
    def __init__(self, *, htf_factor: int = 4, er_period: int = 20, vol_window: int = 200) -> None:
        self.adx = ADX(14)
        self.atr = ATR(14)
        self.htf = _HigherTimeframe(htf_factor)
        self._er_window = er_period + 1
        self._closes: deque[float] = deque(maxlen=self._er_window)
        self._vol: deque[float] = deque(maxlen=vol_window)
        self._last_open: int | None = None
        self._step: int | None = None
        self.value: MarketContext | None = None

    def update(
        self, open_ms: int, o: float, h: float, low: float, c: float
    ) -> MarketContext | None:
        if self._last_open is not None:
            diff = open_ms - self._last_open
            if diff > 0 and (self._step is None or diff < self._step):
                self._step = diff
        self._last_open = open_ms
        adx = self.adx.update(h, low, c)
        atr = self.atr.update(h, low, c)
        self._closes.append(c)
        if self._step is not None:
            self.htf.update(open_ms, self._step, o, h, low, c)
        if atr is None or c <= 0 or len(self._closes) < self._er_window:
            return None
        atr_pct = atr / c
        self._vol.append(atr_pct)
        vol_rank = sum(1 for v in self._vol if v <= atr_pct) / len(self._vol)
        closes = list(self._closes)
        path = sum(abs(b - a) for a, b in pairwise(closes))
        efficiency = abs(closes[-1] - closes[0]) / path if path > 0 else 0.0
        adx_value = adx.adx if adx is not None else None
        regime: Regime
        if vol_rank >= 0.95 and len(self._vol) >= 50:
            regime = "volatile"
        elif adx_value is not None and adx_value >= 25 and efficiency >= 0.3:
            regime = "trend"
        elif (adx_value is None or adx_value <= 20) and efficiency <= 0.25:
            regime = "range"
        else:
            regime = "mixed"
        adx_text = f"ADX {adx_value:.0f}" if adx_value is not None else "ADX ısınıyor"
        detail = (
            f"{REGIME_TITLES[regime]} piyasa: {adx_text}, verimlilik {efficiency:.2f}, "
            f"oynaklık sırası %{vol_rank * 100:.0f}"
        )
        self.value = MarketContext(
            regime=regime,
            adx=round(adx_value, 2) if adx_value is not None else None,
            plus_di=round(adx.plus_di, 2) if adx is not None else None,
            minus_di=round(adx.minus_di, 2) if adx is not None else None,
            efficiency=round(efficiency, 4),
            vol_rank=round(vol_rank, 4),
            htf_trend=round(self.htf.trend, 4) if self.htf.trend is not None else None,
            htf_label=_label(self._step * self.htf.factor) if self._step else "üst zaman dilimi",
            detail=detail,
            htf_detail=self.htf.detail,
        )
        return self.value
