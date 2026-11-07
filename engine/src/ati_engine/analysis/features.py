"""Özellik motoru: mum akışından modele girecek, ölçekten bağımsız (durağan) özellikler.

* Aynı kod tarihsel veride (eğitim) ve canlıda (tahmin) çalışır — eğitim/canlı farkı olmaz.
* Fiyat seviyeleri doğrudan kullanılmaz; uzaklıklar ATR'ye, getiriler logaritmik oranlara,
  hacim kendi geçmişine göre ölçeklenir. Böylece farklı coinler ve dönemler tek modelde
  birleştirilebilir.
* Futures bağlamı (funding, açık pozisyon, büyük oyuncu/genel long-short oranları, agresif
  alış/satış oranı) verilmezse ilgili özellikler ``nan`` olur; LightGBM eksik değeri doğal
  olarak işler.
* Tüm özellikler yalnızca o ana kadarki veriyle hesaplanır (ileriye bakma testleri vardır).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from ati_engine.analysis.indicators import (
    ATR,
    EMA,
    MACD,
    OBV,
    RSI,
    SMA,
    Bollinger,
    Fibonacci,
    Ichimoku,
    RollingExtremes,
    SessionVWAP,
    StochRSI,
)

NAN = float("nan")

BASE_FEATURES: tuple[str, ...] = (
    "ret_1",
    "ret_4",
    "ret_24",
    "volatility_24",
    "atr_pct",
    "rsi_14",
    "macd_atr",
    "macd_hist_atr",
    "ema_9_21_atr",
    "ema_21_50_atr",
    "ema_50_200_atr",
    "close_ema_200_atr",
    "bb_pctb",
    "bb_width",
    "stoch_rsi_k",
    "stoch_rsi_d",
    "obv_flow_24",
    "vwap_dist_atr",
    "ichimoku_tk_atr",
    "ichimoku_cloud_atr",
    "ichimoku_lag_atr",
    "fib_position",
    "fib_nearest_dist_pct",
    "volume_z_48",
    "taker_buy_ratio",
    "taker_buy_ratio_24",
    "hour_sin",
    "hour_cos",
)

FUTURES_FEATURES: tuple[str, ...] = (
    "funding_rate_bps",
    "oi_change_4",
    "oi_change_24",
    "top_long_short_log",
    "global_long_short_log",
    "top_minus_global_log",
    "taker_long_short_log",
)

ALL_FEATURES: tuple[str, ...] = BASE_FEATURES + FUTURES_FEATURES

WARMUP_BARS = 210  # EMA200 + pay


@dataclass(frozen=True)
class Bar:
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    taker_buy_quote: float


@dataclass(frozen=True)
class FuturesContext:
    funding_rate: float | None = None
    open_interest_usd: float | None = None
    top_long_short: float | None = None  # büyük oyuncu pozisyon long/short oranı
    global_long_short: float | None = None  # hesap sayısına göre long/short oranı
    taker_long_short: float | None = None  # agresif alış/satış hacim oranı


@dataclass(frozen=True)
class Snapshot:
    """Bir mum kapanışındaki gösterge değerleri (stratejilerin okuduğu görünüm)."""

    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    ema9: float
    ema21: float
    ema50: float
    ema200: float
    rsi: float
    macd: float
    macd_signal: float
    macd_hist: float
    atr: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    bb_width: float
    bb_width_rank: float  # bant genişliğinin son 120 mumdaki yüzdelik sırası (0-1)
    stoch_k: float
    stoch_d: float | None
    vwap: float | None
    tenkan: float
    kijun: float
    span_a: float | None
    span_b: float | None
    lagging_ref: float | None
    donchian_high: float | None  # önceki 20 mumun en yükseği (bu mum hariç)
    donchian_low: float | None
    volume_z: float
    taker_buy_ratio: float
    funding_rate: float | None
    oi_change_4: float | None
    top_long_short: float | None
    global_long_short: float | None

    @property
    def cloud_top(self) -> float | None:
        if self.span_a is None or self.span_b is None:
            return None
        return max(self.span_a, self.span_b)

    @property
    def cloud_bottom(self) -> float | None:
        if self.span_a is None or self.span_b is None:
            return None
        return min(self.span_a, self.span_b)


def _log_ratio(a: float | None, b: float | None) -> float:
    if a is None or b is None or a <= 0 or b <= 0:
        return NAN
    return math.log(a / b)


def _safe_log(x: float | None) -> float:
    return math.log(x) if x is not None and x > 0 else NAN


class RollingMoments:
    """Kayan pencerede ortalama ve standart sapma (pencere küçük; doğrudan hesap)."""

    def __init__(self, period: int) -> None:
        self.window: deque[float] = deque(maxlen=period)

    def update(self, x: float) -> tuple[float, float] | None:
        self.window.append(x)
        if len(self.window) < (self.window.maxlen or 0):
            return None
        n = len(self.window)
        mean = math.fsum(self.window) / n
        var = math.fsum((v - mean) ** 2 for v in self.window) / (n - 1)
        return mean, math.sqrt(var)


class FeatureEngine:
    """Tek bir sembol ve aralık için özellik durumu."""

    def __init__(self) -> None:
        self.ema9, self.ema21, self.ema50, self.ema200 = EMA(9), EMA(21), EMA(50), EMA(200)
        self.rsi = RSI(14)
        self.macd = MACD(12, 26, 9)
        self.atr = ATR(14)
        self.bb = Bollinger(20, 2.0)
        self.stoch = StochRSI(14, 14, 3, 3)
        self.obv = OBV()
        self.vwap = SessionVWAP()
        self.ichimoku = Ichimoku()
        self.fib = Fibonacci(100)
        self.taker_ratio_ma = SMA(24)
        self._closes: deque[float] = deque(maxlen=25)
        self._log_returns = RollingMoments(24)
        self._log_volume = RollingMoments(48)
        self._obv_hist: deque[float] = deque(maxlen=25)
        self._volumes: deque[float] = deque(maxlen=24)
        self._oi: deque[float | None] = deque(maxlen=25)
        self._donchian = RollingExtremes(20)
        self._donchian_prev: tuple[float, float] | None = None
        self._widths: deque[float] = deque(maxlen=120)
        self.snapshot: Snapshot | None = None
        self.bars = 0

    def update(self, bar: Bar, futures: FuturesContext | None = None) -> dict[str, float] | None:
        """Mum kapandığında çağrılır. Isınma tamamlanana kadar ``None`` döner."""
        self.bars += 1
        c, h, lo = bar.close, bar.high, bar.low
        prev_close = self._closes[-1] if self._closes else None
        self._closes.append(c)
        ema9 = self.ema9.update(c)
        ema21 = self.ema21.update(c)
        ema50 = self.ema50.update(c)
        ema200 = self.ema200.update(c)
        rsi = self.rsi.update(c)
        macd = self.macd.update(c)
        atr = self.atr.update(h, lo, c)
        bb = self.bb.update(c)
        stoch = self.stoch.update(c)
        obv = self.obv.update(c, bar.volume)
        self._obv_hist.append(obv)
        self._volumes.append(bar.volume)
        vwap = self.vwap.update(bar.open_time_ms, h, lo, c, bar.volume, bar.quote_volume)
        ichi = self.ichimoku.update(h, lo, c)
        fib = self.fib.update(h, lo, c)
        ratio = bar.taker_buy_quote / bar.quote_volume if bar.quote_volume > 0 else 0.5
        ratio_ma = self.taker_ratio_ma.update(ratio)
        log_ret = math.log(c / prev_close) if prev_close and prev_close > 0 and c > 0 else 0.0
        moments = self._log_returns.update(log_ret)
        vol_moments = self._log_volume.update(math.log(bar.volume + 1e-12))
        self._oi.append(futures.open_interest_usd if futures else None)
        donchian = self._donchian_prev  # önceki 20 mum (bu mum hariç)
        self._donchian_prev = self._donchian.update(h, lo)
        if bb is not None:
            self._widths.append(bb.width)
        self.snapshot = None

        if self.bars < WARMUP_BARS:
            return None
        if (
            ema9 is None
            or ema21 is None
            or ema50 is None
            or ema200 is None
            or rsi is None
            or macd is None
            or atr is None
            or bb is None
            or stoch is None
            or ichi is None
            or moments is None
            or vol_moments is None
            or atr <= 0
        ):
            return None

        closes = self._closes
        features: dict[str, float] = {
            "ret_1": math.log(c / closes[-2]),
            "ret_4": math.log(c / closes[-5]),
            "ret_24": math.log(c / closes[-25]),
            "volatility_24": moments[1],
            "atr_pct": atr / c,
            "rsi_14": rsi / 100,
            "macd_atr": macd.macd / atr,
            "macd_hist_atr": macd.hist / atr,
            "ema_9_21_atr": (ema9 - ema21) / atr,
            "ema_21_50_atr": (ema21 - ema50) / atr,
            "ema_50_200_atr": (ema50 - ema200) / atr,
            "close_ema_200_atr": (c - ema200) / atr,
            "bb_pctb": bb.percent_b(c),
            "bb_width": bb.width,
            "stoch_rsi_k": stoch.k / 100,
            "stoch_rsi_d": stoch.d / 100 if stoch.d is not None else NAN,
            "obv_flow_24": (
                (obv - self._obv_hist[0]) / sum(self._volumes)
                if len(self._obv_hist) == 25 and sum(self._volumes) > 0
                else NAN
            ),
            "vwap_dist_atr": (c - vwap) / atr if vwap is not None else NAN,
            "ichimoku_tk_atr": (ichi.tenkan - ichi.kijun) / atr,
            "ichimoku_cloud_atr": self._cloud_distance(c, ichi.span_a, ichi.span_b, atr),
            "ichimoku_lag_atr": (
                (c - ichi.lagging_ref) / atr if ichi.lagging_ref is not None else NAN
            ),
            "fib_position": fib.position if fib else NAN,
            "fib_nearest_dist_pct": fib.nearest_distance_pct if fib else NAN,
            "volume_z_48": (
                (math.log(bar.volume + 1e-12) - vol_moments[0]) / vol_moments[1]
                if vol_moments[1] > 0
                else 0.0
            ),
            "taker_buy_ratio": ratio,
            "taker_buy_ratio_24": ratio_ma if ratio_ma is not None else NAN,
            "hour_sin": math.sin(2 * math.pi * ((bar.open_time_ms // 3_600_000) % 24) / 24),
            "hour_cos": math.cos(2 * math.pi * ((bar.open_time_ms // 3_600_000) % 24) / 24),
        }
        features.update(self._futures_features(futures))
        width_rank = sum(1 for w in self._widths if w <= bb.width) / len(self._widths)
        self.snapshot = Snapshot(
            open_time_ms=bar.open_time_ms,
            open=bar.open,
            high=h,
            low=lo,
            close=c,
            ema9=ema9,
            ema21=ema21,
            ema50=ema50,
            ema200=ema200,
            rsi=rsi,
            macd=macd.macd,
            macd_signal=macd.signal,
            macd_hist=macd.hist,
            atr=atr,
            bb_upper=bb.upper,
            bb_middle=bb.middle,
            bb_lower=bb.lower,
            bb_width=bb.width,
            bb_width_rank=width_rank,
            stoch_k=stoch.k,
            stoch_d=stoch.d,
            vwap=vwap,
            tenkan=ichi.tenkan,
            kijun=ichi.kijun,
            span_a=ichi.span_a,
            span_b=ichi.span_b,
            lagging_ref=ichi.lagging_ref,
            donchian_high=donchian[0] if donchian else None,
            donchian_low=donchian[1] if donchian else None,
            volume_z=features["volume_z_48"],
            taker_buy_ratio=ratio,
            funding_rate=futures.funding_rate if futures else None,
            oi_change_4=(None if math.isnan(features["oi_change_4"]) else features["oi_change_4"]),
            top_long_short=futures.top_long_short if futures else None,
            global_long_short=futures.global_long_short if futures else None,
        )
        return features

    @staticmethod
    def _cloud_distance(c: float, a: float | None, b: float | None, atr: float) -> float:
        if a is None or b is None:
            return NAN
        top, bottom = max(a, b), min(a, b)
        if c > top:
            return (c - top) / atr
        if c < bottom:
            return (c - bottom) / atr
        return 0.0

    def _futures_features(self, ctx: FuturesContext | None) -> dict[str, float]:
        if ctx is None:
            return dict.fromkeys(FUTURES_FEATURES, NAN)
        oi = self._oi
        top = _safe_log(ctx.top_long_short)
        glob = _safe_log(ctx.global_long_short)
        return {
            "funding_rate_bps": ctx.funding_rate * 10_000 if ctx.funding_rate is not None else NAN,
            "oi_change_4": _log_ratio(oi[-1], oi[-5]) if len(oi) >= 5 else NAN,
            "oi_change_24": _log_ratio(oi[-1], oi[-25]) if len(oi) >= 25 else NAN,
            "top_long_short_log": top,
            "global_long_short_log": glob,
            "top_minus_global_log": top - glob,
            "taker_long_short_log": _safe_log(ctx.taker_long_short),
        }


def vectorize(features: dict[str, float], names: tuple[str, ...] = ALL_FEATURES) -> list[float]:
    return [features.get(name, NAN) for name in names]
