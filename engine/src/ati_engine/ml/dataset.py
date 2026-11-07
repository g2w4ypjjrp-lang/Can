"""Eğitim veri kümesi: tarihsel mumlardan özellikler (canlıdakiyle aynı ``FeatureEngine``) ve
ileri getiri etiketleri.

Etiket: ``h`` mum sonraki kapanışın logaritmik getirisi. Sınıflandırma hedefi işlem maliyeti
eşiğiyle tanımlanır: long modeli için ``getiri > eşik``, short modeli için ``getiri < -eşik``.
Veri içinde boşluk varsa (borsa kesintisi) ``t+h`` gerçekten ``h`` mum sonrası değilse etiket
üretilmez.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from ati_engine.analysis.features import (
    ALL_FEATURES,
    BASE_FEATURES,
    Bar,
    FeatureEngine,
    FuturesContext,
    vectorize,
)
from ati_engine.history.archive import INTERVAL_MS

Side = Literal["long", "short"]


@dataclass
class Dataset:
    interval: str
    horizon: int
    feature_names: tuple[str, ...]
    times: np.ndarray  # int64, mum açılış zamanı
    symbols: np.ndarray  # object
    X: np.ndarray  # float32 (n, f)
    forward_return: np.ndarray  # float64; bilinmiyorsa nan (son h mum)

    def __len__(self) -> int:
        return len(self.times)

    def labeled(self) -> Dataset:
        mask = ~np.isnan(self.forward_return)
        return Dataset(
            interval=self.interval,
            horizon=self.horizon,
            feature_names=self.feature_names,
            times=self.times[mask],
            symbols=self.symbols[mask],
            X=self.X[mask],
            forward_return=self.forward_return[mask],
        )

    def labels(self, side: Side, threshold: float) -> np.ndarray:
        if side == "long":
            return (self.forward_return > threshold).astype(np.int32)
        return (self.forward_return < -threshold).astype(np.int32)


def _bar(row: Sequence[Any]) -> Bar:
    return Bar(
        open_time_ms=int(row[0]),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
        quote_volume=float(row[6]),
        taker_buy_quote=float(row[7]),
    )


def _futures(row: Sequence[Any]) -> FuturesContext:
    def opt(i: int) -> float | None:
        value = row[i] if len(row) > i else None
        return float(value) if value is not None else None

    return FuturesContext(
        funding_rate=opt(8),
        open_interest_usd=opt(9),
        top_long_short=opt(10),
        global_long_short=opt(11),
        taker_long_short=opt(12),
    )


def symbol_features(
    rows: Sequence[Sequence[Any]], *, futures: bool, names: tuple[str, ...]
) -> tuple[list[int], list[list[float]], list[int]]:
    """Bir sembolün mumlarını sırayla işler: (zamanlar, özellik vektörleri, satır indeksleri)."""
    engine = FeatureEngine()
    times: list[int] = []
    vectors: list[list[float]] = []
    indices: list[int] = []
    for i, row in enumerate(rows):
        features = engine.update(_bar(row), _futures(row) if futures else None)
        if features is None:
            continue
        times.append(int(row[0]))
        vectors.append(vectorize(features, names))
        indices.append(i)
    return times, vectors, indices


def build_dataset(
    per_symbol: Mapping[str, Sequence[Sequence[Any]]],
    *,
    interval: str,
    horizon: int,
    futures: bool,
) -> Dataset:
    """``per_symbol``: sembol → zamana göre sıralı satırlar
    (open_time, open, high, low, close, volume, quote_volume, taker_buy_quote[, futures...])."""
    if horizon < 1:
        raise ValueError("horizon >= 1")
    names = ALL_FEATURES if futures else BASE_FEATURES
    step = INTERVAL_MS[interval]
    all_times: list[int] = []
    all_symbols: list[str] = []
    all_vectors: list[list[float]] = []
    all_forward: list[float] = []
    for symbol, rows in per_symbol.items():
        times, vectors, indices = symbol_features(rows, futures=futures, names=names)
        for t, vec, i in zip(times, vectors, indices, strict=True):
            j = i + horizon
            forward = math.nan
            if j < len(rows) and int(rows[j][0]) - t == horizon * step:
                c0, c1 = float(rows[i][4]), float(rows[j][4])
                if c0 > 0 and c1 > 0:
                    forward = math.log(c1 / c0)
            all_times.append(t)
            all_symbols.append(symbol)
            all_vectors.append(vec)
            all_forward.append(forward)
    order = np.argsort(np.asarray(all_times, dtype=np.int64), kind="stable")
    return Dataset(
        interval=interval,
        horizon=horizon,
        feature_names=names,
        times=np.asarray(all_times, dtype=np.int64)[order],
        symbols=np.asarray(all_symbols, dtype=object)[order],
        X=np.asarray(all_vectors, dtype=np.float32).reshape(len(all_times), len(names))[order],
        forward_return=np.asarray(all_forward, dtype=np.float64)[order],
    )
