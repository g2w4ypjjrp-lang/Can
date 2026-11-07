"""Artımlı (akış) göstergeler: her yeni mum O(1) (pencere uzunluğuyla sınırlı) güncellenir.

Aynı sınıflar hem canlı akışta hem tarihsel veride kullanılır; böylece model eğitimi ile canlı
tahmin arasında hesaplama farkı oluşmaz. Her gösterge yalnızca o ana kadar gelen mumları
görür (ileriye bakma yok). Isınma süresince ``None`` döner.

Sayısal uyum: SMA, EMA, RSI, ATR, OBV, Bollinger ve Stochastic RSI, TA-Lib ile aynı başlangıç
(tohumlama) kurallarını kullanır ve TA-Lib çıktısıyla birebir eşleşir. MACD'de TA-Lib hızlı
EMA'yı farklı tohumladığı için ilk mumlarda küçük fark olur; üstel hafıza nedeniyle birkaç yüz
mumdan sonra fark ölçülemez hale gelir (testlerde doğrulanır).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


class SMA:
    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError("period >= 1")
        self.period = period
        self._window: deque[float] = deque(maxlen=period)
        self._sum = 0.0
        self.value: float | None = None

    def update(self, x: float) -> float | None:
        if len(self._window) == self.period:
            self._sum -= self._window[0]
        self._window.append(x)
        self._sum += x
        if len(self._window) == self.period:
            # Kayan toplamda biriken yuvarlama hatası periyodik olarak sıfırlanır.
            if self._sum != 0 and abs(self._sum) > 1e12:
                self._sum = math.fsum(self._window)
            self.value = self._sum / self.period
        return self.value


class EMA:
    """Üstel ortalama; ilk değer ilk ``period`` girdinin basit ortalamasıdır (TA-Lib)."""

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError("period >= 1")
        self.period = period
        self.alpha = 2.0 / (period + 1)
        self._seed: list[float] = []
        self.value: float | None = None

    def update(self, x: float) -> float | None:
        if self.value is None:
            self._seed.append(x)
            if len(self._seed) == self.period:
                self.value = math.fsum(self._seed) / self.period
                self._seed = []
            return self.value
        self.value += self.alpha * (x - self.value)
        return self.value


class WilderAverage:
    """Wilder yumuşatması (RSI/ATR); tohum = ilk ``period`` girdinin ortalaması."""

    def __init__(self, period: int) -> None:
        self.period = period
        self._seed: list[float] = []
        self.value: float | None = None

    def update(self, x: float) -> float | None:
        if self.value is None:
            self._seed.append(x)
            if len(self._seed) == self.period:
                self.value = math.fsum(self._seed) / self.period
                self._seed = []
            return self.value
        self.value = (self.value * (self.period - 1) + x) / self.period
        return self.value


class RSI:
    def __init__(self, period: int = 14) -> None:
        self._gain = WilderAverage(period)
        self._loss = WilderAverage(period)
        self._prev: float | None = None
        self.value: float | None = None

    def update(self, close: float) -> float | None:
        if self._prev is None:
            self._prev = close
            return None
        change = close - self._prev
        self._prev = close
        gain = self._gain.update(max(change, 0.0))
        loss = self._loss.update(max(-change, 0.0))
        if gain is None or loss is None:
            return None
        total = gain + loss
        self.value = 100.0 * gain / total if total > 0 else 0.0
        return self.value


class ATR:
    def __init__(self, period: int = 14) -> None:
        self._avg = WilderAverage(period)
        self._prev_close: float | None = None
        self.value: float | None = None

    def update(self, high: float, low: float, close: float) -> float | None:
        if self._prev_close is None:
            self._prev_close = close
            return None  # TA-Lib: ilk mumun gerçek aralığı tanımsız
        prev = self._prev_close
        self._prev_close = close
        tr = max(high - low, abs(high - prev), abs(low - prev))
        self.value = self._avg.update(tr)
        return self.value


@dataclass(frozen=True)
class MACDValue:
    macd: float
    signal: float
    hist: float


class MACD:
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        if fast >= slow:
            raise ValueError("fast < slow olmalı")
        self._fast = EMA(fast)
        self._slow = EMA(slow)
        self._signal = EMA(signal)
        self.value: MACDValue | None = None

    def update(self, close: float) -> MACDValue | None:
        fast = self._fast.update(close)
        slow = self._slow.update(close)
        if fast is None or slow is None:
            return None
        macd = fast - slow
        signal = self._signal.update(macd)
        if signal is None:
            return None
        self.value = MACDValue(macd, signal, macd - signal)
        return self.value


@dataclass(frozen=True)
class BandsValue:
    middle: float
    upper: float
    lower: float

    @property
    def width(self) -> float:
        """Bant genişliği (orta banda oranla)."""
        return (self.upper - self.lower) / self.middle if self.middle else 0.0

    def percent_b(self, close: float) -> float:
        span = self.upper - self.lower
        return (close - self.lower) / span if span > 0 else 0.5


class Bollinger:
    """Orta bant SMA; standart sapma popülasyon sapmasıdır (TA-Lib ile aynı)."""

    def __init__(self, period: int = 20, k: float = 2.0) -> None:
        self.period = period
        self.k = k
        self._window: deque[float] = deque(maxlen=period)
        self.value: BandsValue | None = None

    def update(self, close: float) -> BandsValue | None:
        self._window.append(close)
        if len(self._window) < self.period:
            return None
        mean = math.fsum(self._window) / self.period
        var = math.fsum((x - mean) ** 2 for x in self._window) / self.period
        std = math.sqrt(var)
        self.value = BandsValue(mean, mean + self.k * std, mean - self.k * std)
        return self.value


class OBV:
    """On-balance volume; ilk değer ilk mumun hacmidir (TA-Lib)."""

    def __init__(self) -> None:
        self._prev: float | None = None
        self.value: float | None = None

    def update(self, close: float, volume: float) -> float:
        if self._prev is None or self.value is None:
            self.value = volume
        elif close > self._prev:
            self.value += volume
        elif close < self._prev:
            self.value -= volume
        self._prev = close
        return self.value


class RollingExtremes:
    """Kayan pencerede en yüksek/en düşük (monoton kuyruk, amortize O(1))."""

    def __init__(self, period: int) -> None:
        self.period = period
        self._i = 0
        self._max: deque[tuple[int, float]] = deque()
        self._min: deque[tuple[int, float]] = deque()

    def update(self, high: float, low: float) -> tuple[float, float] | None:
        i = self._i
        self._i += 1
        while self._max and self._max[-1][1] <= high:
            self._max.pop()
        self._max.append((i, high))
        while self._min and self._min[-1][1] >= low:
            self._min.pop()
        self._min.append((i, low))
        start = i - self.period + 1
        while self._max[0][0] < start:
            self._max.popleft()
        while self._min[0][0] < start:
            self._min.popleft()
        if self._i < self.period:
            return None
        return self._max[0][1], self._min[0][1]


@dataclass(frozen=True)
class StochRSIValue:
    raw: float  # TA-Lib STOCHRSI fastk
    k: float  # raw'ın SMA'sı (TA-Lib fastd; TradingView %K)
    d: float | None  # k'nın SMA'sı (TradingView %D)


class StochRSI:
    def __init__(
        self, rsi_period: int = 14, stoch_period: int = 14, k_period: int = 3, d_period: int = 3
    ) -> None:
        self._rsi = RSI(rsi_period)
        self._window: deque[float] = deque(maxlen=stoch_period)
        self._k = SMA(k_period)
        self._d = SMA(d_period)
        self.value: StochRSIValue | None = None

    def update(self, close: float) -> StochRSIValue | None:
        rsi = self._rsi.update(close)
        if rsi is None:
            return None
        self._window.append(rsi)
        if len(self._window) < (self._window.maxlen or 0):
            return None
        low, high = min(self._window), max(self._window)
        raw = 100.0 * (rsi - low) / (high - low) if high > low else 0.0
        k = self._k.update(raw)
        if k is None:
            return None
        self.value = StochRSIValue(raw, k, self._d.update(k))
        return self.value


@dataclass(frozen=True)
class IchimokuValue:
    tenkan: float
    kijun: float
    # Bulut, ``displacement`` mum önce hesaplanıp bugüne taşınır: şu anki mumun bulutu
    # yalnızca geçmiş veriden oluşur (ileriye bakma yok).
    span_a: float | None
    span_b: float | None
    lagging_ref: float | None  # ``displacement`` mum önceki kapanış (chikou karşılaştırması)


class Ichimoku:
    def __init__(
        self, tenkan: int = 9, kijun: int = 26, span_b: int = 52, displacement: int = 26
    ) -> None:
        self._t = RollingExtremes(tenkan)
        self._k = RollingExtremes(kijun)
        self._b = RollingExtremes(span_b)
        self._displacement = displacement
        self._future_a: deque[float | None] = deque(maxlen=displacement + 1)
        self._future_b: deque[float | None] = deque(maxlen=displacement + 1)
        self._closes: deque[float] = deque(maxlen=displacement + 1)
        self.value: IchimokuValue | None = None

    def update(self, high: float, low: float, close: float) -> IchimokuValue | None:
        t = self._t.update(high, low)
        k = self._k.update(high, low)
        b = self._b.update(high, low)
        tenkan = (t[0] + t[1]) / 2 if t else None
        kijun = (k[0] + k[1]) / 2 if k else None
        a_now = (tenkan + kijun) / 2 if tenkan is not None and kijun is not None else None
        b_now = (b[0] + b[1]) / 2 if b else None
        self._future_a.append(a_now)
        self._future_b.append(b_now)
        self._closes.append(close)
        if tenkan is None or kijun is None:
            return None
        full = len(self._future_a) == self._displacement + 1
        self.value = IchimokuValue(
            tenkan=tenkan,
            kijun=kijun,
            span_a=self._future_a[0] if full else None,
            span_b=self._future_b[0] if full else None,
            lagging_ref=self._closes[0] if len(self._closes) == self._displacement + 1 else None,
        )
        return self.value


class SessionVWAP:
    """UTC gün başında sıfırlanan hacim ağırlıklı ortalama fiyat. Mumun kote hacmi verilirse
    mumun gerçek ortalama fiyatı (kote hacim / hacim), verilmezse tipik fiyat kullanılır."""

    def __init__(self, session_ms: int = 86_400_000) -> None:
        self._session_ms = session_ms
        self._session: int | None = None
        self._pv = 0.0
        self._v = 0.0
        self.value: float | None = None

    def update(
        self,
        open_time_ms: int,
        high: float,
        low: float,
        close: float,
        volume: float,
        quote_volume: float | None = None,
    ) -> float | None:
        session = open_time_ms // self._session_ms
        if session != self._session:
            self._session = session
            self._pv = 0.0
            self._v = 0.0
        if volume > 0:
            if quote_volume is not None and quote_volume > 0:
                self._pv += quote_volume
            else:
                self._pv += (high + low + close) / 3 * volume
            self._v += volume
        self.value = self._pv / self._v if self._v > 0 else None
        return self.value


FIB_RATIOS: tuple[float, ...] = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)


@dataclass(frozen=True)
class FibonacciValue:
    swing_high: float
    swing_low: float
    trend_up: bool  # dip tepeden önce geldiyse yükseliş geri çekilmesi
    levels: dict[float, float]
    position: float  # kapanışın aralıktaki yeri (0 = dip, 1 = tepe)
    nearest_ratio: float
    nearest_distance_pct: float


class Fibonacci:
    """Son ``period`` mumun tepe ve dibinden geri çekilme seviyeleri."""

    def __init__(self, period: int = 100) -> None:
        self.period = period
        self._bars: deque[tuple[int, float, float]] = deque(maxlen=period)
        self._i = 0
        self.value: FibonacciValue | None = None

    def update(self, high: float, low: float, close: float) -> FibonacciValue | None:
        self._bars.append((self._i, high, low))
        self._i += 1
        if len(self._bars) < self.period:
            return None
        hi_i, hi = max(((i, h) for i, h, _ in self._bars), key=lambda x: x[1])
        lo_i, lo = min(((i, low_) for i, _, low_ in self._bars), key=lambda x: x[1])
        span = hi - lo
        if span <= 0:
            return None
        trend_up = lo_i < hi_i
        # Yükselişte seviyeler tepeden aşağı ölçülür (0 = tepe), düşüşte dipten yukarı.
        levels = {r: (hi - span * r) if trend_up else (lo + span * r) for r in FIB_RATIOS}
        nearest = min(levels.items(), key=lambda kv: abs(close - kv[1]))
        self.value = FibonacciValue(
            swing_high=hi,
            swing_low=lo,
            trend_up=trend_up,
            levels=levels,
            position=(close - lo) / span,
            nearest_ratio=nearest[0],
            nearest_distance_pct=(close / nearest[1] - 1) * 100 if nearest[1] else 0.0,
        )
        return self.value
