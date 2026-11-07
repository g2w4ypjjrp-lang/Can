"""LightGBM ile yürüyen pencere (walk-forward) eğitimi ve dürüst örneklem dışı değerlendirme.

* Zaman sırası korunur; test dönemi her zaman eğitimden **sonradır**.
* Eğitim ile test arasında ``embargo`` (en az etiket ufku kadar) boşluk bırakılır: etiketleri
  test dönemine taşan eğitim örnekleri bilgi sızdıramaz.
* Erken durdurma, eğitim döneminin son kısmıyla (yine ambargolu) yapılır; test verisi model
  seçiminde kullanılmaz.
* Raporlanan metrikler yalnızca örneklem dışı tahminlerden hesaplanır: AUC, log kaybı, Brier,
  kalibrasyon tablosu ve en yüksek olasılıklı %10'luk dilimin maliyet sonrası ortalama getirisi.

Metrikler geçmişteki performansı ölçer; gelecekteki kazancı garanti etmez.
"""

from __future__ import annotations

import itertools
import os
from dataclasses import dataclass, field
from typing import Any

import lightgbm as lgb
import numpy as np
from scipy.stats import rankdata

from ati_engine.ml.dataset import Dataset, Side

DEFAULT_PARAMS: dict[str, Any] = {
    "objective": "binary",
    "learning_rate": 0.03,
    "num_leaves": 15,
    "min_data_in_leaf": 200,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "verbosity": -1,
    "seed": 42,
    "deterministic": True,
    "force_row_wise": True,
    # Eğitim kullanıcının bilgisayarında, işlem motoruyla birlikte çalışır: tüm çekirdekler
    # kullanılmaz.
    "num_threads": max(1, (os.cpu_count() or 2) // 2),
}


def auc(y: np.ndarray, p: np.ndarray) -> float:
    """Sıra tabanlı AUC (Mann-Whitney), eşit değerlerde ortalama sıra."""
    pos = int(y.sum())
    neg = len(y) - pos
    if pos == 0 or neg == 0:
        return float("nan")
    ranks = rankdata(p)
    return float((ranks[y == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


def log_loss(y: np.ndarray, p: np.ndarray) -> float:
    q = np.clip(p, 1e-7, 1 - 1e-7)
    return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def calibration_table(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict[str, float]]:
    edges = np.linspace(0, 1, bins + 1)
    table = []
    for lo, hi in itertools.pairwise(edges):
        mask = (p >= lo) & (p < hi if hi < 1 else p <= hi)
        if mask.sum() == 0:
            continue
        table.append(
            {
                "bin_low": round(float(lo), 2),
                "bin_high": round(float(hi), 2),
                "n": int(mask.sum()),
                "mean_predicted": round(float(p[mask].mean()), 4),
                "observed_rate": round(float(y[mask].mean()), 4),
            }
        )
    return table


def walk_forward_splits(
    times: np.ndarray, *, folds: int, embargo_ms: int, min_train_fraction: float = 0.4
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Genişleyen eğitim penceresi; test dönemleri zaman ekseninin son kısmını eşit böler."""
    if folds < 1:
        raise ValueError("folds >= 1")
    t0, t1 = int(times.min()), int(times.max()) + 1
    start = t0 + int((t1 - t0) * min_train_fraction)
    bounds = np.linspace(start, t1, folds + 1).astype(np.int64)
    splits = []
    for a, b in itertools.pairwise(bounds):
        train = np.where(times < a - embargo_ms)[0]
        test = np.where((times >= a) & (times < b))[0]
        if len(train) and len(test):
            splits.append((train, test))
    return splits


@dataclass
class FoldReport:
    fold: int
    train_end_ms: int
    test_start_ms: int
    test_end_ms: int
    n_train: int
    n_test: int
    best_iteration: int
    auc: float
    log_loss: float
    brier: float
    base_rate: float


@dataclass
class TrainReport:
    side: Side
    threshold: float
    cost: float
    rows: int
    positive_rate: float
    folds: list[FoldReport] = field(default_factory=list)
    oos: dict[str, Any] = field(default_factory=dict)
    feature_importance: dict[str, float] = field(default_factory=dict)
    final_iterations: int = 0


def _fit(
    X: np.ndarray, y: np.ndarray, times: np.ndarray, params: dict[str, Any], embargo_ms: int
) -> lgb.Booster:
    """Eğitim döneminin son %15'i (ambargolu) erken durdurma için ayrılır."""
    cut = int(np.quantile(times, 0.85))
    fit_idx = np.where(times < cut - embargo_ms)[0]
    val_idx = np.where(times >= cut)[0]
    if len(fit_idx) < 500 or len(val_idx) < 100:
        fit_idx, val_idx = np.arange(len(y)), np.arange(0)
    train_set = lgb.Dataset(X[fit_idx], y[fit_idx], free_raw_data=False)
    if len(val_idx):
        valid = lgb.Dataset(X[val_idx], y[val_idx], reference=train_set)
        return lgb.train(
            params,
            train_set,
            num_boost_round=1500,
            valid_sets=[valid],
            callbacks=[lgb.early_stopping(50, verbose=False)],
        )
    return lgb.train(params, train_set, num_boost_round=200)


def train_model(
    data: Dataset,
    *,
    side: Side,
    cost: float,
    threshold: float | None = None,
    folds: int = 5,
    params: dict[str, Any] | None = None,
) -> tuple[lgb.Booster, TrainReport]:
    """``cost``: gidiş-dönüş işlem maliyeti (log getiri cinsinden, ör. 0.002 = %0,2).
    ``threshold`` verilmezse maliyet eşik olarak kullanılır: model "maliyeti karşılayacak
    hareket olasılığını" öğrenir."""
    labeled = data.labeled()
    if len(labeled) < 2_000:
        raise ValueError(f"Eğitim için yetersiz veri: {len(labeled)} etiketli satır")
    thr = cost if threshold is None else threshold
    y = labeled.labels(side, thr)
    X, times = labeled.X, labeled.times
    step = int(np.median(np.diff(np.unique(times)))) if len(np.unique(times)) > 1 else 1
    embargo_ms = (data.horizon + 1) * step
    cfg = {**DEFAULT_PARAMS, **(params or {})}
    report = TrainReport(
        side=side, threshold=thr, cost=cost, rows=len(y), positive_rate=float(y.mean())
    )
    oos_pred = np.full(len(y), np.nan)
    best_iterations = []
    for k, (train_idx, test_idx) in enumerate(
        walk_forward_splits(times, folds=folds, embargo_ms=embargo_ms)
    ):
        booster = _fit(X[train_idx], y[train_idx], times[train_idx], cfg, embargo_ms)
        best = booster.best_iteration or booster.current_iteration()
        best_iterations.append(best)
        pred = np.asarray(booster.predict(X[test_idx], num_iteration=best), dtype=np.float64)
        oos_pred[test_idx] = pred
        yt = y[test_idx]
        report.folds.append(
            FoldReport(
                fold=k,
                train_end_ms=int(times[train_idx].max()),
                test_start_ms=int(times[test_idx].min()),
                test_end_ms=int(times[test_idx].max()),
                n_train=len(train_idx),
                n_test=len(test_idx),
                best_iteration=int(best),
                auc=round(auc(yt, pred), 4),
                log_loss=round(log_loss(yt, pred), 4),
                brier=round(brier(yt, pred), 4),
                base_rate=round(float(yt.mean()), 4),
            )
        )
    mask = ~np.isnan(oos_pred)
    if mask.sum():
        yo, po = y[mask], oos_pred[mask]
        direction = 1.0 if side == "long" else -1.0
        directional = labeled.forward_return[mask] * direction
        top = po >= np.quantile(po, 0.9)
        base_rate = float(yo.mean())
        report.oos = {
            "n": int(mask.sum()),
            "auc": round(auc(yo, po), 4),
            "log_loss": round(log_loss(yo, po), 4),
            # Her zaman temel oranı tahmin eden "bilgisiz" modelin log kaybı (karşılaştırma).
            "log_loss_baseline": round(log_loss(yo, np.full(len(yo), base_rate)), 4),
            "brier": round(brier(yo, po), 4),
            "base_rate": round(base_rate, 4),
            "calibration": calibration_table(yo, po),
            "top_decile_hit_rate": round(float(yo[top].mean()), 4),
            "top_decile_mean_return_pct": round(float(directional[top].mean() * 100), 4),
            "top_decile_net_return_pct": round(float((directional[top].mean() - cost) * 100), 4),
            "all_mean_return_pct": round(float(directional.mean() * 100), 4),
        }
    report.final_iterations = int(np.median(best_iterations)) if best_iterations else 200
    final = lgb.train(cfg, lgb.Dataset(X, y), num_boost_round=max(report.final_iterations, 10))
    gains = final.feature_importance(importance_type="gain")
    total = float(gains.sum()) or 1.0
    report.feature_importance = {
        name: round(float(g) / total, 4)
        for name, g in sorted(zip(labeled.feature_names, gains, strict=True), key=lambda x: -x[1])
    }
    return final, report
