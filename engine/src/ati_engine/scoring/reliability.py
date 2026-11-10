"""Kendini ayarlayan strateji ağırlıkları (güvenilirlik).

Her stratejinin sanal yarışmadaki (gerçek zamanlı, gerçek fiyatlarla, komisyon ve kayma dahil)
kapanmış işlemlerinin **R katı** (net kâr/zarar ÷ başlangıç riski) ortalaması, az sayıda işlemde
aşırı tepki vermemesi için sıfıra doğru büzülür (Bayes küçültmesi):

    büzülmüş ortalama R = toplam R / (işlem sayısı + ÖNSEL)

Çarpan = 1 + 2 × büzülmüş ortalama R, [0,4 ; 1,4] aralığında sınırlanır. En az ``MIN_TRADES``
işlem olmadan çarpan 1'dir (yeterli kanıt yok). Böylece sanal sonuçlarda tutarlı biçimde zarar
eden stratejinin sinyali fırsat puanında daha az, tutarlı biçimde iyi gidenin sinyali daha çok
sayılır. Hiçbir strateji tamamen kapatılmaz ve bu bir kâr garantisi değildir; geçmiş sanal
sonuçlar gelecekteki sonuçları göstermez.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

PRIOR_TRADES = 20
MIN_TRADES = 10
LOW, HIGH = 0.4, 1.4


@dataclass(frozen=True)
class Reliability:
    multiplier: float
    trades: int
    avg_r: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def reliability(r_multiples: Iterable[float]) -> Reliability:
    values = [r for r in r_multiples if r == r]  # NaN dışarıda
    n = len(values)
    if n == 0:
        return Reliability(1.0, 0, None)
    avg = sum(values) / n
    if n < MIN_TRADES:
        return Reliability(1.0, n, round(avg, 4))
    shrunk = sum(values) / (n + PRIOR_TRADES)
    multiplier = max(LOW, min(HIGH, 1.0 + 2.0 * shrunk))
    return Reliability(round(multiplier, 4), n, round(avg, 4))
