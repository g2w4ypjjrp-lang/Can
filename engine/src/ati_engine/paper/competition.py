"""Sanal işlem (paper trading) ve strateji yarışması.

Her strateji (ve fırsat puanı) her piyasa için **ayrı bir sanal hesapla** aynı canlı veriyi
bağımsız olarak değerlendirir:

* **Giriş:** saatlik mum kapandığında (fırsat motorunun aynı strateji defteri) sinyal veren
  semboller güce göre sıralanır, boş pozisyon yuvası kadar en güçlüsü açılır. Dolum, o anki
  piyasadan simüle edilir (odak sembollerinde emir defteri yürütülür, diğerlerinde tahmini
  spread + kayma). Likiditesi düşük semboller elenir.
* **Çıkış:** zarar durdur ve hedef **her canlı işlemde** (tick düzeyinde) denetlenir; ayrıca en
  uzun tutma süresi ve ters sinyal.
* **Funding:** vadelide 00/08/16 UTC'de, canlı mark fiyatı ve funding oranıyla.
* **Kalıcılık:** hesaplar, açık pozisyonlar, işlemler ve saatlik sermaye veritabanındadır;
  motor yeniden başlayınca yarışma kaldığı yerden sürer.
* **Terfi:** ``walk_forward`` aşamasındaki strateji yarışmaya girince ``paper`` olur. Sanal
  işlemde ölçütleri karşılarsa ``live_candidate`` olur. **``live`` aşamasına otomatik geçiş
  yoktur**; gerçek parayla işlem kullanıcının açık onayını gerektirir (G1/G2).

Gerçek borsaya hiçbir emir gönderilmez. Sonuçlar geçmiş performanstır, garanti değildir.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ati_engine.backtest.engine import BacktestConfig, BacktestResult, Trade
from ati_engine.backtest.metrics import compute_metrics
from ati_engine.backtest.service import (
    SCORE_STRATEGY,
    ensure_strategies,
    set_stage,
    strategy_id,
)
from ati_engine.config import PaperSettings
from ati_engine.core.bus import EventBus
from ati_engine.core.clock import Clock, SystemClock
from ati_engine.core.events import SystemEvent
from ati_engine.core.models import Market
from ati_engine.execution.fills import FillSimulator, SimulatedFill
from ati_engine.market.events import AggTrade
from ati_engine.scoring.live import LiveBarScore
from ati_engine.storage.database import Database
from ati_engine.strategies.base import MarketKind
from ati_engine.strategies.library import strategies_for

logger = logging.getLogger(__name__)

HOUR_MS = 3_600_000
FUNDING_PERIOD_MS = 8 * HOUR_MS
LIVE_CANDIDATE = {
    "min_days": 30,
    "min_trades": 30,
    "profit_factor": 1.1,
    "sharpe": 0.5,
    "max_drawdown_pct": 20.0,
}


class PaperTradeEvent(SystemEvent, frozen=True, kw_only=True):
    """Yarışmada sanal pozisyon açıldı/kapandı (gerçek emir değildir)."""

    strategy: str
    market: Market
    symbol: str
    action: str  # opened | closed
    direction: str
    price: float
    qty: float
    net_pnl: float | None = None
    exit_reason: str | None = None
    reason: str = ""


@dataclass
class Account:
    strategy: str  # strateji adı veya "opportunity_score"
    market: Market
    started_at: int
    initial_equity: float
    realized: float = 0.0
    positions: dict[str, Trade] = field(default_factory=dict)
    trades: list[Trade] = field(default_factory=list)
    equity_times: list[int] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)

    @property
    def sid(self) -> str:
        return strategy_id(self.strategy)


@dataclass(frozen=True)
class _Candidate:
    symbol: str
    direction: int
    strength: float
    stop_distance: float
    target_distance: float
    reason: str
    reference: float
    quote_volume_24h: float | None


class PaperCompetition:
    def __init__(
        self,
        *,
        settings: PaperSettings,
        db: Database,
        bus: EventBus,
        fills: FillSimulator,
        interval_ms: int = HOUR_MS,
        clock: Clock | None = None,
        funding_of: Any = None,
    ) -> None:
        self.cfg = settings
        self.db = db
        self.bus = bus
        self.fills = fills
        self.interval_ms = interval_ms
        self.clock = clock or SystemClock()
        # (piyasa, sembol) → (mark fiyatı, funding oranı); yoksa funding uygulanmaz.
        self._funding_of = funding_of
        self.accounts: dict[tuple[str, Market], Account] = {}
        self.last_price: dict[tuple[Market, str], float] = {}
        self._open_index: dict[tuple[Market, str], set[str]] = {}
        self._last_snapshot_ts: int | None = None
        self.stats = {
            "bars": 0,
            "opened": 0,
            "closed": 0,
            "ticks_checked": 0,
            "skipped_cost": 0,
        }

    # --- Kurulum -------------------------------------------------------------------------

    def competitors(self, market: Market) -> list[str]:
        kind: MarketKind = "spot" if market is Market.SPOT else "usdm_futures"
        names = [s.name for s in strategies_for(kind)]
        if self.cfg.competitors:
            names = [n for n in names if n in self.cfg.competitors]
        if not self.cfg.competitors or SCORE_STRATEGY in self.cfg.competitors:
            names.append(SCORE_STRATEGY)
        return names

    async def load(self, markets: Sequence[Market]) -> None:
        await ensure_strategies(self.db)
        now = self.clock.now_ms()
        for market in markets:
            for name in self.competitors(market):
                await self.db.execute(
                    "INSERT OR IGNORE INTO paper_accounts (strategy_id, market, started_at, "
                    "initial_equity) VALUES (?, ?, ?, ?)",
                    (strategy_id(name), market.value, now, self.cfg.initial_equity),
                )
                row = await self.db.fetchone(
                    "SELECT started_at, initial_equity, realized_pnl FROM paper_accounts "
                    "WHERE strategy_id = ? AND market = ?",
                    (strategy_id(name), market.value),
                )
                if row is None:  # pragma: no cover - INSERT OR IGNORE sonrası olamaz
                    raise RuntimeError("Sanal hesap oluşturulamadı")
                account = Account(name, market, int(row[0]), float(row[1]), float(row[2]))
                self.accounts[(name, market)] = account
                await self._load_account_state(account)
        # Yürüyen pencereyi geçen stratejiler sanal işlem aşamasına girer.
        for name in {a.strategy for a in self.accounts.values()}:
            await self.db.execute(
                "UPDATE strategies SET stage = 'paper', stage_changed_at = ? "
                "WHERE id = ? AND stage = 'walk_forward'",
                (now, strategy_id(name)),
            )

    async def _load_account_state(self, account: Account) -> None:
        rows = await self.db.fetchall(
            "SELECT symbol, direction, qty, entry_price, entry_time, stop, target, risk_amount, "
            "fees, funding, bars_held, reason FROM paper_positions "
            "WHERE strategy_id = ? AND market = ?",
            (account.sid, account.market.value),
        )
        for r in rows:
            trade = Trade(
                symbol=r[0],
                direction=int(r[1]),
                entry_time_ms=int(r[4]),
                entry_price=float(r[3]),
                qty=float(r[2]),
                stop=float(r[5]),
                target=float(r[6]),
                risk_amount=float(r[7]),
                reason=r[11],
                fees=float(r[8]),
                funding=float(r[9]),
                bars_held=int(r[10]),
            )
            account.positions[trade.symbol] = trade
            self._open_index.setdefault((account.market, trade.symbol), set()).add(account.strategy)
        trades = await self.db.fetchall(
            "SELECT symbol, direction, qty, entry_price, entry_time, exit_price, exit_time, "
            "exit_reason, fees, funding, risk_amount, reason FROM paper_trades "
            "WHERE strategy_id = ? AND market = ? ORDER BY exit_time",
            (account.sid, account.market.value),
        )
        for r in trades:
            account.trades.append(
                Trade(
                    symbol=r[0],
                    direction=int(r[1]),
                    entry_time_ms=int(r[4]),
                    entry_price=float(r[3]),
                    qty=float(r[2]),
                    stop=0.0,
                    target=0.0,
                    risk_amount=float(r[10]),
                    reason=r[11],
                    exit_time_ms=int(r[6]),
                    exit_price=float(r[5]),
                    exit_reason=r[7],
                    fees=float(r[8]),
                    funding=float(r[9]),
                )
            )
        snapshots = await self.db.fetchall(
            "SELECT ts, equity FROM paper_equity WHERE strategy_id = ? AND market = ? ORDER BY ts",
            (account.sid, account.market.value),
        )
        account.equity_times = [int(r[0]) for r in snapshots]
        account.equity = [float(r[1]) for r in snapshots]

    # --- Hesap ---------------------------------------------------------------------------

    def _price(self, market: Market, symbol: str, fallback: float) -> float:
        return self.last_price.get((market, symbol), fallback)

    def equity(self, account: Account) -> float:
        unrealized = sum(
            t.unrealized(self._price(account.market, s, t.entry_price))
            for s, t in account.positions.items()
        )
        return account.initial_equity + account.realized + unrealized

    # --- Canlı işlemler: tick düzeyinde zarar durdur / hedef ------------------------------

    async def on_trade(self, event: AggTrade) -> None:
        if event.recovered:
            return  # geç gelen (geri alınmış) işlemler tetik için kullanılmaz
        key = (event.market, event.symbol)
        self.last_price[key] = event.price
        holders = self._open_index.get(key)
        if not holders:
            return
        self.stats["ticks_checked"] += 1
        for name in list(holders):
            account = self.accounts.get((name, event.market))
            trade = account.positions.get(event.symbol) if account else None
            if account is None or trade is None:
                continue
            hit = None
            if trade.direction > 0:
                if event.price <= trade.stop:
                    hit = "stop"
                elif event.price >= trade.target:
                    hit = "target"
            elif event.price >= trade.stop:
                hit = "stop"
            elif event.price <= trade.target:
                hit = "target"
            if hit is not None:
                await self._close(account, trade, event.price, event.trade_time_ms, hit, None)

    # --- Kapanan mumlar: giriş, süre ve ters sinyal çıkışı, funding, sermaye ----------------

    async def on_bars(self, updates: Sequence[LiveBarScore]) -> None:
        if not updates:
            return
        self.stats["bars"] += len(updates)
        close_ms = max(u.inputs.snapshot.open_time_ms for u in updates) + self.interval_ms
        by_market: dict[Market, list[LiveBarScore]] = {}
        for update in updates:
            by_market.setdefault(update.market, []).append(update)
            key = (update.market, update.symbol)
            self.last_price.setdefault(key, update.inputs.snapshot.close)
        for market, items in by_market.items():
            if close_ms % FUNDING_PERIOD_MS == 0 and market is Market.USDM_FUTURES:
                await self._apply_funding(market, items)
            for (_, account_market), account in self.accounts.items():
                if account_market is market:
                    await self._step(account, items, close_ms)
        await self._snapshot(close_ms)

    async def _apply_funding(self, market: Market, items: Sequence[LiveBarScore]) -> None:
        if self._funding_of is None:
            return
        for update in items:
            info = self._funding_of(market, update.symbol)
            if info is None:
                continue
            mark, rate = info
            for name in self._open_index.get((market, update.symbol), set()):
                account = self.accounts[(name, market)]
                trade = account.positions[update.symbol]
                trade.funding += trade.direction * trade.qty * mark * rate
                await self._save_position(account, trade)

    def _signal_for(self, account: Account, update: LiveBarScore) -> _Candidate | None:
        snapshot = update.inputs.snapshot
        reference = self._price(update.market, update.symbol, snapshot.close)
        if account.strategy == SCORE_STRATEGY:
            opp = update.opportunity
            if (
                opp.direction == "none"
                or opp.score < self.cfg.score_threshold
                or opp.stop_price is None
                or opp.target_price is None
            ):
                return None
            return _Candidate(
                update.symbol,
                1 if opp.direction == "long" else -1,
                opp.score / 100,
                abs(opp.price - opp.stop_price),
                abs(opp.target_price - opp.price),
                f"fırsat puanı {opp.score:.0f}",
                reference,
                update.inputs.quote_volume_24h,
            )
        for signal in update.inputs.signals:
            if signal.strategy == account.strategy:
                return _Candidate(
                    update.symbol,
                    signal.direction,
                    signal.strength,
                    signal.stop_atr * snapshot.atr,
                    signal.target_atr * snapshot.atr,
                    signal.reason,
                    reference,
                    update.inputs.quote_volume_24h,
                )
        return None

    async def _step(self, account: Account, items: Sequence[LiveBarScore], close_ms: int) -> None:
        shorts = account.market is Market.USDM_FUTURES
        candidates: list[_Candidate] = []
        for update in items:
            candidate = self._signal_for(account, update)
            trade = account.positions.get(update.symbol)
            if trade is not None:
                trade.bars_held += 1
                reference = self._price(update.market, update.symbol, update.inputs.snapshot.close)
                if candidate is not None and candidate.direction != trade.direction:
                    await self._close(account, trade, reference, close_ms, "opposite", None)
                elif trade.bars_held >= self.cfg.max_hold_bars:
                    await self._close(account, trade, reference, close_ms, "time", None)
                else:
                    await self._save_position(account, trade)
                continue
            if candidate is None or (candidate.direction < 0 and not shorts):
                continue
            volume = candidate.quote_volume_24h
            if volume is None or volume < self.cfg.min_quote_volume_24h:
                continue  # likidite filtresi
            candidates.append(candidate)
        free = self.cfg.max_positions - len(account.positions)
        for candidate in sorted(candidates, key=lambda c: -c.strength)[: max(free, 0)]:
            await self._open(account, candidate, close_ms)

    async def _open(self, account: Account, c: _Candidate, now_ms: int) -> None:
        if c.stop_distance <= 0 or c.reference <= 0:
            return
        # Maliyet farkındalığı: zarar durdur uzaklığı gidiş-dönüş maliyetten küçükse veya hedef
        # maliyeti en az ``min_target_cost_ratio`` kat karşılamıyorsa işlem baştan kaybeder
        # (canlı denemede oynaklığı çok düşük bir coinde -40R görüldü).
        cost = self.fills.round_trip_cost(account.market.value, c.quote_volume_24h)
        if (
            c.stop_distance / c.reference < cost
            or c.target_distance / c.reference < self.cfg.min_target_cost_ratio * cost
        ):
            self.stats["skipped_cost"] += 1
            return
        equity = self.equity(account)
        if equity <= 0:
            return
        leverage = self.cfg.futures_leverage if account.market is Market.USDM_FUTURES else 1.0
        qty = equity * self.cfg.risk_per_trade / c.stop_distance
        used = sum(
            t.qty * self._price(account.market, s, t.entry_price)
            for s, t in account.positions.items()
        )
        qty = min(qty, max(equity * leverage - used, 0.0) / c.reference)
        if qty * c.reference < self.cfg.min_notional:
            return
        fill = self.fills.market(
            account.market.value,
            c.symbol,
            c.direction,
            qty,
            reference_price=c.reference,
            quote_volume_24h=c.quote_volume_24h,
        )
        trade = Trade(
            symbol=c.symbol,
            direction=c.direction,
            entry_time_ms=now_ms,
            entry_price=fill.price,
            qty=qty,
            stop=fill.price - c.direction * c.stop_distance,
            target=fill.price + c.direction * c.target_distance,
            risk_amount=qty * c.stop_distance,
            reason=c.reason,
            fees=fill.fee,
        )
        account.positions[c.symbol] = trade
        self._open_index.setdefault((account.market, c.symbol), set()).add(account.strategy)
        self.stats["opened"] += 1
        await self._save_position(account, trade)
        await self.bus.publish(
            PaperTradeEvent(
                strategy=account.strategy,
                market=account.market,
                symbol=c.symbol,
                action="opened",
                direction="long" if c.direction > 0 else "short",
                price=fill.price,
                qty=qty,
                reason=c.reason,
            )
        )

    async def _close(
        self,
        account: Account,
        trade: Trade,
        reference: float,
        now_ms: int,
        reason: str,
        fill: SimulatedFill | None,
    ) -> None:
        if fill is None:
            fill = self.fills.market(
                account.market.value,
                trade.symbol,
                -trade.direction,
                trade.qty,
                reference_price=reference,
            )
        trade.exit_price = fill.price
        trade.exit_time_ms = now_ms
        trade.exit_reason = reason  # type: ignore[assignment]
        trade.fees += fill.fee
        account.realized += trade.net_pnl
        account.positions.pop(trade.symbol, None)
        account.trades.append(trade)
        holders = self._open_index.get((account.market, trade.symbol))
        if holders is not None:
            holders.discard(account.strategy)
        self.stats["closed"] += 1
        await self.db.execute(
            "DELETE FROM paper_positions WHERE strategy_id = ? AND market = ? AND symbol = ?",
            (account.sid, account.market.value, trade.symbol),
        )
        await self.db.execute(
            """
            INSERT INTO paper_trades (strategy_id, market, symbol, direction, qty, entry_price,
                entry_time, exit_price, exit_time, exit_reason, fees, funding, risk_amount,
                net_pnl, reason, fill_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account.sid,
                account.market.value,
                trade.symbol,
                trade.direction,
                trade.qty,
                trade.entry_price,
                trade.entry_time_ms,
                fill.price,
                now_ms,
                reason,
                trade.fees,
                trade.funding,
                trade.risk_amount,
                trade.net_pnl,
                trade.reason,
                fill.source,
            ),
        )
        await self.db.execute(
            "UPDATE paper_accounts SET realized_pnl = ? WHERE strategy_id = ? AND market = ?",
            (account.realized, account.sid, account.market.value),
        )
        await self.bus.publish(
            PaperTradeEvent(
                strategy=account.strategy,
                market=account.market,
                symbol=trade.symbol,
                action="closed",
                direction="long" if trade.direction > 0 else "short",
                price=fill.price,
                qty=trade.qty,
                net_pnl=round(trade.net_pnl, 6),
                exit_reason=reason,
                reason=trade.reason,
            )
        )

    async def _save_position(self, account: Account, t: Trade) -> None:
        await self.db.execute(
            """
            INSERT OR REPLACE INTO paper_positions (strategy_id, market, symbol, direction, qty,
                entry_price, entry_time, stop, target, risk_amount, fees, funding, bars_held,
                reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account.sid,
                account.market.value,
                t.symbol,
                t.direction,
                t.qty,
                t.entry_price,
                t.entry_time_ms,
                t.stop,
                t.target,
                t.risk_amount,
                t.fees,
                t.funding,
                t.bars_held,
                t.reason,
            ),
        )

    # --- Sermaye, metrikler ve terfi -------------------------------------------------------

    async def _snapshot(self, ts: int) -> None:
        if self._last_snapshot_ts == ts:
            return
        self._last_snapshot_ts = ts
        rows = []
        for account in self.accounts.values():
            value = self.equity(account)
            account.equity_times.append(ts)
            account.equity.append(value)
            rows.append((account.sid, account.market.value, ts, value))
        await self.db.executemany(
            "INSERT OR REPLACE INTO paper_equity (strategy_id, market, ts, equity) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
        await self._evaluate_promotions(ts)

    def account_metrics(self, account: Account) -> dict[str, Any]:
        result = BacktestResult(
            rule=account.strategy,
            config=BacktestConfig(),
            trades=account.trades,
            equity_times=[account.started_at, *account.equity_times],
            equity=[account.initial_equity, *account.equity],
            bars_per_year=365 * 86_400_000 / self.interval_ms,
        )
        metrics = compute_metrics(result)
        metrics["equity"] = round(self.equity(account), 4)
        metrics["open_positions"] = len(account.positions)
        metrics["days"] = round((self.clock.now_ms() - account.started_at) / 86_400_000, 2)
        return metrics

    def combined_metrics(self, strategy: str) -> dict[str, Any]:
        """Bir stratejinin tüm piyasa hesaplarının birleşimi (kayıt defteri piyasadan
        bağımsızdır)."""
        accounts = [a for a in self.accounts.values() if a.strategy == strategy]
        if not accounts:
            return {}
        times = sorted({t for a in accounts for t in a.equity_times})
        curves = []
        for a in accounts:
            values = dict(zip(a.equity_times, a.equity, strict=True))
            last = a.initial_equity
            series = []
            for t in times:
                last = values.get(t, last)
                series.append(last)
            curves.append(series)
        combined = [sum(v) for v in zip(*curves, strict=True)] if curves else []
        start = min(a.started_at for a in accounts)
        result = BacktestResult(
            rule=strategy,
            config=BacktestConfig(),
            trades=[t for a in accounts for t in a.trades],
            equity_times=[start, *times],
            equity=[sum(a.initial_equity for a in accounts), *combined],
            bars_per_year=365 * 86_400_000 / self.interval_ms,
        )
        metrics = compute_metrics(result)
        metrics["days"] = round((self.clock.now_ms() - start) / 86_400_000, 2)
        metrics["window_start"] = start
        return metrics

    async def _evaluate_promotions(self, ts: int) -> None:
        for strategy in sorted({a.strategy for a in self.accounts.values()}):
            sid = strategy_id(strategy)
            metrics = self.combined_metrics(strategy)
            if not metrics:
                continue
            await self.db.execute(
                "DELETE FROM strategy_metrics WHERE strategy_id = ? AND mode = 'paper'", (sid,)
            )
            await self.db.execute(
                """
                INSERT INTO strategy_metrics (strategy_id, mode, window_start, window_end,
                    trades, win_rate, profit_factor, sharpe, sortino, max_drawdown, net_pnl,
                    computed_at)
                VALUES (?, 'paper', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sid,
                    metrics["window_start"],
                    ts,
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
            if passes_live_candidate(metrics):
                row = await self.db.fetchone("SELECT stage FROM strategies WHERE id = ?", (sid,))
                if row and row[0] == "paper":
                    await set_stage(self.db, sid, "live_candidate")
                    logger.info("Strateji canlı adayı oldu", extra={"strategy": sid})

    def leaderboard(self, market: Market | None = None) -> list[dict[str, Any]]:
        rows = []
        for (name, account_market), account in self.accounts.items():
            if market is not None and account_market is not market:
                continue
            metrics = self.account_metrics(account)
            rows.append({"strategy": name, "market": account_market.value, **metrics})
        rows.sort(key=lambda r: -(r["equity"] or 0))
        return rows


def passes_live_candidate(metrics: dict[str, Any]) -> bool:
    return (
        (metrics.get("days") or 0) >= LIVE_CANDIDATE["min_days"]
        and (metrics.get("trades") or 0) >= LIVE_CANDIDATE["min_trades"]
        and (metrics.get("profit_factor") or 0) >= LIVE_CANDIDATE["profit_factor"]
        and (metrics.get("sharpe") or -1) >= LIVE_CANDIDATE["sharpe"]
        and (metrics.get("max_drawdown_pct") or 100) <= LIVE_CANDIDATE["max_drawdown_pct"]
    )
