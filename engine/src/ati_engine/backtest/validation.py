"""Aşırı uyuma karşı doğrulama: yürüyen pencere ve arındırılmış (purged) k-katlı çapraz doğrulama.

**Yürüyen pencere:** her pencerede parametreler yalnızca *geçmiş* eğitim döneminde seçilir ve
hemen ardından gelen *görülmemiş* test döneminde uygulanır. Test dönemleri birleştirilerek tek
bir örneklem dışı sermaye eğrisi elde edilir (portföy sürekliliği korunur).

**Arındırılmış k-kat:** zaman ekseni k parçaya bölünür. Her test parçası için parametre, diğer
parçalardaki işlemlerle seçilir; test parçasıyla (± ambargo) zamanda örtüşen işlemler seçimden
çıkarılır (sızıntı önleme). Ayrıca "aşırı uyum olasılığı" (PBO, basitleştirilmiş): seçilen
parametrenin test performansının, tüm adayların test performansının medyanının altında kaldığı
katların oranı. Yüksek değer, seçimin gerçek bir üstünlük değil şans olduğunu gösterir.

Kayıtlar (``BarRecord``) göstergeleri tüm geçmişten, yalnızca geçmiş veriyle hesapladığı için
dönemlere bölmek ileriye bakma oluşturmaz.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from ati_engine.backtest.engine import (
    BacktestConfig,
    BacktestResult,
    BarRecord,
    EntryDecision,
    EntryRule,
    Trade,
    run_backtest,
)
from ati_engine.backtest.metrics import compute_metrics

Params = dict[str, Any]
RuleFactory = Callable[[Params], EntryRule]


def _objective(metrics: Mapping[str, Any], name: str, min_trades: int) -> float:
    if (metrics.get("trades") or 0) < min_trades:
        return -math.inf
    value = metrics.get(name)
    if value is None:
        return -math.inf if name != "profit_factor" else math.inf
    return float(value)


def slice_records(
    data: Mapping[str, Sequence[BarRecord]], start_ms: int, end_ms: int
) -> dict[str, list[BarRecord]]:
    return {s: [r for r in recs if start_ms <= r.time_ms < end_ms] for s, recs in data.items()}


def _timeline(data: Mapping[str, Sequence[BarRecord]]) -> list[int]:
    """Isınması tamamlanmış (görünümü olan) mumların zamanları."""
    return sorted({r.time_ms for recs in data.values() for r in recs if r.snapshot is not None})


@dataclass
class SwitchingRule:
    """Zamana göre farklı parametrelerle oluşturulmuş kurallar arasında geçiş yapar."""

    windows: list[tuple[int, int, EntryRule]]
    name: str = "yürüyen_pencere"

    def decide(
        self, symbol: str, record: BarRecord, quote_volume_24h: float | None
    ) -> EntryDecision | None:
        for start, end, rule in self.windows:
            if start <= record.time_ms < end:
                return rule.decide(symbol, record, quote_volume_24h)
        return None


@dataclass
class WalkForwardWindow:
    train_start_ms: int
    train_end_ms: int
    test_start_ms: int
    test_end_ms: int
    params: Params
    train_objective: float | None
    train_trades: int


@dataclass
class WalkForwardResult:
    objective: str
    windows: list[WalkForwardWindow]
    oos: BacktestResult
    oos_metrics: dict[str, Any]
    mean_train_objective: float | None
    param_changes: int
    candidates: int


def walk_forward(
    data: Mapping[str, Sequence[BarRecord]],
    *,
    make_rule: RuleFactory,
    grid: Sequence[Params],
    config: BacktestConfig,
    interval_ms: int,
    train_bars: int,
    test_bars: int,
    objective: str = "sharpe",
    min_trades: int = 10,
) -> WalkForwardResult:
    if not grid:
        raise ValueError("Parametre ızgarası boş")
    times = _timeline(data)
    if len(times) < train_bars + test_bars:
        raise ValueError("Yürüyen pencere için yeterli veri yok")
    windows: list[WalkForwardWindow] = []
    switching: list[tuple[int, int, EntryRule]] = []
    for start in range(0, len(times) - train_bars - test_bars + 1, test_bars):
        train_start, train_end = times[start], times[start + train_bars]
        test_end_index = start + train_bars + test_bars
        test_end = times[test_end_index] if test_end_index < len(times) else times[-1] + 1
        train_data = slice_records(data, train_start, train_end)
        best: tuple[float, Params, int] | None = None
        for params in grid:
            result = run_backtest(train_data, make_rule(params), config, interval_ms=interval_ms)
            metrics = compute_metrics(result)
            score = _objective(metrics, objective, min_trades)
            if best is None or score > best[0]:
                best = (score, params, metrics["trades"])
        if best is None:  # pragma: no cover - ızgara boş değilse olamaz
            raise ValueError("Parametre seçilemedi")
        windows.append(
            WalkForwardWindow(
                train_start_ms=train_start,
                train_end_ms=train_end,
                test_start_ms=train_end,
                test_end_ms=test_end,
                params=best[1],
                train_objective=None if math.isinf(best[0]) else round(best[0], 4),
                train_trades=best[2],
            )
        )
        switching.append((train_end, test_end, make_rule(best[1])))
    oos_start, oos_end = windows[0].test_start_ms, windows[-1].test_end_ms
    oos = run_backtest(
        slice_records(data, oos_start, oos_end),
        SwitchingRule(switching),
        config,
        interval_ms=interval_ms,
    )
    oos_metrics = compute_metrics(oos)
    train_scores = [w.train_objective for w in windows if w.train_objective is not None]
    return WalkForwardResult(
        objective=objective,
        windows=windows,
        oos=oos,
        oos_metrics=oos_metrics,
        mean_train_objective=round(float(np.mean(train_scores)), 4) if train_scores else None,
        param_changes=sum(1 for a, b in itertools.pairwise(windows) if a.params != b.params),
        candidates=len(grid),
    )


# --- Arındırılmış k-katlı çapraz doğrulama ------------------------------------------------------


def _trade_score(trades: Sequence[Trade], objective: str, min_trades: int) -> float:
    if len(trades) < min_trades:
        return -math.inf
    pnl = np.array([t.net_pnl for t in trades])
    if objective == "profit_factor":
        loss = -pnl[pnl < 0].sum()
        return float(pnl[pnl > 0].sum() / loss) if loss > 0 else math.inf
    if objective == "mean_r":
        return float(np.mean([t.r_multiple for t in trades]))
    return float(pnl.sum())  # net_pnl


@dataclass
class FoldResult:
    fold: int
    test_start_ms: int
    test_end_ms: int
    params: Params
    train_score: float | None
    test_score: float | None
    test_trades: int
    below_median: bool | None


@dataclass
class PurgedCVResult:
    objective: str
    folds: list[FoldResult]
    oos_trades: list[Trade] = field(default_factory=list)
    oos_summary: dict[str, Any] = field(default_factory=dict)
    pbo: float | None = None
    purged_trades: int = 0


def purged_kfold(
    data: Mapping[str, Sequence[BarRecord]],
    *,
    make_rule: RuleFactory,
    grid: Sequence[Params],
    config: BacktestConfig,
    interval_ms: int,
    folds: int = 5,
    embargo_bars: int = 24,
    objective: str = "mean_r",
    min_trades: int = 10,
) -> PurgedCVResult:
    if not grid:
        raise ValueError("Parametre ızgarası boş")
    times = _timeline(data)
    if len(times) < folds * 10:
        raise ValueError("Çapraz doğrulama için yeterli veri yok")
    bounds = [times[int(i * len(times) / folds)] for i in range(folds)] + [times[-1] + 1]
    embargo = embargo_bars * interval_ms
    # Her aday için tek bir tam çalıştırma; işlemler katlara zamana göre ayrılır.
    runs = [run_backtest(data, make_rule(p), config, interval_ms=interval_ms) for p in grid]
    result = PurgedCVResult(objective=objective, folds=[])
    below: list[bool] = []
    for k in range(folds):
        a, b = bounds[k], bounds[k + 1]

        def in_test(t: Trade, a: int = a, b: int = b) -> bool:
            return a <= t.entry_time_ms < b

        def overlaps(t: Trade, a: int = a, b: int = b) -> bool:
            exit_ms = t.exit_time_ms if t.exit_time_ms is not None else t.entry_time_ms
            return exit_ms >= a - embargo and t.entry_time_ms < b + embargo

        train_scores = []
        test_scores = []
        for run in runs:
            train = [t for t in run.trades if not overlaps(t)]
            result.purged_trades += sum(1 for t in run.trades if overlaps(t) and not in_test(t))
            train_scores.append(_trade_score(train, objective, min_trades))
            test_scores.append(_trade_score([t for t in run.trades if in_test(t)], objective, 1))
        best = int(np.argmax(train_scores))
        finite = [s for s in test_scores if math.isfinite(s)]
        median = float(np.median(finite)) if finite else None
        chosen = test_scores[best]
        flag = None
        if median is not None and math.isfinite(chosen):
            flag = chosen < median
            below.append(flag)
        test_trades = [t for t in runs[best].trades if in_test(t)]
        result.oos_trades.extend(test_trades)
        result.folds.append(
            FoldResult(
                fold=k,
                test_start_ms=a,
                test_end_ms=b,
                params=grid[best],
                train_score=round(train_scores[best], 4)
                if math.isfinite(train_scores[best])
                else None,
                test_score=round(chosen, 4) if math.isfinite(chosen) else None,
                test_trades=len(test_trades),
                below_median=flag,
            )
        )
    pnl = np.array([t.net_pnl for t in result.oos_trades])
    loss = -pnl[pnl < 0].sum() if len(pnl) else 0.0
    result.oos_summary = {
        "trades": len(result.oos_trades),
        "win_rate": round(float((pnl > 0).mean()), 4) if len(pnl) else None,
        "profit_factor": round(float(pnl[pnl > 0].sum() / loss), 4) if loss > 0 else None,
        "net_pnl": round(float(pnl.sum()), 4) if len(pnl) else 0.0,
        "mean_r": round(float(np.mean([t.r_multiple for t in result.oos_trades])), 4)
        if result.oos_trades
        else None,
    }
    result.pbo = round(sum(below) / len(below), 4) if below else None
    return result


def config_for_window(config: BacktestConfig, start_ms: int, end_ms: int) -> BacktestConfig:
    return replace(config, trade_start_ms=start_ms, trade_end_ms=end_ms)
