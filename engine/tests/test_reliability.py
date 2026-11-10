"""Kendini ayarlayan strateji ağırlıkları: büzülme, sınırlar, sanal sonuçlardan hesap, puana
etkisi ve yerel API."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from ati_engine.app import Engine
from ati_engine.backtest.engine import Trade
from ati_engine.config import EngineSettings, LocalApiSettings
from ati_engine.core.models import Market
from ati_engine.paper.competition import Account, PaperCompetition
from ati_engine.scoring.reliability import HIGH, LOW, reliability
from ati_engine.scoring.score import OpportunityScorer
from ati_engine.strategies.base import StrategySignal
from test_opportunities import bullish_snapshot, inputs


def test_shrinkage_and_bounds() -> None:
    assert reliability([]).multiplier == 1.0
    few = reliability([2.0] * 5)
    assert few.multiplier == 1.0 and few.trades == 5 and few.avg_r == 2.0  # yeterli kanıt yok
    assert reliability([0.3] * 50).multiplier == HIGH
    assert reliability([-0.5] * 40).multiplier == LOW
    mild = reliability([0.1] * 30)
    assert mild.multiplier == pytest.approx(1 + 2 * 3 / 50, abs=1e-4)
    # Aynı ortalama, daha çok işlemle daha güçlü etki.
    assert reliability([0.1] * 100).multiplier > mild.multiplier


def trade(r: float) -> Trade:
    # Risk 10; R katı = net kâr / 10.
    return Trade("BTCUSDT", 1, 0, 100.0, 1.0, 90.0, 130.0, 10.0, "test", exit_price=100 + 10 * r)


def test_competition_reliability_per_market() -> None:
    good = Account("ema_trend", Market.SPOT, 0, 1000.0, trades=[trade(0.5)] * 30)
    bad = Account("rsi_reversion", Market.SPOT, 0, 1000.0, trades=[trade(-0.6)] * 30)
    other = Account("ema_trend", Market.USDM_FUTURES, 0, 1000.0, trades=[trade(-1.0)] * 30)
    combo = Account("opportunity_score", Market.SPOT, 0, 1000.0, trades=[trade(1.0)] * 30)
    fake = SimpleNamespace(accounts={(a.strategy, a.market): a for a in (good, bad, other, combo)})
    spot = PaperCompetition.reliability(fake, Market.SPOT)  # type: ignore[arg-type]
    assert spot["ema_trend"].multiplier > 1.2 and spot["rsi_reversion"].multiplier < 0.7
    assert "opportunity_score" not in spot  # birleşik puan hesabı kendini ağırlıklandırmaz
    futures = PaperCompetition.reliability(fake, Market.USDM_FUTURES)  # type: ignore[arg-type]
    assert futures["ema_trend"].multiplier < 1


def test_reliability_changes_strategy_weight_in_score() -> None:
    signals = [StrategySignal("ema_trend", 1, 0.8, "trend"),
               StrategySignal("donchian_breakout", 1, 0.6, "kırılım")]  # fmt: skip
    plain = OpportunityScorer().score(inputs(bullish_snapshot(), signals))
    scorer = OpportunityScorer()
    scorer.reliability = {"ema_trend": 0.4, "donchian_breakout": 0.4}
    weak = scorer.score(inputs(bullish_snapshot(), signals))
    strategies_plain = next(c for c in plain.components if c.key == "strategies")
    strategies_weak = next(c for c in weak.components if c.key == "strategies")
    assert strategies_weak.signal < strategies_plain.signal
    assert "2 zayıflatıldı" in strategies_weak.detail
    assert [s["weight"] for s in weak.signals] == [0.4, 0.4]
    assert [s["weight"] for s in plain.signals] == [1.0, 1.0]


async def test_reliability_endpoint(tmp_path: Path) -> None:
    engine = Engine(
        EngineSettings(
            data_dir=tmp_path / "data", log_to_console=False, api=LocalApiSettings(port=0)
        )
    )
    task = asyncio.create_task(engine.run())
    await asyncio.wait_for(engine.ready.wait(), timeout=15)
    assert engine.runtime is not None
    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{engine.bound_port}",
        headers={"Authorization": f"Bearer {engine.runtime.api_token}"},
    ) as http:
        response = await http.get("/v1/opportunities/reliability")
        assert response.status_code == 200
        body = response.json()
        assert "R katı" in body["explanation"] and isinstance(body["markets"], dict)
    engine.runtime.request_shutdown()
    await asyncio.wait_for(task, timeout=15)
