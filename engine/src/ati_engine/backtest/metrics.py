"""Performans metrikleri (tanımlar açık; testlerde elle hesaplanan değerlerle doğrulanır).

* Başarı oranı: net kârı > 0 olan işlem oranı.
* Profit Factor: toplam net kâr / toplam net zararın mutlak değeri (zarar yoksa ``None``).
* Beklenti: işlem başına ortalama net kâr; ortalama R: net kârın riske edilen tutara oranı.
* Sharpe: mum başına sermaye getirisinin ortalaması / standart sapması x √(yıllık mum sayısı).
* Sortino: ortalama / aşağı yönlü sapma √(ortalama(min(getiri, 0)²)) x √(yıllık mum sayısı).
* Maksimum düşüş: sermaye eğrisinde zirveden en derin düşüş (%) ve süresi (mum).
* CAGR: yıllık bileşik büyüme. Piyasada kalma: açık pozisyon bulunan mumların oranı.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ati_engine.backtest.engine import BacktestResult, nan_to_none


def equity_metrics(equity: list[float], bars_per_year: float) -> dict[str, float | int | None]:
    values = np.asarray(equity, dtype=np.float64)
    if len(values) < 2 or values[0] <= 0:
        return {
            "total_return_pct": 0.0,
            "cagr_pct": None,
            "sharpe": None,
            "sortino": None,
            "max_drawdown_pct": 0.0,
            "max_drawdown_bars": 0,
            "volatility_annual_pct": None,
        }
    wiped = np.flatnonzero(values <= 0)
    if len(wiped):
        values = values[: wiped[0] + 1]  # hesap sıfırlandıktan sonra getiri tanımsız
    returns = values[1:] / values[:-1] - 1.0
    mean = float(returns.mean())
    std = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    downside = float(np.sqrt(np.mean(np.minimum(returns, 0.0) ** 2)))
    scale = math.sqrt(bars_per_year)
    peaks = np.maximum.accumulate(values)
    drawdowns = (peaks - values) / peaks
    max_dd = float(drawdowns.max())
    # En uzun düşüş süresi: zirveye geri dönülemeyen ardışık mum sayısı.
    longest = current = 0
    for dd in drawdowns:
        current = current + 1 if dd > 0 else 0
        longest = max(longest, current)
    years = len(returns) / bars_per_year
    final = float(values[-1] / values[0])
    cagr = (final ** (1 / years) - 1) * 100 if years > 0 and final > 0 else None
    return {
        "total_return_pct": round((final - 1) * 100, 4),
        "cagr_pct": round(cagr, 4) if cagr is not None else None,
        "sharpe": round(mean / std * scale, 4) if std > 0 else None,
        "sortino": round(mean / downside * scale, 4) if downside > 0 else None,
        "max_drawdown_pct": round(max_dd * 100, 4),
        "max_drawdown_bars": int(longest),
        "volatility_annual_pct": round(std * scale * 100, 4) if std > 0 else None,
    }


def trade_metrics(result: BacktestResult) -> dict[str, Any]:
    trades = result.trades
    pnl = np.array([t.net_pnl for t in trades], dtype=np.float64)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    gross_profit = float(wins.sum())
    gross_loss = float(-losses.sum())
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t.exit_reason or "?"] = reasons.get(t.exit_reason or "?", 0) + 1
    return {
        "trades": len(trades),
        "long_trades": sum(1 for t in trades if t.direction > 0),
        "short_trades": sum(1 for t in trades if t.direction < 0),
        "win_rate": round(float((pnl > 0).mean()), 4) if len(trades) else None,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss > 0 else None,
        "gross_profit": round(gross_profit, 4),
        "gross_loss": round(gross_loss, 4),
        "net_pnl": round(float(pnl.sum()), 4),
        "expectancy": round(float(pnl.mean()), 4) if len(trades) else None,
        "avg_win": round(float(wins.mean()), 4) if len(wins) else None,
        "avg_loss": round(float(losses.mean()), 4) if len(losses) else None,
        "avg_r": round(float(np.mean([t.r_multiple for t in trades])), 4) if trades else None,
        "avg_bars_held": round(float(np.mean([t.bars_held for t in trades])), 2)
        if trades
        else None,
        "fees": round(sum(t.fees for t in trades), 4),
        "funding": round(sum(t.funding for t in trades), 4),
        "exit_reasons": reasons,
    }


def compute_metrics(result: BacktestResult) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    metrics.update(trade_metrics(result))
    metrics.update(equity_metrics(result.equity, result.bars_per_year))
    metrics["exposure_pct"] = (
        round(result.exposure_bars / result.total_bars * 100, 2) if result.total_bars else 0.0
    )
    metrics["final_equity"] = round(result.equity[-1], 4) if result.equity else None
    metrics["liquidated"] = result.liquidated_at_ms is not None
    metrics["insurance_shortfall"] = round(result.insurance_shortfall, 4)
    return {k: (nan_to_none(v) if isinstance(v, float) else v) for k, v in metrics.items()}
