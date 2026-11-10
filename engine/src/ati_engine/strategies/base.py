"""Strateji arayüzü.

Bir strateji, kapanmış bir mumdaki gösterge görünümünü okuyup yön (+1 long, -1 short) ve
0-1 arası güç ile **gerekçeli** bir sinyal üretir; sinyal yoksa ``None`` döner. Stratejiler
emir vermez: sinyaller fırsat puanına (Aşama 7), backtest'e (Aşama 8) ve sanal yarışmaya
(Aşama 9) girdi olur. Her strateji yalnızca o ana kadarki veriyi görür.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from ati_engine.analysis.features import Snapshot
from ati_engine.analysis.patterns import Pattern
from ati_engine.history.levels import Level

MarketKind = Literal["spot", "usdm_futures"]


@dataclass(frozen=True)
class ModelView:
    """Eğitilmiş modellerin bu mumdaki tahmini ve örneklem dışı temel oranları."""

    p_long: float | None = None
    p_short: float | None = None
    base_long: float | None = None
    base_short: float | None = None


@dataclass(frozen=True)
class StrategyView:
    market: MarketKind
    symbol: str
    now: Snapshot
    prev: Snapshot | None
    levels: tuple[Level, ...] = ()
    model: ModelView | None = None
    patterns: tuple[Pattern, ...] = ()  # bu mumda tamamlanan formasyonlar


@dataclass(frozen=True)
class StrategySignal:
    strategy: str
    direction: int  # +1 long, -1 short
    strength: float  # 0-1
    reason: str
    stop_atr: float = 1.5  # önerilen zarar durdur uzaklığı (ATR katı)
    target_atr: float = 3.0  # önerilen hedef uzaklığı (ATR katı)
    tags: tuple[str, ...] = field(default_factory=tuple)


class Strategy(Protocol):
    name: str
    title: str
    description: str
    markets: tuple[MarketKind, ...]
    category: str  # trend | momentum | mean_reversion | breakout | pattern | flow | futures | model

    def evaluate(self, view: StrategyView) -> StrategySignal | None: ...


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
