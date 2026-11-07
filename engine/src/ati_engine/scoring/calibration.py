"""Puan kalibrasyonu: aynı puanlama geçmiş mumlar üzerinde mum mum çalıştırılır ve her puan
aralığının ``h`` mum sonraki **maliyet sonrası** yönlü getirisi ölçülür.

Tarihsel çalıştırmada canlıya özgü bileşenler (balina, emir defteri) yoktur; bu fark tabloda
belirtilir. Sonuçlar geçmişi anlatır, geleceği garanti etmez.
"""

from __future__ import annotations

import itertools
import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.stats import spearmanr

from ati_engine.history.archive import INTERVAL_MS
from ati_engine.ml.dataset import _bar, _futures
from ati_engine.scoring.score import OpportunityScorer, ScoreInputs
from ati_engine.strategies.base import MarketKind
from ati_engine.strategies.book import StrategyBook

BUCKETS: tuple[float, ...] = (0, 20, 40, 60, 80, 100)


@dataclass(frozen=True)
class ScoredBar:
    time_ms: int
    symbol: str
    direction: int
    score: float
    gross_return_pct: float
    cost_pct: float

    @property
    def net_return_pct(self) -> float:
        return self.gross_return_pct - self.cost_pct


def evaluate_history(
    rows: Sequence[Sequence[Any]],
    *,
    market: MarketKind,
    symbol: str,
    interval: str,
    horizon: int,
    scorer: OpportunityScorer,
    futures: bool = False,
) -> list[ScoredBar]:
    """``rows``: (open_time, open, high, low, close, volume, quote_volume, taker_buy_quote
    [, funding, oi, top_ls, global_ls, taker_ls]) zamana göre sıralı."""
    step = INTERVAL_MS[interval]
    day_bars = max(1, 86_400_000 // step)
    book = StrategyBook(market, symbol)
    quote_window: deque[float] = deque(maxlen=day_bars)
    result: list[ScoredBar] = []
    for i, row in enumerate(rows):
        quote_window.append(float(row[6]))
        update = book.update(_bar(row), _futures(row) if futures else None)
        if update is None:
            continue
        j = i + horizon
        if j >= len(rows) or int(rows[j][0]) - int(row[0]) != horizon * step:
            continue
        opportunity = scorer.score(
            ScoreInputs(
                market=market,
                symbol=symbol,
                interval=interval,
                interval_hours=step / 3_600_000,
                horizon_bars=horizon,
                snapshot=update.snapshot,
                signals=update.signals,
                levels=update.levels,
                quote_volume_24h=sum(quote_window) if len(quote_window) == day_bars else None,
            )
        )
        if opportunity.direction == "none":
            continue
        d = 1 if opportunity.direction == "long" else -1
        c0, c1 = float(row[4]), float(rows[j][4])
        result.append(
            ScoredBar(
                time_ms=int(row[0]),
                symbol=symbol,
                direction=d,
                score=opportunity.score,
                gross_return_pct=(c1 / c0 - 1) * 100 * d,
                cost_pct=opportunity.cost.total_pct,
            )
        )
    return result


def calibration_table(
    scored: Sequence[ScoredBar], *, source: str, buckets: Sequence[float] = BUCKETS
) -> dict[str, Any]:
    if not scored:
        return {"source": source, "n": 0, "buckets": [], "spearman": None}
    scores = np.array([b.score for b in scored])
    net = np.array([b.net_return_pct for b in scored])
    gross = np.array([b.gross_return_pct for b in scored])
    rows = []
    for lo, hi in itertools.pairwise(buckets):
        mask = (scores >= lo) & ((scores < hi) if hi < buckets[-1] else (scores <= hi))
        n = int(mask.sum())
        rows.append(
            {
                "low": lo,
                "high": hi,
                "n": n,
                "hit_rate": round(float((net[mask] > 0).mean()), 4) if n else None,
                "mean_net_return_pct": round(float(net[mask].mean()), 4) if n else None,
                "mean_gross_return_pct": round(float(gross[mask].mean()), 4) if n else None,
            }
        )
    rho = spearmanr(scores, net).statistic if len(scored) > 2 else math.nan
    return {
        "source": source,
        "n": len(scored),
        "buckets": rows,
        "spearman": None if math.isnan(rho) else round(float(rho), 4),
        "all_mean_net_return_pct": round(float(net.mean()), 4),
        "all_hit_rate": round(float((net > 0).mean()), 4),
    }
