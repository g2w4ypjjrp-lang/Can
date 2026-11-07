"""Coin tarayıcı: tüm sembolleri paralel izler, saniyede bir özet tablo üretir ve olağan dışı
durumlarda sinyal yayımlar.

Girdiler (olay veri yolundan):
* ``AggTrade``  → saniyelik agresif alış/satış hacmi ve fiyat izi
* ``Kline``     → kapanan 1 dk mumlardan hacim ve getiri dağılımı (temel çizgi)
* ``TickerBatch`` → 24 saatlik değişim ve hacim
* ``OrderBookTop`` → odak sembollerinde spread, derinlik ve defter dengesizliği
* ``SymbolListed`` → yeni listeleme

Çıktılar:
* ``rows``: her sembol için ``ScanRow`` (yerel API ``/v1/scanner/top``)
* ``MarketSignal`` olayları (masaüstü/iOS bildirimi + yerel veritabanı kaydı)

Sinyaller yatırım tavsiyesi değildir; fırsat puanı (Aşama 7) ve risk kapısı (Aşama 11)
tarafından girdi olarak kullanılır.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ati_engine.config import ScannerSettings
from ati_engine.core.bus import EventBus, OverflowPolicy
from ati_engine.core.clock import Clock, SystemClock
from ati_engine.core.events import SystemEvent
from ati_engine.core.models import Market, Severity
from ati_engine.exchange.rate_limit import Priority
from ati_engine.market.events import AggTrade, Kline, OrderBookTop, SymbolListed, TickerBatch
from ati_engine.scanner.features import FlowWindows, PriceTrail, RollingStats, imbalance, pct_change

if TYPE_CHECKING:
    from ati_engine.market.service import MarketDataService
    from ati_engine.storage.database import Database

logger = logging.getLogger(__name__)


class SignalKind(StrEnum):
    VOLUME_SPIKE = "volume_spike"
    PRICE_MOVE = "price_move"
    FLOW_IMBALANCE = "flow_imbalance"
    LIQUIDITY_DROP = "liquidity_drop"
    NEW_LISTING = "new_listing"


class MarketSignal(SystemEvent, frozen=True, kw_only=True):
    market: Market
    symbol: str
    kind: SignalKind
    severity: Severity
    value: float
    threshold: float
    message: str
    details: dict[str, Any] = {}  # noqa: RUF012 - msgspec değişmez varsayılanı kopyalar


@dataclass
class ScanRow:
    market: str
    symbol: str
    last_price: float | None
    change_1m_pct: float | None
    change_5m_pct: float | None
    change_15m_pct: float | None
    change_24h_pct: float | None
    quote_volume_24h: float | None
    quote_volume_60s: float
    volume_z_60s: float | None
    price_z_60s: float | None
    volatility_1m_pct: float | None
    imbalance_60s: float | None
    imbalance_300s: float | None
    buy_quote_300s: float
    sell_quote_300s: float
    spread_bps: float | None
    book_imbalance_10: float | None
    book_notional_10: float | None
    baseline_minutes: int
    listed_at_ms: int | None
    signals: list[str]
    updated_ms: int


@dataclass
class _Book:
    bid: float
    ask: float
    notional: float
    imbalance: float
    baseline: float | None = None
    samples: int = 0  # temel çizgiye katılan saniyelik tur sayısı
    low_streak: int = 0  # derinliğin eşik altında kaldığı ardışık tur sayısı


@dataclass
class SymbolState:
    market: Market
    symbol: str
    baseline: int
    flow: FlowWindows = field(default_factory=FlowWindows)
    trail: PriceTrail = field(default_factory=PriceTrail)
    vol_stats: RollingStats = field(init=False)
    ret_stats: RollingStats = field(init=False)
    last_close: float | None = None
    last_closed_open_ms: int | None = None
    change_24h: float | None = None
    quote_volume_24h: float | None = None
    ticker_last: float | None = None
    book: _Book | None = None
    listed_at_ms: int | None = None
    last_signal: dict[SignalKind, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.vol_stats = RollingStats(self.baseline)
        self.ret_stats = RollingStats(self.baseline)

    def add_closed_candle(self, open_ms: int, close: float, quote_volume: float) -> None:
        if self.last_closed_open_ms is not None and open_ms <= self.last_closed_open_ms:
            return  # aynı mum ikinci kez (bağlantı yenileme / ısınma örtüşmesi)
        self.vol_stats.push(math.log1p(max(quote_volume, 0.0)))
        if self.last_close and close > 0:
            self.ret_stats.push(math.log(close / self.last_close))
        self.last_close = close
        self.last_closed_open_ms = open_ms


class MarketScanner:
    def __init__(
        self,
        *,
        settings: ScannerSettings,
        bus: EventBus,
        db: Database | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._cfg = settings
        self._bus = bus
        self._db = db
        self._clock = clock or SystemClock()
        self._states: dict[tuple[Market, str], SymbolState] = {}
        self.rows: dict[tuple[Market, str], ScanRow] = {}
        self.signals: deque[MarketSignal] = deque(maxlen=500)
        self.tick_ms_last = 0.0
        self.tick_ms_max = 0.0
        self.ticks = 0
        self.warmup_done: dict[str, int] = {}
        self._attached = False

    # --- Olaylar ---------------------------------------------------------------------------

    def attach(self) -> None:
        if self._attached:
            return
        self._attached = True
        bus = self._bus
        bus.subscribe(AggTrade, self.on_trade, name="scanner-trades", maxsize=200_000)
        bus.subscribe(Kline, self.on_kline, name="scanner-klines", maxsize=50_000)
        bus.subscribe(TickerBatch, self.on_tickers, name="scanner-tickers", maxsize=100)
        bus.subscribe(OrderBookTop, self.on_book, name="scanner-books", maxsize=10_000)
        bus.subscribe(
            SymbolListed, self.on_listed, name="scanner-listings", policy=OverflowPolicy.BLOCK
        )

    def state(self, market: Market, symbol: str) -> SymbolState:
        key = (market, symbol)
        state = self._states.get(key)
        if state is None:
            state = SymbolState(market=market, symbol=symbol, baseline=self._cfg.baseline_minutes)
            self._states[key] = state
        return state

    def on_trade(self, event: AggTrade) -> None:
        state = self.state(event.market, event.symbol)
        sec = event.trade_time_ms // 1000
        state.flow.add(sec, event.price * event.qty, taker_buy=not event.buyer_is_maker)
        if not event.recovered:
            state.trail.update(sec, event.price)

    def on_kline(self, event: Kline) -> None:
        if event.interval != "1m":
            return
        state = self.state(event.market, event.symbol)
        if event.closed:
            state.add_closed_candle(event.open_time_ms, event.close, event.quote_volume)
        if state.trail.latest is None:
            # aggTrade akışı kapalıysa fiyat izi mumdan beslenir.
            state.trail.update(event.event_time_ms // 1000, event.close)

    def on_tickers(self, event: TickerBatch) -> None:
        for ticker in event.tickers:
            state = self._states.get((event.market, ticker.symbol))
            if state is None:
                continue  # izlenmeyen sembol (evren dışı)
            state.change_24h = ticker.change_pct
            state.quote_volume_24h = ticker.quote_volume
            state.ticker_last = ticker.last

    def on_book(self, event: OrderBookTop) -> None:
        state = self.state(event.market, event.symbol)
        notional = event.bid_notional_10 + event.ask_notional_10
        previous = state.book
        state.book = _Book(
            bid=event.best_bid,
            ask=event.best_ask,
            notional=notional,
            imbalance=event.imbalance_10,
            baseline=previous.baseline if previous else None,
            samples=previous.samples if previous else 0,
            low_streak=previous.low_streak if previous else 0,
        )

    async def on_listed(self, event: SymbolListed) -> None:
        state = self.state(event.market, event.symbol)
        state.listed_at_ms = event.onboard_date_ms or self._clock.now_ms()
        await self._emit(
            state,
            SignalKind.NEW_LISTING,
            Severity.INFO,
            value=1.0,
            threshold=1.0,
            message=f"{event.symbol} ({event.market.value}) işlem görmeye başladı",
        )

    # --- Hesaplama --------------------------------------------------------------------------

    def _row(self, state: SymbolState, now_ms: int) -> ScanRow:
        now_sec = now_ms // 1000
        state.flow.advance(now_sec)
        buy60, sell60 = state.flow.totals(60)
        buy300, sell300 = state.flow.totals(300)
        qv60 = buy60 + sell60
        latest = state.trail.latest
        price = latest[1] if latest else state.ticker_last

        # 60 sn'lik akış verisi dolmadan hacim karşılaştırılmaz (eksik pencere düşük görünür).
        ready = (
            len(state.vol_stats) >= self._cfg.min_baseline_minutes
            and state.flow.coverage(now_sec) >= 60
        )
        volume_z = state.vol_stats.zscore(math.log1p(qv60), min_std=0.05) if ready else None
        vol_1m = (
            state.ret_stats.std if len(state.ret_stats) >= self._cfg.min_baseline_minutes else None
        )
        price_60 = state.trail.price_at(now_sec - 60)
        price_z = None
        if price and price_60 and vol_1m is not None:
            price_z = math.log(price / price_60) / max(vol_1m, 1e-5)

        spread_bps = book_imb = book_notional = None
        if state.book is not None:
            mid = (state.book.bid + state.book.ask) / 2
            spread_bps = (state.book.ask - state.book.bid) / mid * 10_000 if mid > 0 else None
            book_imb = state.book.imbalance
            book_notional = state.book.notional

        return ScanRow(
            market=state.market.value,
            symbol=state.symbol,
            last_price=price,
            change_1m_pct=pct_change(price, price_60) if price else None,
            change_5m_pct=pct_change(price, state.trail.price_at(now_sec - 300)) if price else None,
            change_15m_pct=pct_change(price, state.trail.price_at(now_sec - 900))
            if price
            else None,
            change_24h_pct=state.change_24h,
            quote_volume_24h=state.quote_volume_24h,
            quote_volume_60s=qv60,
            volume_z_60s=volume_z,
            price_z_60s=price_z,
            volatility_1m_pct=vol_1m * 100 if vol_1m is not None else None,
            imbalance_60s=imbalance(buy60, sell60),
            imbalance_300s=imbalance(buy300, sell300),
            buy_quote_300s=buy300,
            sell_quote_300s=sell300,
            spread_bps=spread_bps,
            book_imbalance_10=book_imb,
            book_notional_10=book_notional,
            baseline_minutes=len(state.vol_stats),
            listed_at_ms=state.listed_at_ms,
            signals=[
                k.value
                for k, at in state.last_signal.items()
                if time.monotonic() - at < self._cfg.signal_cooldown_s
            ],
            updated_ms=now_ms,
        )

    async def _evaluate(self, state: SymbolState, row: ScanRow) -> None:
        cfg = self._cfg
        if (
            row.volume_z_60s is not None
            and row.volume_z_60s >= cfg.volume_z_threshold
            and row.quote_volume_60s >= cfg.volume_min_quote
        ):
            critical = row.volume_z_60s >= cfg.volume_z_threshold * 2
            await self._emit(
                state,
                SignalKind.VOLUME_SPIKE,
                Severity.CRITICAL if critical else Severity.WARNING,
                value=row.volume_z_60s,
                threshold=cfg.volume_z_threshold,
                message=(
                    f"{row.symbol}: son 60 sn hacim {row.quote_volume_60s:,.0f} "
                    f"({row.volume_z_60s:.1f} standart sapma üstünde)"
                ),
                details={"quote_volume_60s": row.quote_volume_60s},
            )
        if (
            row.price_z_60s is not None
            and row.change_1m_pct is not None
            and abs(row.price_z_60s) >= cfg.price_z_threshold
            and abs(row.change_1m_pct) >= cfg.price_min_move_pct
        ):
            direction = "yükseliş" if row.change_1m_pct > 0 else "düşüş"
            await self._emit(
                state,
                SignalKind.PRICE_MOVE,
                Severity.WARNING,
                value=row.price_z_60s,
                threshold=cfg.price_z_threshold,
                message=f"{row.symbol}: 60 sn'de ani {direction} %{row.change_1m_pct:+.2f}",
                details={"change_1m_pct": row.change_1m_pct},
            )
        flow = row.buy_quote_300s + row.sell_quote_300s
        full_window = state.flow.coverage(row.updated_ms // 1000) >= 300
        if (
            full_window
            and row.imbalance_300s is not None
            and abs(row.imbalance_300s) >= cfg.imbalance_threshold
            and flow >= cfg.imbalance_min_quote
        ):
            side = "alım" if row.imbalance_300s > 0 else "satım"
            await self._emit(
                state,
                SignalKind.FLOW_IMBALANCE,
                Severity.INFO,
                value=row.imbalance_300s,
                threshold=cfg.imbalance_threshold,
                message=(
                    f"{row.symbol}: son 5 dk agresif {side} baskısı ({row.imbalance_300s:+.2f})"
                ),
                details={
                    "buy_quote_300s": row.buy_quote_300s,
                    "sell_quote_300s": row.sell_quote_300s,
                },
            )
        book = state.book
        if book is not None:
            if book.baseline is None:
                book.baseline = book.notional
            elif book.samples >= 60:  # temel çizgi en az ~1 dk otursun
                limit = book.baseline * (1 - cfg.liquidity_drop_pct / 100)
                book.low_streak = book.low_streak + 1 if book.notional < limit else 0
                # Anlık titreşim değil, en az 10 sn süren çekilme sinyal sayılır.
                if book.low_streak >= 10:
                    drop = (1 - book.notional / book.baseline) * 100
                    await self._emit(
                        state,
                        SignalKind.LIQUIDITY_DROP,
                        Severity.WARNING,
                        value=drop,
                        threshold=cfg.liquidity_drop_pct,
                        message=f"{row.symbol}: ilk 10 kademe derinlik %{drop:.0f} azaldı",
                        details={"notional_10": book.notional, "baseline": book.baseline},
                    )
            # Yaklaşık 5 dakikalık üstel hareketli ortalama (saniyelik turda güncellenir).
            book.baseline += (book.notional - book.baseline) / 300
            book.samples += 1

    async def _emit(
        self,
        state: SymbolState,
        kind: SignalKind,
        severity: Severity,
        *,
        value: float,
        threshold: float,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        now = time.monotonic()
        last = state.last_signal.get(kind)
        if last is not None and now - last < self._cfg.signal_cooldown_s:
            return
        state.last_signal[kind] = now
        signal = MarketSignal(
            market=state.market,
            symbol=state.symbol,
            kind=kind,
            severity=severity,
            value=round(value, 4),
            threshold=threshold,
            message=message,
            details=details or {},
        )
        self.signals.append(signal)
        await self._bus.publish(signal)
        if self._db is not None:
            try:
                await self._db.execute(
                    "INSERT INTO market_signals (ts, market, symbol, kind, severity, value, "
                    "threshold, message, details) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        signal.ts_ms,
                        signal.market.value,
                        signal.symbol,
                        signal.kind.value,
                        signal.severity.value,
                        signal.value,
                        signal.threshold,
                        signal.message,
                        json.dumps(signal.details, ensure_ascii=False),
                    ),
                )
            except Exception:
                logger.exception("Sinyal kaydedilemedi")

    async def tick(self, now_ms: int | None = None) -> None:
        now_ms = self._clock.now_ms() if now_ms is None else now_ms
        started = time.perf_counter()
        for key, state in list(self._states.items()):
            row = self._row(state, now_ms)
            self.rows[key] = row
            await self._evaluate(state, row)
        self.ticks += 1
        self.tick_ms_last = (time.perf_counter() - started) * 1000
        self.tick_ms_max = max(self.tick_ms_max, self.tick_ms_last)

    # --- Isınma (REST'ten geçmiş mumlar) -------------------------------------------------------

    def load_history(
        self, market: Market, symbol: str, rows: Iterable[list[Any]], now_ms: int
    ) -> int:
        """Binance kline REST satırlarını (yalnızca kapanmış mumlar) temel çizgiye ekler."""
        state = self.state(market, symbol)
        loaded = 0
        for row in rows:
            open_ms, close_ms = int(row[0]), int(row[6])
            if close_ms >= now_ms:
                continue  # henüz kapanmamış mum
            state.add_closed_candle(open_ms, float(row[4]), float(row[7]))
            loaded += 1
        return loaded

    async def warmup(self, service: MarketDataService, *, concurrency: int = 4) -> int:
        symbols = service.tracked_symbols()
        endpoints = service.endpoints
        limit = self._cfg.baseline_minutes + 1
        sem = asyncio.Semaphore(concurrency)
        done = 0

        async def one(symbol: str) -> None:
            nonlocal done
            async with sem:
                try:
                    rows = await service.rest.get(
                        endpoints.klines_path,
                        params={"symbol": symbol, "interval": "1m", "limit": limit},
                        weight=endpoints.klines_weight(limit),
                        priority=Priority.LOW,
                    )
                except Exception as exc:
                    logger.warning(
                        "Mum geçmişi alınamadı", extra={"symbol": symbol, "error": repr(exc)}
                    )
                    return
                self.load_history(service.market, symbol, rows, self._clock.now_ms())
                done += 1
                self.warmup_done[service.market.value] = done

        await asyncio.gather(*(one(s) for s in symbols))
        return done

    async def run(self, services: Iterable[MarketDataService] = ()) -> None:
        tasks: list[asyncio.Task[Any]] = []
        if self._cfg.warmup:
            for service in services:
                tasks.append(asyncio.create_task(self._warmup_when_ready(service)))
        try:
            while True:
                await self.tick()
                await asyncio.sleep(self._cfg.tick_interval_s)
        finally:
            for task in tasks:
                task.cancel()

    async def _warmup_when_ready(self, service: MarketDataService) -> None:
        await service.discovered.wait()
        loaded = await self.warmup(service)
        logger.info(
            "Tarayıcı ısınması tamamlandı",
            extra={"market": service.market.value, "symbols": loaded},
        )

    # --- Sorgular -------------------------------------------------------------------------

    def top(
        self,
        market: Market,
        *,
        sort: str = "volume_z_60s",
        limit: int = 50,
        min_quote_volume_24h: float = 0.0,
        symbols: set[str] | None = None,
    ) -> list[ScanRow]:
        rows = [
            r
            for (m, s), r in self.rows.items()
            if m is market
            and (symbols is None or s in symbols)
            and (r.quote_volume_24h or 0.0) >= min_quote_volume_24h
        ]

        def key(row: ScanRow) -> float:
            value = getattr(row, sort)
            if value is None:
                return float("-inf")
            number = float(value)
            return abs(number) if sort.startswith(("change_", "price_z", "imbalance")) else number

        rows.sort(key=key, reverse=True)
        return rows[:limit]

    def stats(self) -> dict[str, Any]:
        return {
            "symbols": len(self._states),
            "ticks": self.ticks,
            "tick_ms_last": round(self.tick_ms_last, 3),
            "tick_ms_max": round(self.tick_ms_max, 3),
            "signals": len(self.signals),
            "warmup_done": dict(self.warmup_done),
        }


def row_dict(row: ScanRow) -> dict[str, Any]:
    return asdict(row)
