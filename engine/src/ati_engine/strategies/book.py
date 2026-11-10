"""Sembol başına strateji defteri: özellik motoru + destek/direnç + tüm stratejiler.

Her kapanmış mumda göstergeler güncellenir, seviyeler belirli aralıklarla yeniden hesaplanır ve
piyasaya uygun bütün stratejiler çalıştırılır. Bir stratejideki hata diğerlerini etkilemez.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from ati_engine.analysis.features import Bar, FeatureEngine, FuturesContext, Snapshot
from ati_engine.analysis.patterns import Pattern, detect_patterns
from ati_engine.history.levels import Level, find_levels
from ati_engine.strategies.base import MarketKind, ModelView, StrategySignal, StrategyView
from ati_engine.strategies.library import strategies_for

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BookUpdate:
    snapshot: Snapshot
    features: dict[str, float]
    signals: tuple[StrategySignal, ...]
    levels: tuple[Level, ...]
    model: ModelView | None = None
    patterns: tuple[Pattern, ...] = ()


class StrategyBook:
    def __init__(
        self,
        market: MarketKind,
        symbol: str,
        *,
        levels_every: int = 6,
        history: int = 500,
    ) -> None:
        self.market = market
        self.symbol = symbol
        self.engine = FeatureEngine()
        self.strategies = strategies_for(market)
        self.prev: Snapshot | None = None
        self.levels: tuple[Level, ...] = ()
        self._levels_every = levels_every
        self._since_levels = levels_every
        self._bars: deque[tuple[int, float, float, float, float, float]] = deque(maxlen=history)
        self.last_open_ms: int | None = None
        self.errors = 0

    def update(
        self,
        bar: Bar,
        futures: FuturesContext | None = None,
        model: ModelView | Callable[[dict[str, float]], ModelView | None] | None = None,
    ) -> BookUpdate | None:
        """``model`` bir fonksiyon olabilir: bu mumun özellikleriyle çağrılır (model tahmini
        stratejilerden önce, aynı mumun özellikleriyle yapılır)."""
        if self.last_open_ms is not None and bar.open_time_ms <= self.last_open_ms:
            return None  # aynı veya eski mum (ısınma ile canlı akışın çakışması)
        self.last_open_ms = bar.open_time_ms
        features = self.engine.update(bar, futures)
        self._bars.append((bar.open_time_ms, bar.open, bar.high, bar.low, bar.close, bar.volume))
        snapshot = self.engine.snapshot
        if features is None or snapshot is None:
            self.prev = None
            return None
        self._since_levels += 1
        if self._since_levels >= self._levels_every:
            self.levels = tuple(find_levels(list(self._bars)))
            self._since_levels = 0
        model_view: ModelView | None
        if callable(model):
            try:
                model_view = model(features)
            except Exception as exc:
                self.errors += 1
                logger.warning(
                    "Model tahmini başarısız", extra={"symbol": self.symbol, "error": repr(exc)}
                )
                model_view = None
        else:
            model_view = model
        try:
            patterns = detect_patterns(self._bars, snapshot.atr, self.levels)
        except Exception as exc:  # formasyon hatası stratejileri durdurmaz
            self.errors += 1
            logger.warning(
                "Formasyon taraması başarısız", extra={"symbol": self.symbol, "error": repr(exc)}
            )
            patterns = ()
        view = StrategyView(
            market=self.market,
            symbol=self.symbol,
            now=snapshot,
            prev=self.prev,
            levels=self.levels,
            model=model_view,
            patterns=patterns,
        )
        signals: list[StrategySignal] = []
        for strategy in self.strategies:
            try:
                signal = strategy.evaluate(view)
            except Exception as exc:  # bir stratejinin hatası diğerlerini durdurmaz
                self.errors += 1
                logger.warning(
                    "Strateji hatası",
                    extra={"strategy": strategy.name, "symbol": self.symbol, "error": repr(exc)},
                )
                continue
            if signal is not None:
                signals.append(signal)
        self.prev = snapshot
        return BookUpdate(snapshot, features, tuple(signals), self.levels, model_view, patterns)
