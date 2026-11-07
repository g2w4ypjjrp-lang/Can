"""Aşama 8 kabul testleri: sonucu elle hesaplanmış sentetik senaryolarda doğru işlemler ve
metrikler; ileriye bakma yok; yürüyen pencere ve arındırılmış çapraz doğrulama."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pytest

from ati_engine.analysis.features import Bar, FeatureEngine, Snapshot
from ati_engine.backtest.engine import (
    BacktestConfig,
    BarRecord,
    BuyAndHoldRule,
    EntryDecision,
    StrategyRule,
    record_symbol,
    run_backtest,
)
from ati_engine.backtest.metrics import compute_metrics, equity_metrics
from ati_engine.backtest.validation import purged_kfold, walk_forward

HOUR = 3_600_000
FIXTURE = Path(__file__).parent / "fixtures" / "binance" / "spot_btcusdt_1h_1500.json"


def base_snapshot() -> Snapshot:
    engine = FeatureEngine()
    for r in json.loads(FIXTURE.read_text(encoding="utf-8"))["rows"][:300]:
        engine.update(Bar(int(r[0]), *r[1:8]))
    assert engine.snapshot is not None
    return replace(engine.snapshot, atr=1.0)


SNAP = base_snapshot()


def rec(
    i: int,
    o: float,
    h: float,
    lo: float,
    c: float,
    *,
    funding: float | None = None,
    start: int = 0,
) -> BarRecord:
    return BarRecord(
        time_ms=start + i * HOUR,
        open=o,
        high=h,
        low=lo,
        close=c,
        quote_volume=1e12,
        funding_rate=funding,
        snapshot=SNAP,
        signals=(),
        levels=(),
    )


@dataclass
class ScriptedRule:
    """Belirli mumların kapanışında belirli kararı veren kural (bilinen senaryolar için)."""

    script: dict[int, EntryDecision]
    name: str = "senaryo"

    def decide(self, symbol: str, record: BarRecord, quote_volume_24h: float | None):  # type: ignore[no-untyped-def]
        return self.script.get(record.time_ms)


LONG = EntryDecision(1, 1.0, 2.0, "test long")
SHORT = EntryDecision(-1, 1.0, 2.0, "test short")
EXACT = BacktestConfig(taker_fee=0.0, slippage_bps=0.0, max_positions=5)


def flat(n: int, price: float = 100.0) -> list[BarRecord]:
    return [rec(i, price, price + 0.1, price - 0.1, price) for i in range(n)]


# --- Bilinen sonuçlu senaryolar ----------------------------------------------------------------


def test_long_hits_target_exactly() -> None:
    bars = flat(6)
    bars[3] = rec(3, 100, 102.5, 99.5, 102)  # hedef 102'ye değdi
    result = run_backtest({"X": bars}, ScriptedRule({1 * HOUR: LONG}), EXACT)
    (trade,) = result.trades
    # Sinyal 1. mumun kapanışında, giriş 2. mumun açılışında (100).
    assert trade.entry_time_ms == 2 * HOUR and trade.entry_price == 100
    # Risk = 10.000 x %1 = 100; zarar durdur uzaklığı 1 ATR = 1 → 100 adet; değer 10.000.
    assert trade.qty == pytest.approx(100)
    assert (trade.stop, trade.target) == (99, 102)
    assert trade.exit_reason == "target" and trade.exit_price == 102
    assert trade.net_pnl == pytest.approx(200)
    assert trade.r_multiple == pytest.approx(2.0)
    assert result.equity[-1] == pytest.approx(10_200)


def test_stop_wins_when_both_levels_touched_same_bar() -> None:
    bars = flat(6)
    bars[3] = rec(3, 100, 103, 98, 101)  # hem 99 (stop) hem 102 (hedef) görüldü
    (trade,) = run_backtest({"X": bars}, ScriptedRule({HOUR: LONG}), EXACT).trades
    assert trade.exit_reason == "stop" and trade.exit_price == 99
    assert trade.net_pnl == pytest.approx(-100)
    assert trade.r_multiple == pytest.approx(-1.0)


def test_gap_through_stop_fills_at_open() -> None:
    bars = flat(6)
    bars[3] = rec(3, 97, 97.5, 96, 97)  # açılış stop'un (99) altında
    (trade,) = run_backtest({"X": bars}, ScriptedRule({HOUR: LONG}), EXACT).trades
    assert trade.exit_price == 97
    assert trade.net_pnl == pytest.approx(-300)  # 1R değil 3R kayıp: boşluk riski


def test_fees_and_slippage_exact() -> None:
    bars = flat(6)
    bars[3] = rec(3, 100, 102.5, 99.5, 102)
    config = BacktestConfig(taker_fee=0.001, slippage_bps=10.0)
    (trade,) = run_backtest({"X": bars}, ScriptedRule({HOUR: LONG}), config).trades
    entry = 100 * 1.001  # alışta kayma aleyhte
    qty = 10_000 / entry  # risk 100/1 = 100 adet istenir; sermaye sınırı 10.000 / 100,1
    assert trade.entry_price == pytest.approx(entry)
    assert trade.qty == pytest.approx(qty)
    target = entry + 2.0
    exit_fill = target * 0.999
    assert trade.exit_price == pytest.approx(exit_fill)
    fees = qty * entry * 0.001 + qty * exit_fill * 0.001
    assert trade.fees == pytest.approx(fees)
    assert trade.net_pnl == pytest.approx(qty * (exit_fill - entry) - fees)


def test_futures_short_with_funding() -> None:
    start = 10 * 8 * HOUR  # 8 saatin katı: 3. mum 00/08/16'ya denk gelir
    bars = [rec(i, 100, 100.1, 99.9, 100, start=start - 2 * HOUR) for i in range(8)]
    bars[2] = rec(2, 100, 100.1, 99.9, 100, funding=0.0001, start=start - 2 * HOUR)
    bars[4] = rec(4, 100, 100.2, 97.5, 98, start=start - 2 * HOUR)  # short hedef 98
    config = replace(EXACT, market="usdm_futures")
    script = {start - 2 * HOUR: SHORT}  # 0. mum kapanışı → 1. mum açılışında giriş
    (trade,) = run_backtest({"X": bars}, ScriptedRule(script), config).trades
    assert trade.direction == -1 and trade.entry_price == 100
    # Pozitif funding'de short alır: 100 adet x 100 x 0,0001 = 1 (ödenen = -1).
    assert trade.funding == pytest.approx(-1.0)
    assert trade.exit_reason == "target" and trade.exit_price == 98
    assert trade.net_pnl == pytest.approx(200 + 1)


def test_spot_ignores_short_signals_and_time_exit() -> None:
    bars = flat(10)
    config = replace(EXACT, max_hold_bars=3)
    result = run_backtest({"X": bars}, ScriptedRule({HOUR: SHORT, 2 * HOUR: LONG}), config)
    (trade,) = result.trades  # short yok sayıldı, yalnızca long
    assert trade.direction == 1
    assert trade.exit_reason == "time" and trade.bars_held == 3


def test_opposite_signal_exits_next_open() -> None:
    bars = flat(10)
    bars[5] = rec(5, 101, 101.2, 100.8, 101)
    config = replace(EXACT, market="usdm_futures")
    result = run_backtest({"X": bars}, ScriptedRule({HOUR: LONG, 4 * HOUR: SHORT}), config)
    first = result.trades[0]
    assert first.exit_reason == "opposite"
    assert first.exit_time_ms == 5 * HOUR and first.exit_price == 101


def test_portfolio_position_limit_and_leverage_cap() -> None:
    data = {s: flat(8) for s in ("A", "B", "C")}
    wide = EntryDecision(1, 5.0, 10.0, "geniş stop")  # 100 / 5 = 20 adet → 2.000 değer
    result = run_backtest(data, ScriptedRule({HOUR: wide}), replace(EXACT, max_positions=2))
    assert sorted(t.symbol for t in result.trades) == ["A", "B"]  # C yer bulamadı
    assert all(t.qty * t.entry_price == pytest.approx(2_000) for t in result.trades)
    # Dar stopta ilk işlem tüm sermayeyi (kaldıraç 1) kullanır; ikinciye yer kalmaz.
    narrow = run_backtest(data, ScriptedRule({HOUR: LONG}), replace(EXACT, max_positions=3))
    assert len(narrow.trades) == 1
    assert narrow.trades[0].qty * narrow.trades[0].entry_price == pytest.approx(10_000)
    # Kaldıraç 3 (vadeli): üç pozisyon da sığar.
    levered = replace(EXACT, max_positions=3, max_leverage=3.0, market="usdm_futures")
    assert len(run_backtest(data, ScriptedRule({HOUR: LONG}), levered).trades) == 3


# --- Metrikler -------------------------------------------------------------------------------


def test_equity_metrics_by_hand() -> None:
    equity = [100.0, 110.0, 99.0, 120.0]
    m = equity_metrics(equity, bars_per_year=3)
    r = np.array([0.10, -0.10, 120 / 99 - 1])
    assert m["total_return_pct"] == pytest.approx(20.0)
    assert m["max_drawdown_pct"] == pytest.approx(10.0)  # 110 → 99
    assert m["max_drawdown_bars"] == 1
    assert m["sharpe"] == pytest.approx(r.mean() / r.std(ddof=1) * math.sqrt(3), abs=1e-4)
    downside = math.sqrt(np.mean(np.minimum(r, 0) ** 2))
    assert m["sortino"] == pytest.approx(r.mean() / downside * math.sqrt(3), abs=1e-4)
    assert m["cagr_pct"] == pytest.approx(20.0, abs=1e-6)  # 3 mum = 1 yıl


def test_trade_metrics_by_hand() -> None:
    bars = flat(30)
    bars[3] = rec(3, 100, 102.5, 99.5, 102)  # 1. işlem: +200 (hedef)
    bars[8] = rec(8, 102, 102.1, 100.5, 101)  # 2. işlem (giriş 102): stop 101 → -100
    bars[13] = rec(13, 101, 103.6, 100.9, 103)  # 3. işlem (giriş 101): hedef 103 → +200
    script = {HOUR: LONG, 6 * HOUR: LONG, 11 * HOUR: LONG}
    bars[7] = rec(7, 102, 102.1, 101.9, 102)
    bars[12] = rec(12, 101, 101.1, 100.9, 101)
    result = run_backtest({"X": bars}, ScriptedRule(script), EXACT)
    m = compute_metrics(result)
    pnl = [round(t.net_pnl, 6) for t in result.trades]
    assert len(pnl) == 3
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p < 0]
    assert m["win_rate"] == pytest.approx(len(wins) / 3, abs=1e-4)
    assert m["profit_factor"] == pytest.approx(sum(wins) / -sum(losses), rel=1e-4)
    assert m["net_pnl"] == pytest.approx(sum(pnl))
    assert m["final_equity"] == pytest.approx(10_000 + sum(pnl))


def test_profit_factor_none_without_losses() -> None:
    bars = flat(6)
    bars[3] = rec(3, 100, 102.5, 99.5, 102)
    m = compute_metrics(run_backtest({"X": bars}, ScriptedRule({HOUR: LONG}), EXACT))
    assert m["profit_factor"] is None and m["win_rate"] == 1.0


# --- İleriye bakma ---------------------------------------------------------------------------


def real_records(cut_alter: int | None = None) -> list[BarRecord]:
    rows = [tuple(r) for r in json.loads(FIXTURE.read_text(encoding="utf-8"))["rows"]]
    if cut_alter is not None:
        rng = np.random.default_rng(2)
        altered = []
        for i, r in enumerate(rows):
            if i >= cut_alter:
                f = float(1 + rng.normal(0, 0.05))
                r = (r[0], r[1] * f, r[2] * f * 1.02, r[3] * f * 0.98, r[4] * f, *r[5:])
            altered.append(r)
        rows = altered
    return record_symbol(rows, market="spot", symbol="BTCUSDT")


def test_no_look_ahead_trades_before_cut_unchanged() -> None:
    """Gelecek mumlar değiştirildiğinde, kesimden önce kapanmış işlemler birebir aynı kalır."""
    cut = 1100
    original = real_records()
    altered = real_records(cut_alter=cut)
    cut_time = original[cut].time_ms
    config = BacktestConfig()
    for strategy in ("ema_trend", "donchian_breakout", "macd_momentum"):
        a = run_backtest({"BTC": original}, StrategyRule(strategy), config).trades
        b = run_backtest({"BTC": altered}, StrategyRule(strategy), config).trades
        before_a = [t for t in a if t.exit_time_ms is not None and t.exit_time_ms < cut_time]
        before_b = [t for t in b if t.exit_time_ms is not None and t.exit_time_ms < cut_time]
        assert before_a, strategy
        assert [(t.entry_time_ms, t.exit_time_ms, round(t.net_pnl, 9)) for t in before_a] == [
            (t.entry_time_ms, t.exit_time_ms, round(t.net_pnl, 9)) for t in before_b
        ]


def test_entries_happen_after_signal_bar() -> None:
    records = real_records()
    result = run_backtest({"BTC": records}, StrategyRule("ema_trend"), BacktestConfig())
    signal_times = {r.time_ms for r in records if any(s.strategy == "ema_trend" for s in r.signals)}
    assert result.trades
    for trade in result.trades:
        assert trade.entry_time_ms - HOUR in signal_times  # bir önceki mumda sinyal vardı
        assert trade.entry_time_ms not in signal_times or trade.entry_time_ms - HOUR in signal_times


def test_buy_and_hold_tracks_price() -> None:
    records = real_records()
    config = BacktestConfig(taker_fee=0.0, slippage_bps=0.0, max_hold_bars=10**9)
    result = run_backtest({"BTC": records}, BuyAndHoldRule(), config)
    (trade,) = result.trades
    first = next(i for i, r in enumerate(records) if r.snapshot is not None)
    assert trade.entry_price == records[first + 1].open
    expected = trade.qty * (records[-1].close - trade.entry_price)
    assert trade.net_pnl == pytest.approx(expected)


# --- Doğrulama ---------------------------------------------------------------------------------


def trending_records(n: int = 2000, seed: int = 4) -> dict[str, list[BarRecord]]:
    """Sentetik: gerçek fikstür + rastgele yürüyüş birleşik (yeterli uzunluk için)."""
    rng = np.random.default_rng(seed)
    price = 100.0
    rows = []
    for i in range(n):
        o = price
        price *= math.exp(rng.normal(0.0002, 0.01))
        h, lo = max(o, price) * 1.003, min(o, price) * 0.997
        v = float(rng.uniform(50, 150))
        rows.append((i * HOUR, o, h, lo, price, v, v * price, v * price * rng.uniform(0.3, 0.7)))
    return {"SYN": record_symbol(rows, market="spot", symbol="SYN")}


def test_walk_forward_selects_on_past_and_tests_on_future() -> None:
    data = trending_records()
    grid = [{"stop_atr": s, "target_atr": t} for s in (1.0, 2.0) for t in (2.0, 4.0)]

    def make(params: dict[str, float]) -> StrategyRule:
        return StrategyRule(
            "ema_trend", stop_atr=params["stop_atr"], target_atr=params["target_atr"]
        )

    result = walk_forward(
        data,
        make_rule=make,
        grid=grid,
        config=BacktestConfig(),
        interval_ms=HOUR,
        train_bars=600,
        test_bars=300,
        min_trades=3,
    )
    assert len(result.windows) >= 3
    for w in result.windows:
        assert w.train_end_ms == w.test_start_ms
        assert w.train_start_ms < w.train_end_ms < w.test_end_ms
        assert w.params in grid
    # Örneklem dışı işlemler yalnızca test dönemlerinde.
    first_test = result.windows[0].test_start_ms
    assert all(t.entry_time_ms >= first_test for t in result.oos.trades)
    assert result.oos_metrics["trades"] == len(result.oos.trades)


def test_purged_cv_excludes_overlapping_trades() -> None:
    data = trending_records()
    grid = [{"strategy": s} for s in ("ema_trend", "donchian_breakout", "macd_momentum")]
    result = purged_kfold(
        data,
        make_rule=lambda p: StrategyRule(p["strategy"]),
        grid=grid,
        config=BacktestConfig(),
        interval_ms=HOUR,
        folds=4,
        embargo_bars=24,
        min_trades=2,
    )
    assert len(result.folds) == 4
    assert result.purged_trades > 0  # sınırdaki işlemler seçimden çıkarıldı
    for fold in result.folds:
        assert fold.test_start_ms < fold.test_end_ms
    assert all(
        any(f.test_start_ms <= t.entry_time_ms < f.test_end_ms for f in result.folds)
        for t in result.oos_trades
    )
    assert result.pbo is None or 0 <= result.pbo <= 1


# --- Kayıt defteri ve API -----------------------------------------------------------------------


async def test_backtest_api_and_registry(tmp_path: Path) -> None:
    import asyncio

    import httpx

    from ati_engine.app import Engine
    from ati_engine.config import EngineSettings, LocalApiSettings

    settings = EngineSettings(
        data_dir=tmp_path / "data", log_to_console=False, api=LocalApiSettings(port=0)
    )
    engine = Engine(settings)
    task = asyncio.create_task(engine.run())
    await asyncio.wait_for(engine.ready.wait(), timeout=10)
    runtime = engine.runtime
    assert runtime is not None and runtime.history is not None and runtime.backtests is not None
    try:
        rows = json.loads(FIXTURE.read_text(encoding="utf-8"))["rows"]
        await runtime.history.store.insert(
            "spot",
            "BTCUSDT",
            "1h",
            [
                (
                    int(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    int(r[0]) + HOUR - 1,
                    r[6],
                    10,
                    r[7] / r[4],
                    r[7],
                )
                for r in rows
            ],
        )

        class NoNetworkSync:  # veri zaten depoda; ağ kullanılmaz
            db = runtime.db

            async def sync_klines(self, *args: object) -> None:
                return None

        runtime.history.sync = NoNetworkSync()  # type: ignore[assignment]
        headers = {"Authorization": f"Bearer {runtime.api_token}"}
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{engine.bound_port}", headers=headers
        ) as client:
            accepted = await client.post(
                "/v1/backtest/run",
                json={"market": "spot", "symbols": ["btcusdt"], "walk_forward": False},
            )
            assert accepted.status_code == 202, accepted.text
            for _ in range(300):
                job = (await client.get("/v1/backtest/jobs")).json()[0]
                if job["state"] != "running":
                    break
                await asyncio.sleep(0.1)
            assert job["state"] == "done", job
            reports = (await client.get("/v1/backtest/reports")).json()
            assert reports == [job["report_name"]]
            report = (await client.get(f"/v1/backtest/reports/{reports[0]}")).json()
            names = {row["name"] for row in report["leaderboard"]}
            assert {"ema_trend", "al_ve_tut", "score>=60"} <= names
            assert "garanti" in report["disclaimer"]
            registry = (await client.get("/v1/strategies")).json()
            ema = next(s for s in registry if s["name"] == "ema_trend")
            assert ema["stage"] == "backtest"  # araştırmadan backtest aşamasına
            assert ema["metrics"]["backtest"]["trades"] >= 0
            assert not any(s["stage"] == "live" for s in registry)
            bad = await client.get("/v1/backtest/reports/..%2Fengine.db")
            assert bad.status_code in (404, 422)
    finally:
        runtime.request_shutdown()
        assert await asyncio.wait_for(task, timeout=15) == 0


async def test_live_stage_cannot_be_set_automatically(tmp_path: Path) -> None:
    from ati_engine.backtest.service import ensure_strategies, set_stage, strategy_id
    from ati_engine.storage.database import Database

    db = Database(tmp_path / "e.db")
    await db.open()
    await db.migrate()
    await ensure_strategies(db)
    with pytest.raises(ValueError, match="Canlı"):
        await set_stage(db, strategy_id("ema_trend"), "live")
    # Veritabanı kısıtı da onaysız canlı aşamayı reddeder.
    with pytest.raises(Exception, match="CHECK"):
        await db.execute("UPDATE strategies SET stage = 'live' WHERE id = 'ema_trend.v1'")
    await db.close()


def test_futures_liquidation_stops_the_account() -> None:
    """3 kat kaldıraçla long; mum içinde fiyat %35 düşünce sermaye bakım teminatının altına
    iner → tasfiye. Hesap eksiye düşmez, açık sigorta fonuna yazılır, sonra işlem açılmaz."""
    bars = flat(12)
    bars[4] = rec(4, 100, 100.1, 65, 90)  # mum içinde 65'e iğne, 90'da kapanış
    wide = EntryDecision(1, 50.0, 100.0, "uzak stop")
    # Risk 1,5 x sermaye / 50 → 300 adet (30.000 değer = 3 kat kaldıraç).
    config = replace(EXACT, market="usdm_futures", max_leverage=3.0, risk_per_trade=1.5)
    result = run_backtest({"X": bars}, ScriptedRule({HOUR: wide, 6 * HOUR: LONG}), config)
    (trade,) = result.trades  # tasfiye sonrası yeni işlem yok
    assert trade.qty == pytest.approx(300)
    assert trade.exit_reason == "liquidation" and trade.exit_price == 65
    assert result.liquidated_at_ms == 4 * HOUR
    metrics = compute_metrics(result)
    assert metrics["liquidated"] is True
    # 300 x (65 - 100) = -10.500 → 500 açık sigorta fonuna, hesap 0.
    assert metrics["insurance_shortfall"] == pytest.approx(500)
    assert min(result.equity) >= -1e-6
    assert result.equity[-1] == pytest.approx(0.0)
    assert metrics["max_drawdown_pct"] == pytest.approx(100.0)
    assert metrics["total_return_pct"] == pytest.approx(-100.0)


def test_spot_has_no_liquidation() -> None:
    bars = flat(8)
    bars[4] = rec(4, 100, 100.1, 40, 50)
    wide = EntryDecision(1, 80.0, 100.0, "uzak stop")
    result = run_backtest({"X": bars}, ScriptedRule({HOUR: wide}), EXACT)
    assert result.liquidated_at_ms is None
    assert result.trades[0].exit_reason in {"time", "end"}
