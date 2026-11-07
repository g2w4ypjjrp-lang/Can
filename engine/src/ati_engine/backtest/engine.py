"""Olay güdümlü geriye dönük test motoru.

**Aynı strateji kodu:** sinyaller canlıdaki ``StrategyBook`` ile, aynı göstergeler ve aynı
stratejilerle üretilir. Önce her sembolün mumları bir kez işlenip her mumun görünümü
(gösterge anlık görüntüsü + strateji sinyalleri + seviyeler) kaydedilir; ardından farklı giriş
kuralları bu kayıt üzerinde hızlıca simüle edilir.

**İleriye bakma yok:**

* Sinyal mumun **kapanışında** hesaplanır; emir bir **sonraki mumun açılışında** dolar.
* Zarar durdur/hedef, girişten sonraki mumlarda en yüksek/en düşük fiyatla denetlenir.
  Aynı mumda ikisi birden değerse **önce zarar durdurun** çalıştığı varsayılır (ihtiyatlı).
  Fiyat seviyenin ötesinde açılırsa (boşluk) dolum açılış fiyatından olur.

**Maliyetler:** iki yönde alıcı (taker) komisyonu, likiditeye göre spread + kayma, vadelide
funding (00/08/16 UTC'de, o an bilinen oranla; long pozitif oranda öder).

**Pozisyon büyüklüğü:** işlem başına sermayenin ``risk_per_trade`` kadarı riske edilir
(miktar = risk / zarar durdur uzaklığı); toplam pozisyon değeri ``sermaye x max_leverage``
ile sınırlıdır. Spot yalnızca long'dur.

Hesaplar araştırma amaçlı ``float`` ile yapılır; gerçek emir yürütmede ``Decimal`` kullanılır.
Sonuçlar geçmişi anlatır, geleceği garanti etmez.
"""

from __future__ import annotations

import heapq
import math
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from ati_engine.analysis.features import Snapshot
from ati_engine.history.levels import Level
from ati_engine.ml.dataset import _bar, _futures
from ati_engine.scoring.costs import CostModel, CostSettingsView
from ati_engine.scoring.score import OpportunityScorer, ScoreInputs
from ati_engine.strategies.base import MarketKind, StrategySignal
from ati_engine.strategies.book import StrategyBook

FUNDING_PERIOD_MS = 8 * 3_600_000
# Vadelide sermaye, açık pozisyon değerinin bu oranına (bakım teminatı) düşerse tüm pozisyonlar
# tasfiye edilir ve test durur. Binance BTC/ETH ilk kademe ~%0,4-0,5 (yaklaşık, ihtiyatlı).
MAINTENANCE_MARGIN = 0.005

# --- Kayıt -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BarRecord:
    """Bir mumun ham değerleri ve (ısınma sonrası) o mumun kapanışındaki görünüm."""

    time_ms: int
    open: float
    high: float
    low: float
    close: float
    quote_volume: float
    funding_rate: float | None
    snapshot: Snapshot | None
    signals: tuple[StrategySignal, ...]
    levels: tuple[Level, ...]


def record_symbol(
    rows: Sequence[Sequence[Any]], *, market: MarketKind, symbol: str, futures: bool = False
) -> list[BarRecord]:
    """Mumları sırayla strateji defterinden geçirir (canlıdakiyle aynı kod)."""
    book = StrategyBook(market, symbol)
    records = []
    for row in rows:
        bar = _bar(row)
        update = book.update(bar, _futures(row) if futures else None)
        funding = float(row[8]) if futures and len(row) > 8 and row[8] is not None else None
        records.append(
            BarRecord(
                time_ms=bar.open_time_ms,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                quote_volume=bar.quote_volume,
                funding_rate=funding,
                snapshot=update.snapshot if update else None,
                signals=update.signals if update else (),
                levels=update.levels if update else (),
            )
        )
    return records


# --- Giriş kuralları ------------------------------------------------------------------------


@dataclass(frozen=True)
class EntryDecision:
    direction: int
    stop_atr: float
    target_atr: float
    reason: str
    # Verilirse risk tabanlı boyut yerine sermayenin bu oranı kadar pozisyon açılır; zarar
    # durdur ve hedef kullanılmaz (ör. al-ve-tut karşılaştırması).
    fixed_fraction: float | None = None


class EntryRule(Protocol):
    @property
    def name(self) -> str: ...

    def decide(
        self, symbol: str, record: BarRecord, quote_volume_24h: float | None
    ) -> EntryDecision | None: ...


@dataclass
class StrategyRule:
    """Tek bir stratejinin sinyaliyle giriş; zarar durdur/hedef stratejinin önerisi (veya
    verilen çarpanlar)."""

    strategy: str
    min_strength: float = 0.0
    stop_atr: float | None = None
    target_atr: float | None = None

    @property
    def name(self) -> str:
        return self.strategy

    def decide(
        self, symbol: str, record: BarRecord, quote_volume_24h: float | None
    ) -> EntryDecision | None:
        for signal in record.signals:
            if signal.strategy == self.strategy and signal.strength >= self.min_strength:
                return EntryDecision(
                    signal.direction,
                    self.stop_atr or signal.stop_atr,
                    self.target_atr or signal.target_atr,
                    signal.reason,
                )
        return None


@dataclass
class ScoreRule:
    """Fırsat puanı eşiğiyle giriş (Aşama 7 puanı; zarar durdur/hedef puanlayıcının önerisi)."""

    threshold: float
    scorer: OpportunityScorer
    market: MarketKind
    interval: str = "1h"
    interval_hours: float = 1.0
    horizon_bars: int = 4

    @property
    def name(self) -> str:
        return f"score>={self.threshold:g}"

    def decide(
        self, symbol: str, record: BarRecord, quote_volume_24h: float | None
    ) -> EntryDecision | None:
        if record.snapshot is None:
            return None
        opp = self.scorer.score(
            ScoreInputs(
                market=self.market,
                symbol=symbol,
                interval=self.interval,
                interval_hours=self.interval_hours,
                horizon_bars=self.horizon_bars,
                snapshot=record.snapshot,
                signals=record.signals,
                levels=record.levels,
                quote_volume_24h=quote_volume_24h,
            )
        )
        if opp.direction == "none" or opp.score < self.threshold:
            return None
        if opp.stop_price is None or opp.target_price is None:
            return None
        atr = record.snapshot.atr
        return EntryDecision(
            1 if opp.direction == "long" else -1,
            abs(opp.price - opp.stop_price) / atr,
            abs(opp.target_price - opp.price) / atr,
            f"puan {opp.score:.0f}",
        )


@dataclass
class BuyAndHoldRule:
    """Karşılaştırma: ilk fırsatta long girip sonuna kadar tutar."""

    name: str = "al_ve_tut"

    def decide(
        self, symbol: str, record: BarRecord, quote_volume_24h: float | None
    ) -> EntryDecision | None:
        if record.snapshot is None:
            return None
        return EntryDecision(1, 0.0, 0.0, "al ve tut", fixed_fraction=1.0)


# --- Yapılandırma, işlem, sonuç --------------------------------------------------------------


@dataclass(frozen=True)
class BacktestConfig:
    market: MarketKind = "spot"
    initial_equity: float = 10_000.0
    risk_per_trade: float = 0.01
    max_positions: int = 5
    max_leverage: float = 1.0
    taker_fee: float | None = None  # verilmezse piyasaya göre (Spot %0,10, Futures %0,05)
    slippage_bps: float | None = None  # tek yön; verilmezse 24 saatlik hacme göre
    max_hold_bars: int = 24
    allow_short: bool | None = None  # verilmezse yalnızca vadelide
    exit_on_opposite: bool = True
    min_notional: float = 10.0
    trade_start_ms: int | None = None  # bu zamandan önce yeni işlem açılmaz (ısınma)
    trade_end_ms: int | None = None  # bu zamanda açık pozisyonlar kapatılır

    @property
    def fee(self) -> float:
        if self.taker_fee is not None:
            return self.taker_fee
        return 0.001 if self.market == "spot" else 0.0005

    @property
    def shorts(self) -> bool:
        if self.allow_short is not None:
            return self.allow_short and self.market != "spot"
        return self.market != "spot"


ExitReason = Literal["stop", "target", "time", "opposite", "end", "liquidation"]


@dataclass
class Trade:
    symbol: str
    direction: int
    entry_time_ms: int
    entry_price: float
    qty: float
    stop: float
    target: float
    risk_amount: float
    reason: str
    exit_time_ms: int | None = None
    exit_price: float | None = None
    exit_reason: ExitReason | None = None
    fees: float = 0.0
    funding: float = 0.0  # pozitif = ödenen
    bars_held: int = 0

    @property
    def gross_pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        return self.direction * self.qty * (self.exit_price - self.entry_price)

    @property
    def net_pnl(self) -> float:
        return self.gross_pnl - self.fees - self.funding

    @property
    def r_multiple(self) -> float:
        return self.net_pnl / self.risk_amount if self.risk_amount > 0 else 0.0

    @property
    def return_pct(self) -> float:
        notional = self.qty * self.entry_price
        return self.net_pnl / notional * 100 if notional > 0 else 0.0

    def unrealized(self, price: float) -> float:
        return self.direction * self.qty * (price - self.entry_price) - self.fees - self.funding


@dataclass
class BacktestResult:
    rule: str
    config: BacktestConfig
    trades: list[Trade]
    equity_times: list[int]
    equity: list[float]
    bars_per_year: float
    exposure_bars: int = 0
    total_bars: int = 0
    liquidated_at_ms: int | None = None
    insurance_shortfall: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)


# --- Motor -------------------------------------------------------------------------------------


def _slippage_for(quote_volume_24h: float | None, configured_bps: float | None) -> float:
    if configured_bps is not None:
        return configured_bps / 10_000
    cost = CostModel(CostSettingsView()).estimate(
        "spot", direction=1, holding_hours=0, quote_volume_24h=quote_volume_24h
    )
    # Tahmini gidiş-dönüş spread + kayma (%) → tek yön oran.
    return (cost.spread_pct + cost.slippage_pct) / 2 / 100


@dataclass
class _Pending:
    decision: EntryDecision
    atr: float
    signal_time_ms: int


def run_backtest(
    data: Mapping[str, Sequence[BarRecord]],
    rule: EntryRule,
    config: BacktestConfig,
    *,
    interval_ms: int = 3_600_000,
    metrics_fn: Callable[[BacktestResult], dict[str, Any]] | None = None,
) -> BacktestResult:
    """Birden çok sembolü tek portföyde, zaman sırasıyla simüle eder."""
    fee = config.fee
    day_bars = max(1, 86_400_000 // interval_ms)
    equity_realized = config.initial_equity
    open_trades: dict[str, Trade] = {}
    pending_entry: dict[str, _Pending] = {}
    pending_exit: set[str] = set()
    closed: list[Trade] = []
    last_price: dict[str, float] = {}
    quote_windows: dict[str, deque[float]] = {s: deque(maxlen=day_bars) for s in data}
    equity_times: list[int] = []
    equity_values: list[float] = []
    exposure = 0
    total = 0
    liquidated_at: int | None = None
    insurance_shortfall = 0.0

    def equity_now() -> float:
        return equity_realized + sum(
            t.unrealized(last_price.get(s, t.entry_price)) for s, t in open_trades.items()
        )

    def close(symbol: str, price: float, time_ms: int, reason: ExitReason, slip: float) -> None:
        nonlocal equity_realized
        trade = open_trades.pop(symbol)
        fill = price * (1 - slip) if trade.direction > 0 else price * (1 + slip)
        trade.exit_price = fill
        trade.exit_time_ms = time_ms
        trade.exit_reason = reason
        trade.fees += abs(trade.qty * fill) * fee
        equity_realized += trade.net_pnl
        closed.append(trade)

    # Zaman sıralı birleştirme (sembol başına sıralı listeler).
    heap: list[tuple[int, str, int]] = []
    for symbol, records in data.items():
        if records:
            heapq.heappush(heap, (records[0].time_ms, symbol, 0))
    current_time: int | None = None

    def flush_equity(time_ms: int) -> None:
        equity_times.append(time_ms)
        equity_values.append(equity_now())

    while heap:
        time_ms, symbol, index = heapq.heappop(heap)
        if current_time is not None and time_ms != current_time:
            flush_equity(current_time)
            total += 1
            if open_trades:
                exposure += 1
        current_time = time_ms
        records = data[symbol]
        if index + 1 < len(records):
            heapq.heappush(heap, (records[index + 1].time_ms, symbol, index + 1))
        rec = records[index]
        window = quote_windows[symbol]
        window.append(rec.quote_volume)
        quote_24h = sum(window) if len(window) == day_bars else None
        slip = _slippage_for(quote_24h, config.slippage_bps)
        ended = (
            config.trade_end_ms is not None and time_ms >= config.trade_end_ms
        ) or liquidated_at is not None

        # 1) Açılışta bekleyen çıkış ve girişler.
        if symbol in pending_exit and symbol in open_trades:
            close(symbol, rec.open, time_ms, "opposite", slip)
        pending_exit.discard(symbol)
        pending = pending_entry.pop(symbol, None)
        if pending is not None and symbol not in open_trades and not ended:
            equity = equity_now()
            chosen = pending.decision
            stop_distance = chosen.stop_atr * pending.atr
            direction = chosen.direction
            fill = rec.open * (1 + slip) if direction > 0 else rec.open * (1 - slip)
            fixed = chosen.fixed_fraction
            if (stop_distance > 0 or fixed) and equity > 0:
                if fixed:
                    qty = equity * fixed / fill
                else:
                    qty = equity * config.risk_per_trade / stop_distance
                used = sum(t.qty * last_price.get(s, t.entry_price) for s, t in open_trades.items())
                room = equity * config.max_leverage - used
                qty = min(qty, max(room, 0.0) / fill)
                if qty * fill >= config.min_notional:
                    if fixed:
                        stop, target, risk = (
                            (0.0 if direction > 0 else math.inf),
                            (math.inf if direction > 0 else 0.0),
                            qty * fill,
                        )
                    else:
                        stop = fill - direction * stop_distance
                        target = fill + direction * chosen.target_atr * pending.atr
                        risk = qty * stop_distance
                    new_trade = Trade(
                        symbol=symbol,
                        direction=direction,
                        entry_time_ms=time_ms,
                        entry_price=fill,
                        qty=qty,
                        stop=stop,
                        target=target,
                        risk_amount=risk,
                        reason=chosen.reason,
                    )
                    new_trade.fees = qty * fill * fee
                    open_trades[symbol] = new_trade

        # 2) Açık pozisyon: funding, zarar durdur / hedef / süre.
        trade: Trade | None = open_trades.get(symbol)
        if trade is not None:
            if (
                time_ms % FUNDING_PERIOD_MS == 0
                and rec.funding_rate is not None
                and time_ms != trade.entry_time_ms
            ):
                trade.funding += trade.direction * trade.qty * rec.open * rec.funding_rate
            if trade.direction > 0:
                if rec.low <= trade.stop:
                    close(symbol, min(rec.open, trade.stop), time_ms, "stop", slip)
                elif rec.high >= trade.target:
                    close(symbol, max(rec.open, trade.target), time_ms, "target", slip)
            else:
                if rec.high >= trade.stop:
                    close(symbol, max(rec.open, trade.stop), time_ms, "stop", slip)
                elif rec.low <= trade.target:
                    close(symbol, min(rec.open, trade.target), time_ms, "target", slip)
        trade = open_trades.get(symbol)
        if trade is not None:
            trade.bars_held += 1
            if ended:
                close(symbol, rec.close, time_ms, "end", slip)
            elif trade.bars_held >= config.max_hold_bars:
                close(symbol, rec.close, time_ms, "time", slip)
        last_price[symbol] = rec.close

        # Tasfiye: vadeli hesapta sermaye, mum içindeki en kötü fiyatta bakım teminatına inerse
        # tüm pozisyonlar kapanır. Hesap eksiye düşmez; açık borsa sigorta fonuna kalır
        # (``insurance_shortfall`` olarak raporlanır).
        if config.market != "spot" and open_trades and liquidated_at is None:
            marks = dict(last_price)
            current = open_trades.get(symbol)
            if current is not None:
                marks[symbol] = rec.low if current.direction > 0 else rec.high
            unrealized = sum(
                t.unrealized(marks.get(s, t.entry_price)) for s, t in open_trades.items()
            )
            notional = sum(t.qty * marks.get(s, t.entry_price) for s, t in open_trades.items())
            if equity_realized + unrealized <= notional * MAINTENANCE_MARGIN:
                for open_symbol in list(open_trades):
                    close(open_symbol, marks[open_symbol], time_ms, "liquidation", slip)
                if equity_realized < 0:
                    insurance_shortfall += -equity_realized
                    equity_realized = 0.0
                liquidated_at = time_ms
                pending_entry.clear()
                continue

        # 3) Kapanışta karar (bir sonraki açılışta uygulanır).
        if ended or rec.snapshot is None:
            continue
        if config.trade_start_ms is not None and time_ms < config.trade_start_ms:
            continue
        decision = rule.decide(symbol, rec, quote_24h)
        if decision is None:
            continue
        trade = open_trades.get(symbol)
        if trade is not None:
            if config.exit_on_opposite and decision.direction != trade.direction:
                pending_exit.add(symbol)
            continue
        if decision.direction < 0 and not config.shorts:
            continue
        if len(open_trades) + len(pending_entry) >= config.max_positions:
            continue
        pending_entry[symbol] = _Pending(decision, rec.snapshot.atr, time_ms)

    if current_time is not None:
        for symbol in list(open_trades):
            close(symbol, last_price[symbol], current_time, "end", 0.0)
        flush_equity(current_time)
        total += 1
    result = BacktestResult(
        rule=rule.name,
        config=config,
        trades=closed,
        equity_times=equity_times,
        equity=equity_values,
        bars_per_year=365 * 86_400_000 / interval_ms,
        exposure_bars=exposure,
        total_bars=total,
        liquidated_at_ms=liquidated_at,
        insurance_shortfall=insurance_shortfall,
    )
    if metrics_fn is not None:
        result.metrics = metrics_fn(result)
    return result


def nan_to_none(value: float) -> float | None:
    return None if value is None or math.isnan(value) or math.isinf(value) else value
