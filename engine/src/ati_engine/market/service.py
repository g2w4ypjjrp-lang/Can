"""Piyasa verisi servisi: keşif + akışlar + emir defterleri + güncel piyasa durumu.

Her piyasa (Spot, USDⓈ-M Futures) için bir ``MarketDataService`` çalışır. Servis tek bir
denetlenen görevdir; iç görevlerinden biri çökerse tümü durur ve denetleyici servisi yeniden
başlatır. Servis sağlıklı olduğunda ``market_data.<piyasa>`` hazırlık koşulunu doğru yapar;
bağlantı koparsa koşul bozulur ve motor güvenli moda (SAFE_MODE) iner.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from ati_engine.config import EngineSettings
from ati_engine.core.bus import EventBus
from ati_engine.core.models import Market
from ati_engine.exchange.endpoints import MarketEndpoints, endpoints_for
from ati_engine.exchange.rate_limit import (
    Priority,
    WeightBudget,
    parse_rate_limits,
    request_weight_per_minute,
)
from ati_engine.exchange.rest import BinanceRestClient
from ati_engine.market.discovery import SymbolRegistry, parse_exchange_info
from ati_engine.market.events import (
    AggTrade,
    DepthDiff,
    MarkPrice,
    MarkPriceBatch,
    OrderBookResynced,
    OrderBookTop,
    StreamConnectionChanged,
    Ticker24h,
    TickerBatch,
)
from ati_engine.market.gapfill import TradeGapFiller
from ati_engine.market.orderbook import (
    BookSynchronizer,
    DepthSnapshot,
    ResyncRequired,
    SnapshotTooOld,
    SyncState,
)
from ati_engine.market.parsing import ParsedMessage, StreamKind
from ati_engine.market.streams import ConnectionAttemptLimiter, StreamConnection, StreamManager

logger = logging.getLogger(__name__)

ReadinessCallback = Callable[[bool, str], Awaitable[None]]

DEFAULT_WEIGHT_LIMIT = {Market.SPOT: 6000, Market.USDM_FUTURES: 2400}


# --- Güncel piyasa durumu ------------------------------------------------------------------


class MarketState:
    """Sembol başına son 24 saatlik özet ve (Futures) mark price / funding."""

    def __init__(self) -> None:
        self.tickers: dict[str, Ticker24h] = {}
        self.marks: dict[str, MarkPrice] = {}
        # Son işlem fiyatı (aggTrade akışı; her işlemde anında güncellenir).
        self.trades: dict[str, float] = {}
        self.counts: dict[str, int] = {}
        self.started = time.monotonic()

    def count(self, kind: StreamKind, n: int = 1) -> None:
        self.counts[kind.value] = self.counts.get(kind.value, 0) + n

    def top(self, limit: int, symbols: set[str] | None = None) -> list[Ticker24h]:
        items = (t for t in self.tickers.values() if symbols is None or t.symbol in symbols)
        return sorted(items, key=lambda t: t.quote_volume, reverse=True)[:limit]

    def rates(self) -> dict[str, float]:
        elapsed = max(time.monotonic() - self.started, 1e-6)
        return {k: round(v / elapsed, 2) for k, v in self.counts.items()}


# --- Emir defterleri -----------------------------------------------------------------------


@dataclass
class BookStatus:
    symbol: str
    state: str
    update_id: int
    best_bid: float | None
    best_ask: float | None
    imbalance_10: float | None
    resyncs: int
    applied: int


class OrderBookManager:
    def __init__(
        self,
        *,
        market: Market,
        endpoints: MarketEndpoints,
        rest: BinanceRestClient,
        bus: EventBus,
        snapshot_limit: int,
        publish_interval_s: float = 0.1,
        max_concurrent_snapshots: int = 2,
    ) -> None:
        self.market = market
        self._endpoints = endpoints
        self._rest = rest
        self._bus = bus
        self._limit = snapshot_limit if market is Market.SPOT else min(snapshot_limit, 1000)
        self._publish_interval = publish_interval_s
        self._sem = asyncio.Semaphore(max_concurrent_snapshots)
        self._books: dict[str, BookSynchronizer] = {}
        self._pending: set[str] = set()
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._last_publish: dict[str, float] = {}

    @property
    def symbols(self) -> list[str]:
        return sorted(self._books)

    def set_focus(self, symbols: Iterable[str]) -> list[str]:
        wanted = {s.upper() for s in symbols}
        for symbol in list(self._books):
            if symbol not in wanted:
                del self._books[symbol]
                self._pending.discard(symbol)
        for symbol in wanted:
            self._books.setdefault(symbol, BookSynchronizer(market=self.market, symbol=symbol))
        return [f"{s.lower()}@depth@100ms" for s in sorted(wanted)]

    def get(self, symbol: str) -> BookSynchronizer | None:
        return self._books.get(symbol)

    def _request_snapshot(self, symbol: str) -> None:
        if symbol not in self._pending:
            self._pending.add(symbol)
            self._queue.put_nowait(symbol)

    async def on_diff(self, diff: DepthDiff) -> None:
        sync = self._books.get(diff.symbol)
        if sync is None:
            return
        try:
            updated = sync.on_diff(diff)
        except ResyncRequired as exc:
            await self._bus.publish(
                OrderBookResynced(market=self.market, symbol=diff.symbol, reason=exc.reason)
            )
            sync.on_diff(diff)  # yeni tamponun ilk olayı
            self._request_snapshot(diff.symbol)
            return
        if sync.state is SyncState.BUFFERING:
            self._request_snapshot(diff.symbol)
        elif updated:
            await self._maybe_publish(sync, diff.event_time_ms)

    async def _maybe_publish(self, sync: BookSynchronizer, event_time_ms: int) -> None:
        now = time.monotonic()
        if now - self._last_publish.get(sync.symbol, 0.0) < self._publish_interval:
            return
        self._last_publish[sync.symbol] = now
        book = sync.book
        bb, ba = book.best_bid(), book.best_ask()
        if bb is None or ba is None:
            return
        bids, asks = book.top_bids(10), book.top_asks(10)
        await self._bus.publish(
            OrderBookTop(
                market=self.market,
                event_time_ms=event_time_ms,
                symbol=sync.symbol,
                update_id=book.update_id,
                best_bid=bb[0],
                best_ask=ba[0],
                bid_notional_10=book.notional(bids),
                ask_notional_10=book.notional(asks),
                imbalance_10=book.imbalance(10),
            )
        )

    async def _fetch(self, symbol: str) -> DepthSnapshot:
        payload = await self._rest.get(
            self._endpoints.depth_path,
            params={"symbol": symbol, "limit": self._limit},
            weight=self._endpoints.depth_weight(self._limit),
            priority=Priority.NORMAL,
        )
        return DepthSnapshot.from_rest(payload)

    async def _sync_one(self, symbol: str) -> None:
        # Anlık görüntüden önce akıştan en az bir olayın tamponlanmasını bekle.
        for _ in range(50):
            sync = self._books.get(symbol)
            if sync is None:
                return
            if sync.buffer:
                break
            await asyncio.sleep(0.1)
        async with self._sem:
            for attempt in range(5):
                sync = self._books.get(symbol)
                if sync is None or sync.state is SyncState.SYNCED:
                    return
                snapshot = await self._fetch(symbol)
                try:
                    sync.on_snapshot(snapshot)
                    return
                except SnapshotTooOld:
                    await asyncio.sleep(0.25 * (attempt + 1))
                except ResyncRequired as exc:
                    await self._bus.publish(
                        OrderBookResynced(market=self.market, symbol=symbol, reason=exc.reason)
                    )
                    await asyncio.sleep(0.25 * (attempt + 1))

    async def run(self) -> None:
        async def worker() -> None:
            while True:
                symbol = await self._queue.get()
                try:
                    await self._sync_one(symbol)
                except Exception:
                    logger.exception(
                        "Emir defteri anlık görüntüsü alınamadı", extra={"symbol": symbol}
                    )
                    await asyncio.sleep(2)
                finally:
                    self._pending.discard(symbol)
                    sync = self._books.get(symbol)
                    if sync is not None and sync.state is SyncState.BUFFERING and sync.buffer:
                        self._request_snapshot(symbol)

        async with asyncio.TaskGroup() as group:
            for i in range(2):
                group.create_task(worker(), name=f"orderbook-{self.market.value}-{i}")

    def status(self) -> list[BookStatus]:
        result = []
        for symbol, sync in sorted(self._books.items()):
            bb, ba = sync.book.best_bid(), sync.book.best_ask()
            synced = sync.state is SyncState.SYNCED
            result.append(
                BookStatus(
                    symbol=symbol,
                    state=sync.state.value,
                    update_id=sync.book.update_id,
                    best_bid=bb[0] if bb and synced else None,
                    best_ask=ba[0] if ba and synced else None,
                    imbalance_10=round(sync.book.imbalance(10), 4) if synced else None,
                    resyncs=sync.resyncs,
                    applied=sync.applied,
                )
            )
        return result


# --- Servis -------------------------------------------------------------------------------


def tier0_streams(market: Market) -> list[str]:
    if market is Market.SPOT:
        return ["!miniTicker@arr"]
    return ["!ticker@arr", "!markPrice@arr@1s", "!forceOrder@arr"]


class MarketDataService:
    def __init__(
        self,
        *,
        market: Market,
        settings: EngineSettings,
        registry: SymbolRegistry,
        bus: EventBus,
        on_ready: ReadinessCallback,
        attempt_limiter: ConnectionAttemptLimiter | None = None,
        rest: BinanceRestClient | None = None,
    ) -> None:
        self.market = market
        self.condition = f"market_data.{market.value}"
        self._settings = settings
        self._cfg = settings.market_data
        self._registry = registry
        self._bus = bus
        self._on_ready = on_ready
        self.endpoints = endpoints_for(market, settings.binance)
        self.rest = rest or BinanceRestClient(
            self.endpoints.rest_base, budget=WeightBudget(DEFAULT_WEIGHT_LIMIT[market])
        )
        self.state = MarketState()
        self.books = OrderBookManager(
            market=market,
            endpoints=self.endpoints,
            rest=self.rest,
            bus=bus,
            snapshot_limit=self._cfg.depth_snapshot_limit,
        )
        self.streams = StreamManager(
            market=market,
            endpoints=self.endpoints,
            on_parsed=self._on_parsed,
            on_health=self._on_stream_health,
            on_connection_state=self._on_connection_state,
            streams_per_connection=self._cfg.streams_per_connection,
            stale_after_s=self._cfg.stale_after_s,
            attempt_limiter=attempt_limiter,
        )
        self.gaps = TradeGapFiller(
            market=market, endpoints=self.endpoints, rest=self.rest, publish=bus.publish
        )
        self._discovered = False
        self.discovered = asyncio.Event()  # ilk keşif tamamlandığında kurulur
        self._focus: list[str] = list(self._cfg.focus_symbols)
        # Açık pozisyonların anlık fiyat yayını (LivePrices.note); her işlem fiyatında çağrılır.
        self.on_trade_price: Callable[[Market, str, float], None] | None = None
        self.last_discovery_error: str | None = None
        self._ready: bool | None = None
        self._ready_detail: str | None = None
        # Coin listesi canlı akışı beklemeden REST'ten doldurulur; akış sustuğunda da yenilenir.
        self.tickers_ready = asyncio.Event()
        self._ws_ticker_at = -1e18
        self.ticker_snapshots = 0
        self.last_ticker_error: str | None = None

    # --- Akış seçimi -------------------------------------------------------------------

    def desired_streams(self) -> list[str]:
        streams = list(tier0_streams(self.market))
        for info in self._registry.tracked(self.market):
            name = info.symbol.lower()
            streams.extend(f"{name}@kline_{interval}" for interval in self._cfg.kline_intervals)
            if self._cfg.include_agg_trades:
                streams.append(f"{name}@aggTrade")
        tracked = {s.symbol for s in self._registry.tracked(self.market)}
        focus = [s for s in self._focus if s in tracked]
        streams.extend(self.books.set_focus(focus))
        return streams

    def set_focus(self, symbols: Iterable[str]) -> list[str]:
        tracked = {s.symbol for s in self._registry.tracked(self.market)}
        self._focus = [s.upper() for s in symbols if s.upper() in tracked]
        self.streams.set_streams(self.desired_streams())
        return self._focus

    @property
    def focus(self) -> list[str]:
        return list(self._focus)

    def tracked_symbols(self) -> list[str]:
        return [s.symbol for s in self._registry.tracked(self.market)]

    def tickers(self, limit: int, *, focus_only: bool = False) -> list[Ticker24h]:
        """İzlenen evrendeki semboller, 24 saatlik işlem hacmine göre azalan."""
        if focus_only:
            symbols = set(self._focus)
        else:
            symbols = {s.symbol for s in self._registry.tracked(self.market)}
        return self.state.top(limit, symbols)

    # --- Olay işleme -------------------------------------------------------------------

    async def _on_parsed(self, parsed: ParsedMessage) -> None:
        self.state.count(parsed.kind)
        for event in parsed.events:
            if isinstance(event, DepthDiff):
                await self.books.on_diff(event)
                continue
            if isinstance(event, AggTrade):
                if not self.gaps.accept(event):
                    continue  # bağlantı yenilemesindeki tekrar
                if not event.recovered and event.price > 0:
                    self.state.trades[event.symbol] = event.price
                    if self.on_trade_price is not None:
                        self.on_trade_price(self.market, event.symbol, event.price)
            elif isinstance(event, TickerBatch):
                for ticker in event.tickers:
                    self.state.tickers[ticker.symbol] = ticker
                self._ws_ticker_at = asyncio.get_running_loop().time()
                self.tickers_ready.set()
            elif isinstance(event, MarkPriceBatch):
                for mark in event.items:
                    self.state.marks[mark.symbol] = mark
            await self._bus.publish(event)

    async def _on_connection_state(
        self, conn: StreamConnection, connected: bool, reason: str
    ) -> None:
        await self._bus.publish(
            StreamConnectionChanged(
                market=self.market,
                connection=conn.name,
                connected=connected,
                streams=len(conn.desired),
                reason=reason,
            )
        )

    async def _on_stream_health(self, healthy: bool, detail: str) -> None:
        await self._update_ready()

    async def _update_ready(self) -> None:
        ready = self._discovered and self.streams.healthy()
        if not self._discovered:
            detail = self.last_discovery_error or "semboller keşfediliyor"
        else:
            detail = self.streams.health_detail()
        # Durum aynı kalsa bile neden değişirse bildirilir (ör. "keşfediliyor" → "keşif
        # başarısız"); aksi halde arayüz yanlış nedeni gösterir.
        if ready != self._ready or detail != self._ready_detail:
            self._ready = ready
            self._ready_detail = detail
            await self._on_ready(ready, detail)

    # --- Keşif -------------------------------------------------------------------------

    async def discover(self) -> None:
        payload = await self.rest.get(
            self.endpoints.exchange_info_path,
            weight=self.endpoints.exchange_info_weight,
            priority=Priority.NORMAL,
        )
        limit = request_weight_per_minute(parse_rate_limits(payload.get("rateLimits", [])))
        if limit:
            self.rest.budget.set_limit(limit)
        symbols = parse_exchange_info(self.market, payload)
        diff = await self._registry.apply(self.market, symbols)
        # Bu süreçteki ilk keşifte akışlar her zaman kurulur. Semboller veritabanında önceki
        # çalıştırmadan kalmışsa fark "boş" görünür; yalnızca farka bakmak akışları hiç
        # başlatmıyordu (motor yeniden açıldığında "akış yok" ve güvenli mod).
        first = not self._discovered
        self._discovered = True
        self.discovered.set()
        self.last_discovery_error = None
        if first or diff.changed or diff.initial:
            self.streams.set_streams(self.desired_streams())
        logger.info(
            "Sembol keşfi tamamlandı",
            extra={
                "market": self.market.value,
                "tracked": len(self._registry.tracked(self.market)),
                "listed": [s.symbol for s in diff.listed] if not diff.initial else len(diff.listed),
                "delisted": [s.symbol for s in diff.delisted],
            },
        )

    async def refresh_tickers(self) -> int:
        """24 saatlik özetleri tek REST isteğiyle alır (açılışta ve canlı akış sustuğunda).

        Akıştan gelen daha yeni değerin üzerine yazılmaz; yalnızca izlenen semboller alınır."""
        rows = await self.rest.get(
            self.endpoints.ticker_24h_path,
            weight=self.endpoints.ticker_24h_weight,
            priority=Priority.NORMAL,
        )
        tracked = {s.symbol for s in self._registry.tracked(self.market)}
        updated = 0
        for row in rows or []:
            symbol = row.get("symbol") if isinstance(row, dict) else None
            if symbol not in tracked:
                continue
            try:
                ticker = Ticker24h(
                    symbol=symbol,
                    last=float(row["lastPrice"]),
                    open=float(row["openPrice"]),
                    high=float(row["highPrice"]),
                    low=float(row["lowPrice"]),
                    base_volume=float(row["volume"]),
                    quote_volume=float(row["quoteVolume"]),
                    event_time_ms=int(row.get("closeTime") or 0),
                )
            except (KeyError, TypeError, ValueError):
                continue
            current = self.state.tickers.get(symbol)
            if current is None or current.event_time_ms < ticker.event_time_ms:
                self.state.tickers[symbol] = ticker
                updated += 1
        self.ticker_snapshots += 1
        self.last_ticker_error = None
        if self.state.tickers:
            self.tickers_ready.set()
        return updated

    async def _ticker_snapshot_loop(self, *, every_s: float = 60.0, silent_s: float = 45.0) -> None:
        await self.discovered.wait()
        loop = asyncio.get_running_loop()
        while True:
            if loop.time() - self._ws_ticker_at > silent_s:
                try:
                    await self.refresh_tickers()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.last_ticker_error = f"{type(exc).__name__}: {exc}"[:300]
                    logger.warning(
                        "24 saatlik özetler REST'ten alınamadı",
                        extra={"market": self.market.value, "error": repr(exc)},
                    )
            await asyncio.sleep(every_s)

    def warmup_order(self) -> list[str]:
        """Isınma sırası: odak sembolleri, sonra 24 saatlik hacme göre azalan; böylece büyük
        coinler ilk saniyelerde puanlanır."""
        symbols = self.tracked_symbols()
        focus = [s for s in self._focus if s in set(symbols)]
        volume = {s: t.quote_volume for s, t in self.state.tickers.items()}
        rest = sorted(
            (s for s in symbols if s not in focus), key=lambda s: volume.get(s, 0.0), reverse=True
        )
        return focus + rest

    async def _discovery_loop(self) -> None:
        backoff = 2.0
        while True:
            try:
                await self.discover()
                backoff = 2.0
                await self._update_ready()
                await asyncio.sleep(self._cfg.discovery_interval_s)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_discovery_error = f"keşif başarısız: {type(exc).__name__}: {exc}"[:300]
                logger.warning(
                    "Sembol keşfi başarısız",
                    extra={"market": self.market.value, "error": repr(exc)},
                )
                await self._update_ready()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 120.0)

    async def run(self) -> None:
        self._ready = None
        self._ready_detail = None
        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(self._discovery_loop(), name=f"discovery-{self.market.value}")
                group.create_task(self.streams.run(), name=f"streams-{self.market.value}")
                group.create_task(self.books.run(), name=f"books-{self.market.value}")
                group.create_task(self.gaps.run(), name=f"gapfill-{self.market.value}")
                group.create_task(
                    self._ticker_snapshot_loop(), name=f"ticker-snapshot-{self.market.value}"
                )
        finally:
            with contextlib.suppress(Exception):
                await self._on_ready(False, "piyasa verisi servisi durdu")

    async def close(self) -> None:
        await self.rest.close()

    def status(self) -> dict[str, Any]:
        tracked = self._registry.tracked(self.market)
        return {
            "market": self.market.value,
            "ready": bool(self._ready),
            "tracked_symbols": len(tracked),
            "streams": self.streams.stream_count,
            "connections": [vars(c) for c in self.streams.status()],
            "message_rates_per_s": self.state.rates(),
            "order_books": [vars(b) for b in self.books.status()],
            "trade_gaps": vars(self.gaps.stats).copy(),
            "focus": self.focus,
            "rest_budget": self.rest.budget.snapshot(),
            "last_discovery_error": self.last_discovery_error,
            "tickers": len(self.state.tickers),
            "ticker_snapshots": self.ticker_snapshots,
            "last_ticker_error": self.last_ticker_error,
        }
