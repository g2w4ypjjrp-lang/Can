"""Benzer piyasa koşulu arama.

Son ``window`` mumluk fiyat yolu (log fiyat, z-normalize edilmiş: yalnızca şekil) geçmişteki
tüm pencerelerle karşılaştırılır; oynaklığı çok farklı pencereler elenir. En yakın eşleşmelerin
**sonrasında** fiyatın ne yaptığı (ileri getiriler) özetlenir.

Bu bir istatistiksel benzerliktir: geçmişte benzer görünen dönemlerin sonucunu gösterir,
gelecekteki fiyatı **garanti etmez**. Sonuçlar örnek sayısıyla birlikte yorumlanmalıdır.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view


@dataclass(frozen=True)
class Match:
    end_index: int
    start_time_ms: int
    end_time_ms: int
    distance: float
    forward_pct: dict[int, float]


@dataclass(frozen=True)
class ForwardStat:
    horizon: int
    n: int
    mean_pct: float
    median_pct: float
    positive_rate: float


@dataclass
class SimilarityResult:
    window: int
    query_end_index: int
    query_end_time_ms: int
    candidates: int
    matches: list[Match] = field(default_factory=list)
    forward: list[ForwardStat] = field(default_factory=list)


def _znorm(rows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = rows.mean(axis=1, keepdims=True)
    std = rows.std(axis=1, keepdims=True)
    valid = std[:, 0] > 1e-12
    safe = np.where(std > 1e-12, std, 1.0)
    return (rows - mean) / safe, valid


def find_similar(
    times_ms: Sequence[int],
    closes: Sequence[float],
    *,
    window: int = 48,
    top_k: int = 10,
    horizons: Sequence[int] = (6, 24),
    query_end: int | None = None,
    vol_tolerance: float = 2.0,
    chunk: int = 50_000,
) -> SimilarityResult:
    """``query_end`` (varsayılan: son mum) ile biten pencereye en çok benzeyen geçmiş
    pencereleri bulur. Eşleşmenin ileri getirisi tamamen bilinmeli ve eşleşme sorgu
    penceresiyle çakışmamalıdır; eşleşmeler birbirinden en az ``window`` mum uzaktadır."""
    if window < 8:
        raise ValueError("window en az 8 olmalı")
    prices = np.asarray(closes, dtype=np.float64)
    if np.any(prices <= 0):
        raise ValueError("Fiyatlar pozitif olmalı")
    n = len(prices)
    q_end = n - 1 if query_end is None else query_end
    if q_end < window - 1 or q_end >= n:
        raise ValueError("Sorgu penceresi için yeterli veri yok")
    max_h = max(horizons)
    log_p = np.log(prices)
    query = log_p[q_end - window + 1 : q_end + 1][None, :]
    zq, q_valid = _znorm(query)
    q_vol = float(np.std(np.diff(query[0])))
    result = SimilarityResult(
        window=window,
        query_end_index=q_end,
        query_end_time_ms=int(times_ms[q_end]),
        candidates=0,
    )
    if not q_valid[0]:
        return result

    # Aday pencerenin bitişi e: e + max_h <= q_end (sonrası bilinir) ve e < q_start (çakışmaz).
    last_end = min(q_end - max_h, q_end - window)
    if last_end < window - 1:
        return result
    ends: list[np.ndarray] = []
    dists: list[np.ndarray] = []
    for start in range(0, last_end - window + 2, chunk):
        stop = min(start + chunk, last_end - window + 2)  # pencere başlangıç indeksleri
        segment = log_p[start : stop + window - 1]
        rows = sliding_window_view(segment, window)
        z, valid = _znorm(rows)
        dist = np.sqrt(np.sum((z - zq) ** 2, axis=1))
        vols = np.std(np.diff(rows, axis=1), axis=1)
        if q_vol > 0:
            ratio = vols / q_vol
            valid &= (ratio <= vol_tolerance) & (ratio >= 1 / vol_tolerance)
        dist = np.where(valid, dist, np.inf)
        ends.append(np.arange(start, stop) + window - 1)
        dists.append(dist)
    all_ends = np.concatenate(ends)
    all_dists = np.concatenate(dists)
    result.candidates = int(np.isfinite(all_dists).sum())

    order = np.argsort(all_dists, kind="stable")
    chosen: list[int] = []
    for idx in order:
        if not np.isfinite(all_dists[idx]) or len(chosen) >= top_k:
            break
        end = int(all_ends[idx])
        if any(abs(end - c) < window for c in chosen):
            continue
        chosen.append(end)
        forward = {h: round(float((prices[end + h] / prices[end] - 1) * 100), 4) for h in horizons}
        result.matches.append(
            Match(
                end_index=end,
                start_time_ms=int(times_ms[end - window + 1]),
                end_time_ms=int(times_ms[end]),
                distance=round(float(all_dists[idx]), 4),
                forward_pct=forward,
            )
        )
    for h in horizons:
        values = np.array([m.forward_pct[h] for m in result.matches])
        if len(values):
            result.forward.append(
                ForwardStat(
                    horizon=h,
                    n=len(values),
                    mean_pct=round(float(values.mean()), 4),
                    median_pct=round(float(np.median(values)), 4),
                    positive_rate=round(float((values > 0).mean()), 4),
                )
            )
    return result
