"""Artımlı (O(1) / O(log n)) güncellenen istatistik yapıları.

Tarayıcı saniyede binlerce işlem ve yüzlerce mum güncellemesi alır; her olayda ya da her
saniyelik turda geçmişi yeniden toplamak yerine yalnızca değişen kısım güncellenir:

* ``RollingStats``: sabit uzunluklu pencerede toplam ve kareler toplamı (ortalama, standart
  sapma, z-skor). Yeni değer eklenince en eski değer düşülür.
* ``FlowWindows``: saniyelik kovalarda agresif alış/satış hacmi; 60 ve 300 saniyelik
  pencere toplamları her zaman hazır tutulur. Zaman ilerledikçe pencereden çıkan kova düşülür.
* ``PriceTrail``: işlem olan her saniyenin son fiyatı; geçmiş bir andaki fiyat ikili arama ile
  bulunur (az işlem gören coinlerde de hızlı).
"""

from __future__ import annotations

import math
from array import array
from bisect import bisect_right
from collections import deque


class RollingStats:
    """Son ``size`` değerin ortalaması ve standart sapması (kayan pencere)."""

    __slots__ = ("_size", "_sum", "_sumsq", "_values")

    def __init__(self, size: int) -> None:
        if size < 2:
            raise ValueError("Pencere en az 2 olmalı")
        self._size = size
        self._values: deque[float] = deque()
        self._sum = 0.0
        self._sumsq = 0.0

    def __len__(self) -> int:
        return len(self._values)

    def push(self, value: float) -> None:
        self._values.append(value)
        self._sum += value
        self._sumsq += value * value
        if len(self._values) > self._size:
            old = self._values.popleft()
            self._sum -= old
            self._sumsq -= old * old

    @property
    def mean(self) -> float:
        n = len(self._values)
        return self._sum / n if n else 0.0

    @property
    def std(self) -> float:
        n = len(self._values)
        if n < 2:
            return 0.0
        variance = (self._sumsq - self._sum * self._sum / n) / (n - 1)
        return math.sqrt(variance) if variance > 0 else 0.0

    def zscore(self, value: float, *, min_std: float = 1e-9) -> float:
        return (value - self.mean) / max(self.std, min_std)


class FlowWindows:
    """Agresif alış/satış hacmi (quote) için 60 sn ve 300 sn kayan pencereler."""

    WINDOWS = (60, 300)
    __slots__ = ("_advanced", "_buy", "_n", "_sec", "_sell", "_sums", "first_sec")

    def __init__(self, ring_seconds: int = 330) -> None:
        if ring_seconds <= max(self.WINDOWS):
            raise ValueError("Halka en büyük pencereden uzun olmalı")
        self._n = ring_seconds
        self._sec = array("q", [-1]) * ring_seconds
        self._buy = array("d", [0.0]) * ring_seconds
        self._sell = array("d", [0.0]) * ring_seconds
        self._sums = {w: [0.0, 0.0] for w in self.WINDOWS}
        self._advanced = -1
        self.first_sec = -1  # bu sembolün ilk işlem saniyesi (pencere kapsamı için)

    def coverage(self, now_sec: int) -> int:
        """Kaç saniyelik akış verisi var (pencere dolmadan karar vermemek için)."""
        return 0 if self.first_sec < 0 else now_sec - self.first_sec

    def add(self, sec: int, quote: float, *, taker_buy: bool) -> None:
        if self.first_sec < 0 or sec < self.first_sec:
            self.first_sec = sec
        if self._advanced < 0:
            self._advanced = sec
        if sec <= self._advanced - max(self.WINDOWS):
            return  # tüm pencerelerden eski
        i = sec % self._n
        if self._sec[i] != sec:
            if self._sec[i] >= 0:
                # Halkada yeniden kullanılan kova: hâlâ pencere içindeyse düş (normalde olmaz).
                self._expire_bucket(i)
            self._sec[i] = sec
            self._buy[i] = 0.0
            self._sell[i] = 0.0
        if taker_buy:
            self._buy[i] += quote
        else:
            self._sell[i] += quote
        for window, sums in self._sums.items():
            if sec > self._advanced - window:
                sums[0 if taker_buy else 1] += quote

    def _expire_bucket(self, i: int) -> None:
        old = self._sec[i]
        for window, sums in self._sums.items():
            if old > self._advanced - window:
                sums[0] -= self._buy[i]
                sums[1] -= self._sell[i]

    def advance(self, now_sec: int) -> None:
        """Pencereleri ``now_sec`` anına getirir; çıkan kovaları toplamlardan düşer."""
        if self._advanced < 0:
            self._advanced = now_sec
            return
        if now_sec <= self._advanced:
            return
        steps = now_sec - self._advanced
        if steps >= max(self.WINDOWS):
            # Büyük sıçrama (uzun süre işlem görmeyen sembol): toplamları sıfırlamak yerine
            # halkadaki geçerli kovalardan yeniden hesapla; pencere içindeki yeni işlemler korunur.
            self._advanced = now_sec
            self._recompute()
            return
        for window, sums in self._sums.items():
            for offset in range(steps):
                expiring = self._advanced - window + 1 + offset
                if expiring < 0:
                    continue
                i = expiring % self._n
                if self._sec[i] == expiring:
                    sums[0] -= self._buy[i]
                    sums[1] -= self._sell[i]
        self._advanced = now_sec

    def _recompute(self) -> None:
        for window, sums in self._sums.items():
            low = self._advanced - window
            buy = sell = 0.0
            for i in range(self._n):
                if self._sec[i] > low:
                    buy += self._buy[i]
                    sell += self._sell[i]
            sums[0], sums[1] = buy, sell

    def totals(self, window: int) -> tuple[float, float]:
        buy, sell = self._sums[window]
        # Kayan nokta birikimi küçük negatiflere yol açabilir.
        return max(buy, 0.0), max(sell, 0.0)


class PriceTrail:
    """İşlem olan her saniyenin son fiyatı (son ``keep_seconds`` saniye)."""

    __slots__ = ("_keep", "_prices", "_secs", "_start")

    def __init__(self, keep_seconds: int = 960) -> None:
        self._keep = keep_seconds
        self._secs: list[int] = []
        self._prices: list[float] = []
        self._start = 0

    @property
    def latest(self) -> tuple[int, float] | None:
        if len(self._secs) == self._start:
            return None
        return self._secs[-1], self._prices[-1]

    def update(self, sec: int, price: float) -> None:
        if self._secs and len(self._secs) > self._start:
            last = self._secs[-1]
            if sec == last:
                self._prices[-1] = price
                return
            if sec < last:
                return  # sırası dışı (geri alınmış) işlem fiyat izini değiştirmez
        self._secs.append(sec)
        self._prices.append(price)
        cutoff = sec - self._keep
        while self._start < len(self._secs) and self._secs[self._start] < cutoff:
            self._start += 1
        if self._start > 512:
            del self._secs[: self._start]
            del self._prices[: self._start]
            self._start = 0

    def price_at(self, sec: int) -> float | None:
        """``sec`` anında geçerli olan fiyat (o ana kadarki son işlem). Bilinmiyorsa None."""
        idx = bisect_right(self._secs, sec, lo=self._start) - 1
        if idx < self._start:
            return None
        return self._prices[idx]


def pct_change(new: float, old: float | None) -> float | None:
    if old is None or old <= 0:
        return None
    return (new / old - 1.0) * 100.0


def imbalance(buy: float, sell: float) -> float | None:
    total = buy + sell
    return None if total <= 0 else (buy - sell) / total
