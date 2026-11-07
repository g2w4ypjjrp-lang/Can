"""Backtest paketi: tüm stratejiler + puan eşikleri + al-ve-tut karşılaştırması, yürüyen pencere
doğrulaması, strateji kayıt defterine yazma ve aşama terfisi.

**Terfi kuralı** (yalnızca ``backtest → walk_forward``; ``live`` aşamasına hiçbir zaman
otomatik geçilmez, veritabanı bunu kullanıcı onayı olmadan reddeder):
yürüyen pencerenin örneklem dışı sonucunda en az 30 işlem, Profit Factor ≥ 1,1, Sharpe ≥ 0,5
ve maksimum düşüş ≤ %30. Kriterleri karşılamayan strateji ``backtest`` aşamasında kalır.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from ati_engine.backtest.engine import (
    BacktestConfig,
    BarRecord,
    BuyAndHoldRule,
    EntryRule,
    ScoreRule,
    StrategyRule,
    run_backtest,
)
from ati_engine.backtest.metrics import compute_metrics
from ati_engine.backtest.validation import purged_kfold, walk_forward
from ati_engine.scoring.costs import CostModel, CostSettingsView
from ati_engine.scoring.score import OpportunityScorer
from ati_engine.storage.database import Database
from ati_engine.strategies.base import MarketKind
from ati_engine.strategies.library import ALL_STRATEGIES, strategies_for

logger = logging.getLogger(__name__)

PROMOTION = {"min_trades": 30, "profit_factor": 1.1, "sharpe": 0.5, "max_drawdown_pct": 30.0}
STOP_TARGET_GRID: tuple[dict[str, float], ...] = (
    {"stop_atr": 1.0, "target_atr": 2.0},
    {"stop_atr": 1.5, "target_atr": 3.0},
    {"stop_atr": 2.0, "target_atr": 4.0},
)
SCORE_THRESHOLDS = (50.0, 60.0, 70.0)
# Puan modunda eşik de bir parametredir: tam dönem sonucundan eşik seçmek seçim yanlılığı
# yaratır. Bu yüzden eşik yürüyen pencerede geçmişte seçilip gelecekte sınanır ve arındırılmış
# çapraz doğrulama ile aşırı uyum olasılığı (PBO) raporlanır.
SCORE_GRID: tuple[dict[str, float], ...] = tuple(
    {"threshold": t} for t in (55.0, 60.0, 65.0, 70.0, 75.0)
)
SCORE_STRATEGY = "opportunity_score"
DISCLAIMER = (
    "Backtest sonuçları geçmiş veride, modellenen maliyetlerle ölçülmüştür; gelecekteki "
    "kazancı garanti etmez."
)


def strategy_id(name: str) -> str:
    return f"{name}.v1"


async def ensure_strategies(db: Database) -> None:
    now = int(time.time() * 1000)
    await db.executemany(
        """
        INSERT OR IGNORE INTO strategies (id, name, version, stage, params, created_at,
                                          stage_changed_at)
        VALUES (?, ?, 1, 'research', '{}', ?, ?)
        """,
        [(strategy_id(s.name), s.name, now, now) for s in ALL_STRATEGIES]
        + [(strategy_id(SCORE_STRATEGY), SCORE_STRATEGY, now, now)],
    )


async def record_metrics(
    db: Database, sid: str, mode: str, start_ms: int, end_ms: int, metrics: Mapping[str, Any]
) -> None:
    await db.execute(
        """
        INSERT OR REPLACE INTO strategy_metrics (strategy_id, mode, window_start, window_end,
            trades, win_rate, profit_factor, sharpe, sortino, max_drawdown, net_pnl, computed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sid,
            mode,
            start_ms,
            end_ms,
            int(metrics.get("trades") or 0),
            metrics.get("win_rate"),
            metrics.get("profit_factor"),
            metrics.get("sharpe"),
            metrics.get("sortino"),
            metrics.get("max_drawdown_pct"),
            str(metrics.get("net_pnl", 0)),
            int(time.time() * 1000),
        ),
    )


def passes_promotion(metrics: Mapping[str, Any]) -> bool:
    return (
        (metrics.get("trades") or 0) >= PROMOTION["min_trades"]
        and (metrics.get("profit_factor") or 0) >= PROMOTION["profit_factor"]
        and (metrics.get("sharpe") or -1) >= PROMOTION["sharpe"]
        and (metrics.get("max_drawdown_pct") or 100) <= PROMOTION["max_drawdown_pct"]
    )


async def set_stage(db: Database, sid: str, stage: str) -> None:
    if stage == "live":  # savunma: canlı aşama yalnızca kullanıcı onayıyla (Aşama 10-11)
        raise ValueError("Canlı aşamaya otomatik geçiş yapılamaz")
    await db.execute(
        "UPDATE strategies SET stage = ?, stage_changed_at = ? WHERE id = ? AND stage <> 'live'",
        (stage, int(time.time() * 1000), sid),
    )


@dataclass(frozen=True)
class SuiteOptions:
    market: MarketKind
    interval: str
    interval_ms: int
    walk_forward: bool = True
    train_bars: int = 24 * 365
    test_bars: int = 24 * 90
    strategies: tuple[str, ...] | None = None  # None: piyasaya uygun tümü (model hariç)


def _row(name: str, kind: str, metrics: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "trades",
        "win_rate",
        "profit_factor",
        "net_pnl",
        "total_return_pct",
        "cagr_pct",
        "sharpe",
        "sortino",
        "max_drawdown_pct",
        "exposure_pct",
        "avg_r",
        "fees",
        "funding",
    )
    return {"name": name, "kind": kind, **{k: metrics.get(k) for k in keys}}


async def run_suite(
    data: Mapping[str, Sequence[BarRecord]],
    options: SuiteOptions,
    config: BacktestConfig,
    *,
    db: Database | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Tüm adayları çalıştırır, sonuçları döndürür ve (verildiyse) kayıt defterine yazar."""
    import asyncio

    say = progress or (lambda _msg: None)
    times = [r.time_ms for recs in data.values() for r in recs]
    start_ms, end_ms = (min(times), max(times)) if times else (0, 0)
    names = options.strategies or tuple(
        s.name for s in strategies_for(options.market) if s.category != "model"
    )
    rules: list[tuple[str, str, EntryRule]] = [(n, "strategy", StrategyRule(n)) for n in names]
    scorer = OpportunityScorer(
        cost_model=CostModel(
            CostSettingsView(
                spot_taker_fee=config.fee if options.market == "spot" else 0.001,
                futures_taker_fee=config.fee if options.market != "spot" else 0.0005,
            )
        )
    )
    hours = options.interval_ms / 3_600_000
    for threshold in SCORE_THRESHOLDS:
        score_rule = ScoreRule(
            threshold, scorer, options.market, options.interval, interval_hours=hours
        )
        rules.append((score_rule.name, "score", score_rule))
    rules.append(("al_ve_tut", "baseline", BuyAndHoldRule()))

    leaderboard = []
    for name, kind, rule in rules:
        say(f"backtest: {name}")
        cfg = (
            replace(config, max_hold_bars=10**9, exit_on_opposite=False)
            if kind == "baseline"
            else config
        )
        result = await asyncio.to_thread(
            run_backtest, data, rule, cfg, interval_ms=options.interval_ms
        )
        metrics = compute_metrics(result)
        leaderboard.append(_row(name, kind, metrics))
        if db is not None and kind == "strategy":
            await record_metrics(db, strategy_id(name), "backtest", start_ms, end_ms, metrics)

    walk: list[dict[str, Any]] = []
    if options.walk_forward:
        for name in names:
            say(f"yürüyen pencere: {name}")

            def make(params: dict[str, Any], strategy: str = name) -> EntryRule:
                return StrategyRule(
                    strategy, stop_atr=params["stop_atr"], target_atr=params["target_atr"]
                )

            try:
                wf = await asyncio.to_thread(
                    walk_forward,
                    data,
                    make_rule=make,
                    grid=list(STOP_TARGET_GRID),
                    config=config,
                    interval_ms=options.interval_ms,
                    train_bars=options.train_bars,
                    test_bars=options.test_bars,
                    objective="sharpe",
                    min_trades=10,
                )
            except ValueError as exc:
                walk.append({"name": name, "error": str(exc)})
                continue
            oos = wf.oos_metrics
            promoted = passes_promotion(oos)
            walk.append(
                {
                    **_row(name, "walk_forward", oos),
                    "windows": len(wf.windows),
                    "param_changes": wf.param_changes,
                    "mean_train_sharpe": wf.mean_train_objective,
                    "promoted": promoted,
                }
            )
            if db is not None:
                sid = strategy_id(name)
                await record_metrics(
                    db, sid, "walk_forward", wf.windows[0].test_start_ms, end_ms, oos
                )
                await set_stage(db, sid, "walk_forward" if promoted else "backtest")
    if options.walk_forward:
        say("yürüyen pencere: fırsat puanı eşiği")

        def make_score(params: dict[str, Any]) -> EntryRule:
            return ScoreRule(
                params["threshold"], scorer, options.market, options.interval, interval_hours=hours
            )

        try:
            wf = await asyncio.to_thread(
                walk_forward,
                data,
                make_rule=make_score,
                grid=list(SCORE_GRID),
                config=config,
                interval_ms=options.interval_ms,
                train_bars=options.train_bars,
                test_bars=options.test_bars,
                objective="sharpe",
                min_trades=10,
            )
            say("arındırılmış çapraz doğrulama: fırsat puanı eşiği")
            cv = await asyncio.to_thread(
                purged_kfold,
                data,
                make_rule=make_score,
                grid=list(SCORE_GRID),
                config=config,
                interval_ms=options.interval_ms,
                folds=5,
                embargo_bars=config.max_hold_bars,  # işlem en fazla bu kadar sürer
                objective="mean_r",
                min_trades=10,
            )
            oos = wf.oos_metrics
            promoted = passes_promotion(oos)
            walk.append(
                {
                    **_row(SCORE_STRATEGY, "walk_forward", oos),
                    "windows": len(wf.windows),
                    "param_changes": wf.param_changes,
                    "mean_train_sharpe": wf.mean_train_objective,
                    "chosen_thresholds": [w.params["threshold"] for w in wf.windows],
                    "purged_cv": {
                        "oos": cv.oos_summary,
                        "pbo": cv.pbo,
                        "folds": [
                            {
                                "threshold": f.params["threshold"],
                                "train_mean_r": f.train_score,
                                "test_mean_r": f.test_score,
                                "test_trades": f.test_trades,
                            }
                            for f in cv.folds
                        ],
                    },
                    "promoted": promoted,
                }
            )
            if db is not None:
                sid = strategy_id(SCORE_STRATEGY)
                await record_metrics(
                    db, sid, "walk_forward", wf.windows[0].test_start_ms, end_ms, oos
                )
                await set_stage(db, sid, "walk_forward" if promoted else "backtest")
        except ValueError as exc:
            walk.append({"name": SCORE_STRATEGY, "error": str(exc)})
    elif db is not None:
        for name in names:
            await db.execute(
                "UPDATE strategies SET stage = 'backtest', stage_changed_at = ? "
                "WHERE id = ? AND stage = 'research'",
                (int(time.time() * 1000), strategy_id(name)),
            )

    leaderboard.sort(key=lambda r: (r["sharpe"] is not None, r["sharpe"] or 0), reverse=True)
    walk.sort(key=lambda r: (r.get("sharpe") is not None, r.get("sharpe") or 0), reverse=True)
    return {
        "market": options.market,
        "interval": options.interval,
        "symbols": sorted(data),
        "start_ms": start_ms,
        "end_ms": end_ms,
        "config": {
            "initial_equity": config.initial_equity,
            "risk_per_trade": config.risk_per_trade,
            "max_positions": config.max_positions,
            "max_leverage": config.max_leverage,
            "taker_fee": config.fee,
            "slippage_bps": config.slippage_bps,
            "max_hold_bars": config.max_hold_bars,
            "shorts": config.shorts,
        },
        "promotion_rule": PROMOTION,
        "leaderboard": leaderboard,
        "walk_forward": walk,
        "disclaimer": DISCLAIMER,
    }


def report_json(report: Mapping[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)


# --- Veri hazırlığı ve arka plan işleri (komut satırı ve yerel API ortak) -------------------


async def prepare_records(
    history: Any,
    market_value: str,
    symbols: Sequence[str],
    interval: str,
    *,
    since_ms: int | None,
    warmup_bars: int = 300,
    progress: Callable[[str], None] | None = None,
) -> dict[str, list[BarRecord]]:
    """Mumları (ve vadelide funding/metrikleri) eşitler, strateji defterinden geçirir."""
    import asyncio

    from ati_engine.analysis.service import _with_quote
    from ati_engine.backtest.engine import record_symbol
    from ati_engine.core.models import Market
    from ati_engine.history.futures_data import FuturesDataSync

    say = progress or (lambda _msg: None)
    market = Market(market_value)
    futures = market is Market.USDM_FUTURES
    kind: MarketKind = "usdm_futures" if futures else "spot"
    data: dict[str, list[BarRecord]] = {}
    for raw in symbols:
        symbol = raw.upper()
        say(f"veri eşitleniyor: {symbol}")
        await history.sync.sync_klines(market, symbol, interval)
        if futures:
            await FuturesDataSync(history.archive, history.store, history.sync.db).sync(
                symbol, since_ms=since_ms
            )
            rows = await history.store.bars_with_futures(symbol, interval)
        else:
            rows = [_with_quote(r) for r in await history.store.candles("spot", symbol, interval)]
        if since_ms is not None:
            first = next((i for i, r in enumerate(rows) if int(r[0]) >= since_ms), len(rows))
            rows = rows[max(0, first - warmup_bars) :]
        say(f"strateji defteri: {symbol} ({len(rows)} mum)")
        data[symbol] = await asyncio.to_thread(
            record_symbol, rows, market=kind, symbol=symbol, futures=futures
        )
    return data


@dataclass
class BacktestJob:
    id: int
    market: str
    symbols: list[str]
    interval: str
    since_ms: int | None
    walk_forward: bool
    state: str = "running"
    stage: str = "başlıyor"
    started_ms: int = 0
    finished_ms: int | None = None
    report_name: str | None = None
    error: str | None = None


class BacktestService:
    """Yerel API için arka planda backtest; raporlar ``backtests/`` dizinine yazılır."""

    def __init__(self, history: Any, db: Database, reports_dir: Any) -> None:
        import asyncio
        import itertools

        self.history = history
        self.db = db
        self.reports_dir = reports_dir
        self.jobs: dict[int, BacktestJob] = {}
        self._ids = itertools.count(1)
        self._lock = asyncio.Lock()
        self._tasks: set[Any] = set()

    def start(
        self,
        market: str,
        symbols: Sequence[str],
        interval: str,
        *,
        since_ms: int | None,
        walk_forward: bool,
        config: BacktestConfig,
    ) -> BacktestJob:
        import asyncio

        from ati_engine.history.archive import INTERVAL_MS

        if interval not in INTERVAL_MS:
            raise ValueError(f"Desteklenmeyen aralık: {interval}")
        job = BacktestJob(
            id=next(self._ids),
            market=market,
            symbols=[s.upper() for s in symbols],
            interval=interval,
            since_ms=since_ms,
            walk_forward=walk_forward,
            started_ms=int(time.time() * 1000),
        )
        self.jobs[job.id] = job
        task = asyncio.create_task(self._run(job, config, INTERVAL_MS[interval]))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def _run(self, job: BacktestJob, config: BacktestConfig, interval_ms: int) -> None:
        import asyncio

        def progress(message: str) -> None:
            job.stage = message

        try:
            async with self._lock:
                data = await prepare_records(
                    self.history,
                    job.market,
                    job.symbols,
                    job.interval,
                    since_ms=job.since_ms,
                    progress=progress,
                )
                await ensure_strategies(self.db)
                kind: MarketKind = "spot" if job.market == "spot" else "usdm_futures"
                report = await run_suite(
                    data,
                    SuiteOptions(
                        market=kind,
                        interval=job.interval,
                        interval_ms=interval_ms,
                        walk_forward=job.walk_forward,
                    ),
                    replace(config, market=kind),
                    db=self.db,
                    progress=progress,
                )
                stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
                name = f"{stamp}-{job.market}-{job.interval}-{job.id}.json"
                self.reports_dir.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(
                    (self.reports_dir / name).write_text, report_json(report), "utf-8"
                )
                job.report_name = name
                job.state = "done"
                job.stage = "tamamlandı"
        except asyncio.CancelledError:
            job.state, job.error = "failed", "iptal edildi"
            raise
        except Exception as exc:
            job.state = "failed"
            job.error = f"{type(exc).__name__}: {exc}"[:300]
            logger.warning("Backtest başarısız", extra={"error": job.error})
        finally:
            job.finished_ms = int(time.time() * 1000)

    def reports(self) -> list[str]:
        if not self.reports_dir.exists():
            return []
        return sorted((p.name for p in self.reports_dir.glob("*.json")), reverse=True)

    def report(self, name: str) -> dict[str, Any]:
        import re

        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}\.json", name):
            raise ValueError("Geçersiz rapor adı")
        path = self.reports_dir / name
        if not path.exists():
            raise FileNotFoundError(name)
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    async def strategies(self) -> list[dict[str, Any]]:
        await ensure_strategies(self.db)
        rows = await self.db.fetchall(
            "SELECT id, name, stage, stage_changed_at, approved_live_by FROM strategies "
            "ORDER BY name"
        )
        catalog = {s.name: s for s in ALL_STRATEGIES}
        result = []
        for sid, name, stage, changed, approved in rows:
            metrics = {}
            for mode in ("backtest", "walk_forward", "paper"):
                row = await self.db.fetchone(
                    "SELECT window_start, window_end, trades, win_rate, profit_factor, sharpe, "
                    "sortino, max_drawdown, net_pnl, computed_at FROM strategy_metrics "
                    "WHERE strategy_id = ? AND mode = ? ORDER BY computed_at DESC LIMIT 1",
                    (sid, mode),
                )
                if row:
                    metrics[mode] = dict(
                        zip(
                            (
                                "window_start",
                                "window_end",
                                "trades",
                                "win_rate",
                                "profit_factor",
                                "sharpe",
                                "sortino",
                                "max_drawdown_pct",
                                "net_pnl",
                                "computed_at",
                            ),
                            row,
                            strict=True,
                        )
                    )
            info = catalog.get(name)
            result.append(
                {
                    "id": sid,
                    "name": name,
                    "title": info.title if info else name,
                    "category": info.category if info else "",
                    "stage": stage,
                    "stage_changed_at": changed,
                    "live_approved": approved is not None,
                    "metrics": metrics,
                }
            )
        return result

    async def close(self) -> None:
        import asyncio
        import contextlib

        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
