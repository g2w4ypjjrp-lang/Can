"""Balina radarı servisi: tüm balina modüllerini birleştirir.

Akış:
* ``AggTrade`` → süpürme birleştirme → sembol eşiği → ``WhaleTrade`` + kayıt + kümelenme
  + etki takibi; çok büyük emirde ``WhaleAlert(MEGA_TRADE)``.
* ``Liquidation`` → büyük tasfiye kaydı + zincir tespiti → ``WhaleAlert(LIQUIDATION_CASCADE)``.
* Saniyelik tur → odak defterlerinde duvar taraması, bekleyen süpürmelerin tamamlanması,
  etki ölçümlerinin tamamlanması, veritabanına toplu yazma.
* 5 dakikada bir → büyük oyuncu pozisyonlanması (Futures).
* (Açıksa) zincir üstü büyük transferler.

Uyarılar sembol ve tür başına bekleme süresiyle sınırlanır ve masaüstü/iOS'a bildirilir.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from ati_engine.config import WhaleSettings
from ati_engine.core.bus import EventBus
from ati_engine.core.clock import Clock, SystemClock
from ati_engine.core.models import Market, Severity
from ati_engine.market.events import AggTrade, Liquidation
from ati_engine.market.orderbook import SyncState
from ati_engine.whales.clusters import ClusterDetector
from ati_engine.whales.events import WhaleAlert, WhaleAlertKind, WhaleTrade
from ati_engine.whales.impact import ImpactTracker
from ati_engine.whales.large_trades import SweepAggregator, TakerOrder, WhaleThresholds
from ati_engine.whales.liquidations import LiquidationMonitor, liquidation_notional
from ati_engine.whales.onchain import FlowType, OnchainTransfer, OnchainWatcher
from ati_engine.whales.positioning import PositioningSnapshot, fetch_snapshot
from ati_engine.whales.walls import WallChange, WallTracker

if TYPE_CHECKING:
    from ati_engine.market.service import MarketDataService
    from ati_engine.storage.database import Database

logger = logging.getLogger(__name__)

_WHALE_EVENT_SQL = (
    "INSERT INTO whale_events (ts, source, market, symbol, side, notional_usd, details) "
    "VALUES (?, ?, ?, ?, ?, ?, ?)"
)
_IMPACT_SQL = (
    "INSERT INTO whale_impacts (event_ts, market, symbol, kind, direction, horizon_s, "
    "return_pct, directional_pct) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)


class WhaleRadar:
    def __init__(
        self,
        *,
        settings: WhaleSettings,
        bus: EventBus,
        db: Database | None = None,
        clock: Clock | None = None,
        onchain: OnchainWatcher | None = None,
    ) -> None:
        self._cfg = settings
        self._bus = bus
        self._db = db
        self._clock = clock or SystemClock()
        self._onchain = onchain
        self._sweeps = {m: SweepAggregator() for m in Market}
        self._thresholds = {
            Market.SPOT: WhaleThresholds(
                floor_usd=settings.spot_floor_usd,
                quantile=settings.quantile,
                min_samples=settings.min_samples,
            ),
            Market.USDM_FUTURES: WhaleThresholds(
                floor_usd=settings.futures_floor_usd,
                quantile=settings.quantile,
                min_samples=settings.min_samples,
            ),
        }
        self.clusters = ClusterDetector(
            window_s=settings.cluster_window_s,
            min_count=settings.cluster_min_count,
            min_notional=settings.cluster_min_usd,
        )
        self._walls = {
            Market.SPOT: self._wall_tracker(settings.spot_wall_min_usd),
            Market.USDM_FUTURES: self._wall_tracker(settings.futures_wall_min_usd),
        }
        self.liquidations = LiquidationMonitor(
            min_notional=settings.liquidation_min_usd,
            window_s=settings.cascade_window_s,
            cascade_min_notional=settings.cascade_min_usd,
            cascade_min_count=settings.cascade_min_count,
        )
        self.impact = ImpactTracker()
        self._prices: dict[tuple[Market, str], float] = {}
        self.trades: deque[WhaleTrade] = deque(maxlen=5_000)
        self.alerts: deque[WhaleAlert] = deque(maxlen=1_000)
        self.wall_changes: deque[WallChange] = deque(maxlen=1_000)
        self.onchain_transfers: deque[OnchainTransfer] = deque(maxlen=1_000)
        self.positioning: dict[str, PositioningSnapshot] = {}
        self._last_alert: dict[tuple[Market | None, str, WhaleAlertKind], float] = {}
        self._event_rows: list[tuple[Any, ...]] = []
        self._impact_rows: list[tuple[Any, ...]] = []
        self.orders_seen = 0
        self.ticks = 0
        self.tick_ms_max = 0.0
        self._attached = False

    def _wall_tracker(self, min_usd: float) -> WallTracker:
        cfg = self._cfg
        return WallTracker(
            levels=cfg.wall_levels,
            multiple=cfg.wall_multiple,
            min_notional=min_usd,
            max_distance_pct=cfg.wall_max_distance_pct,
            min_lifetime_s=cfg.wall_min_lifetime_s,
        )

    # --- Olaylar ---------------------------------------------------------------------------

    def attach(self) -> None:
        if self._attached:
            return
        self._attached = True
        self._bus.subscribe(AggTrade, self.on_trade, name="whales-trades", maxsize=200_000)
        self._bus.subscribe(
            Liquidation, self.on_liquidation, name="whales-liquidations", maxsize=10_000
        )

    def threshold(self, market: Market, symbol: str) -> float:
        return self._thresholds[market].threshold(symbol)

    def price(self, market: Market, symbol: str) -> float | None:
        return self._prices.get((market, symbol))

    async def on_trade(self, event: AggTrade) -> None:
        if not event.recovered:
            self._prices[(event.market, event.symbol)] = event.price
        completed = self._sweeps[event.market].add(
            event.symbol,
            event.trade_time_ms,
            event.price,
            event.qty,
            taker_buy=not event.buyer_is_maker,
        )
        if completed is not None:
            await self._handle_order(event.market, completed)

    async def _handle_order(self, market: Market, order: TakerOrder) -> None:
        self.orders_seen += 1
        thresholds = self._thresholds[market]
        threshold = thresholds.threshold(order.symbol)
        thresholds.observe(order.symbol, order.notional)
        if order.notional < threshold:
            return
        trade = WhaleTrade(
            market=market,
            event_time_ms=order.time_ms,
            symbol=order.symbol,
            side=order.side,
            notional=order.notional,
            avg_price=order.avg_price,
            qty=order.qty,
            fills=order.fills,
            sweep_pct=round(order.price_impact_pct, 4),
            threshold=threshold,
        )
        self.trades.append(trade)
        await self._bus.publish(trade)
        self._event_rows.append(
            (
                order.time_ms,
                "binance_trade",
                market.value,
                order.symbol,
                order.side,
                f"{order.notional:.2f}",
                json.dumps(
                    {
                        "avg_price": order.avg_price,
                        "qty": order.qty,
                        "fills": order.fills,
                        "threshold": round(threshold, 2),
                        "sweep_pct": trade.sweep_pct,
                    },
                ),
            )
        )
        direction = 1 if order.taker_buy else -1
        self.impact.register(
            "whale_trade", direction, market, order.symbol, order.time_ms, order.last_price
        )
        cfg = self._cfg
        if order.notional >= max(cfg.mega_multiple * threshold, cfg.mega_min_usd):
            verb = "alış" if order.taker_buy else "satış"
            await self._alert(
                WhaleAlertKind.MEGA_TRADE,
                market,
                order.symbol,
                Severity.WARNING,
                side=order.side,
                notional=order.notional,
                message=(
                    f"{order.symbol}: {order.notional:,.0f} tutarında tek agresif {verb} emri "
                    f"({order.fills} kademe, eşik {threshold:,.0f})"
                ),
                details={"avg_price": order.avg_price, "sweep_pct": trade.sweep_pct},
            )
        cluster = self.clusters.add(market, order.symbol, order.time_ms, order.side, order.notional)
        if cluster is not None:
            kind = WhaleAlertKind.ACCUMULATION if order.taker_buy else WhaleAlertKind.DISTRIBUTION
            label = (
                "birikim (art arda büyük alış)"
                if order.taker_buy
                else "dağıtım (art arda büyük satış)"
            )
            cross = " · Spot ve Futures birlikte" if cluster.cross_market else ""
            await self._alert(
                kind,
                market,
                order.symbol,
                Severity.WARNING if cluster.cross_market else Severity.INFO,
                side=order.side,
                notional=cluster.notional,
                message=(
                    f"{order.symbol}: {cluster.window_s // 60} dk içinde "
                    f"{cluster.count} balina emri, "
                    f"{label}, toplam {cluster.notional:,.0f}{cross}"
                ),
                details=asdict(cluster) | {"market": market.value},
            )
            self.impact.register(
                kind.value, direction, market, order.symbol, order.time_ms, order.last_price
            )

    async def on_liquidation(self, event: Liquidation) -> None:
        notional = liquidation_notional(event)
        cascade = self.liquidations.add(event)
        if notional >= self.liquidations.min_notional:
            self._event_rows.append(
                (
                    event.trade_time_ms,
                    "binance_liquidation",
                    event.market.value,
                    event.symbol,
                    event.side.lower(),
                    f"{notional:.2f}",
                    json.dumps(
                        {
                            "liquidated": "long" if event.side == "SELL" else "short",
                            "avg_price": event.avg_price,
                            "qty": event.filled_qty,
                        },
                    ),
                )
            )
        if cascade is not None:
            direction = -1 if cascade.liquidated == "long" else 1
            pressure = "satış" if cascade.liquidated == "long" else "alış"
            await self._alert(
                WhaleAlertKind.LIQUIDATION_CASCADE,
                event.market,
                event.symbol,
                Severity.WARNING,
                side=cascade.liquidated,
                notional=cascade.notional,
                message=(
                    f"{event.symbol}: {cascade.window_s} sn içinde "
                    f"{cascade.count} {cascade.liquidated} "
                    f"tasfiyesi, en az {cascade.notional:,.0f} ({pressure} baskısı)"
                ),
                details=asdict(cascade),
            )
            price = self.price(event.market, event.symbol) or event.avg_price
            self.impact.register(
                "liquidation_cascade",
                direction,
                event.market,
                event.symbol,
                event.trade_time_ms,
                price,
            )

    # --- Uyarılar ---------------------------------------------------------------------------

    async def _alert(
        self,
        kind: WhaleAlertKind,
        market: Market | None,
        symbol: str,
        severity: Severity,
        *,
        side: str,
        notional: float,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        key = (market, symbol, kind)
        now = time.monotonic()
        last = self._last_alert.get(key)
        if last is not None and now - last < self._cfg.alert_cooldown_s:
            return
        self._last_alert[key] = now
        alert = WhaleAlert(
            market=market,
            symbol=symbol,
            kind=kind,
            severity=severity,
            side=side,
            notional=round(notional, 2),
            message=message,
            details=details or {},
        )
        self.alerts.append(alert)
        await self._bus.publish(alert)
        if self._db is not None:
            try:
                await self._db.execute(
                    "INSERT INTO whale_alerts (ts, market, symbol, kind, severity, side, notional, "
                    "message, details) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        alert.ts_ms,
                        market.value if market else None,
                        symbol,
                        kind.value,
                        severity.value,
                        side,
                        alert.notional,
                        message,
                        json.dumps(alert.details, ensure_ascii=False, default=str),
                    ),
                )
            except Exception:
                logger.exception("Balina uyarısı kaydedilemedi")

    # --- Duvarlar ----------------------------------------------------------------------------

    async def scan_walls(self, services: Iterable[MarketDataService], now_ms: int) -> None:
        for service in services:
            tracker = self._walls[service.market]
            for symbol in service.books.symbols:
                sync = service.books.get(symbol)
                if sync is None or sync.state is not SyncState.SYNCED:
                    continue
                for change in tracker.scan(service.market, symbol, sync.book, now_ms):
                    await self._on_wall(change, now_ms)

    async def _on_wall(self, change: WallChange, now_ms: int) -> None:
        self.wall_changes.append(change)
        side = "buy" if change.side == "bid" else "sell"
        self._event_rows.append(
            (
                now_ms,
                "binance_orderbook",
                change.market.value,
                change.symbol,
                side,
                f"{change.notional:.2f}",
                json.dumps(
                    {
                        "event": change.kind,
                        "price": change.price,
                        "lifetime_s": change.lifetime_s,
                        "distance_pct": round(change.distance_pct, 4),
                    },
                ),
            )
        )
        if change.kind == "appeared":
            return
        wall = "alış" if change.side == "bid" else "satış"
        if change.kind == "pulled":
            kind, verb = WhaleAlertKind.WALL_PULLED, "fiyat ulaşmadan çekildi"
        else:
            kind, verb = WhaleAlertKind.WALL_EATEN, "işlemle eritildi"
        await self._alert(
            kind,
            change.market,
            change.symbol,
            Severity.INFO,
            side=side,
            notional=change.notional,
            message=(
                f"{change.symbol}: {change.price:g} seviyesindeki "
                f"{change.notional:,.0f} tutarındaki "
                f"{wall} duvarı {verb} ({change.lifetime_s:.0f} sn yaşadı)"
            ),
            details=asdict(change) | {"market": change.market.value},
        )

    # --- Saniyelik tur -------------------------------------------------------------------------

    async def tick(
        self, services: Iterable[MarketDataService] = (), now_ms: int | None = None
    ) -> None:
        now_ms = self._clock.now_ms() if now_ms is None else now_ms
        started = time.perf_counter()
        for market, sweeps in self._sweeps.items():
            for order in sweeps.flush(now_ms - 1_000):
                await self._handle_order(market, order)
        await self.scan_walls(services, now_ms)
        for result in self.impact.due(now_ms, self.price):
            self._impact_rows.append(
                (
                    result.t0_ms,
                    result.market.value,
                    result.symbol,
                    result.kind,
                    result.direction,
                    result.horizon_s,
                    round(result.return_pct, 6),
                    round(result.directional_pct, 6),
                )
            )
        await self.flush()
        self.ticks += 1
        self.tick_ms_max = max(self.tick_ms_max, (time.perf_counter() - started) * 1000)

    async def flush(self) -> None:
        if self._db is None:
            self._event_rows.clear()
            self._impact_rows.clear()
            return
        events, impacts = self._event_rows, self._impact_rows
        self._event_rows, self._impact_rows = [], []
        try:
            if events:
                await self._db.executemany(_WHALE_EVENT_SQL, events)
            if impacts:
                await self._db.executemany(_IMPACT_SQL, impacts)
        except Exception:
            logger.exception("Balina kayıtları yazılamadı")

    async def restore_impact(self) -> int:
        """Önceki çalıştırmaların etki ölçümlerini istatistiklere yükler."""
        if self._db is None:
            return 0
        rows = await self._db.fetchall(
            "SELECT kind, direction, horizon_s, directional_pct FROM whale_impacts "
            "ORDER BY id DESC LIMIT 200000"
        )
        for kind, direction, horizon, value in rows:
            self.impact.restore(str(kind), int(direction), int(horizon), float(value))
        return len(rows)

    # --- Büyük oyuncu pozisyonlanması ----------------------------------------------------

    async def poll_positioning(self, service: MarketDataService) -> list[PositioningSnapshot]:
        symbols = list(
            dict.fromkeys(
                [*service.focus, *(t.symbol for t in service.tickers(self._cfg.positioning_top_n))]
            )
        )
        snapshots: list[PositioningSnapshot] = []
        for symbol in symbols:
            try:
                snapshot = await fetch_snapshot(service.rest, symbol)
            except Exception as exc:
                logger.debug(
                    "Pozisyon istatistiği alınamadı", extra={"symbol": symbol, "error": repr(exc)}
                )
                continue
            if snapshot is None:
                continue
            previous = self.positioning.get(symbol)
            self.positioning[symbol] = snapshot
            snapshots.append(snapshot)
            if previous is not None and previous.timestamp_ms == snapshot.timestamp_ms:
                continue
            if abs(snapshot.top_long_change_pts) >= self._cfg.positioning_shift_pts:
                direction = "long" if snapshot.top_long_change_pts > 0 else "short"
                crowd = " · kalabalık ters yönde (ayrışma)" if snapshot.divergence else ""
                await self._alert(
                    WhaleAlertKind.POSITIONING_SHIFT,
                    Market.USDM_FUTURES,
                    symbol,
                    Severity.INFO,
                    side=direction,
                    notional=snapshot.open_interest_usd,
                    message=(
                        f"{symbol}: büyük oyuncular son 1 saatte {direction} yönüne kaydı "
                        f"({snapshot.top_long_change_pts:+.1f} puan, "
                        f"long payı %{snapshot.top_long_pct:.1f})"
                        f"{crowd}"
                    ),
                    details=asdict(snapshot),
                )
        return snapshots

    async def _positioning_loop(self, service: MarketDataService) -> None:
        await service.discovered.wait()
        await asyncio.sleep(30)  # önce ticker'lar gelsin (en hacimli semboller seçilir)
        while True:
            await self.poll_positioning(service)
            await asyncio.sleep(self._cfg.positioning_interval_s)

    # --- Zincir üstü ------------------------------------------------------------------------------

    async def poll_onchain(self) -> list[OnchainTransfer]:
        if self._onchain is None:
            return []
        transfers = await self._onchain.poll()
        for transfer in transfers:
            self.onchain_transfers.append(transfer)
            side = {
                FlowType.EXCHANGE_INFLOW: "inflow",
                FlowType.EXCHANGE_OUTFLOW: "outflow",
            }.get(transfer.flow, "transfer")
            self._event_rows.append(
                (
                    transfer.time_ms,
                    "onchain",
                    None,
                    transfer.asset,
                    side,
                    f"{transfer.amount_usd:.2f}",
                    json.dumps(asdict(transfer), default=str),
                )
            )
            label = transfer.recipient_label or transfer.sender_label
            where = {
                FlowType.EXCHANGE_INFLOW: f"{label} borsasına giriş",
                FlowType.EXCHANGE_OUTFLOW: f"{label} borsasından çıkış",
                FlowType.EXCHANGE_INTERNAL: "borsalar arası",
                FlowType.TRANSFER: "cüzdanlar arası",
            }[transfer.flow]
            await self._alert(
                WhaleAlertKind.ONCHAIN_TRANSFER,
                None,
                transfer.tx_hash,
                Severity.INFO,
                side=side,
                notional=transfer.amount_usd,
                message=(
                    f"{transfer.amount:,.2f} {transfer.asset} "
                    f"(~{transfer.amount_usd:,.0f} USD) {where}"
                ),
                details={
                    "chain": transfer.chain,
                    "tx_hash": transfer.tx_hash,
                    "flow": transfer.flow.value,
                },
            )
        return transfers

    async def _onchain_loop(self) -> None:
        while True:
            try:
                await self.poll_onchain()
            except Exception as exc:
                logger.warning("Zincir üstü veri alınamadı", extra={"error": repr(exc)})
            await asyncio.sleep(self._cfg.onchain.interval_s)

    # --- Yaşam döngüsü --------------------------------------------------------------------------

    async def run(self, services: Iterable[MarketDataService] = ()) -> None:
        services = list(services)
        await self.restore_impact()
        tasks: list[asyncio.Task[None]] = []
        if self._cfg.positioning:
            for service in services:
                if service.market is Market.USDM_FUTURES:
                    tasks.append(asyncio.create_task(self._positioning_loop(service)))
        if self._onchain is not None:
            tasks.append(asyncio.create_task(self._onchain_loop()))
        try:
            while True:
                await self.tick(services)
                await asyncio.sleep(1.0)
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await self.flush()

    # --- Sorgular ---------------------------------------------------------------------------

    def summary(
        self, market: Market, *, window_s: int = 3600, limit: int = 20
    ) -> list[dict[str, Any]]:
        cutoff = self._clock.now_ms() - window_s * 1000
        per: dict[str, dict[str, Any]] = {}
        for trade in self.trades:
            if trade.market is not market or trade.event_time_ms < cutoff:
                continue
            row = per.setdefault(
                trade.symbol,
                {
                    "symbol": trade.symbol,
                    "count": 0,
                    "buy_usd": 0.0,
                    "sell_usd": 0.0,
                    "largest_usd": 0.0,
                    "last_ms": 0,
                },
            )
            row["count"] += 1
            row["buy_usd" if trade.side == "buy" else "sell_usd"] += trade.notional
            row["largest_usd"] = max(row["largest_usd"], trade.notional)
            row["last_ms"] = max(row["last_ms"], trade.event_time_ms)
        rows = list(per.values())
        for row in rows:
            row["net_usd"] = row["buy_usd"] - row["sell_usd"]
            row["threshold_usd"] = round(self.threshold(market, row["symbol"]), 2)
        rows.sort(key=lambda r: abs(r["net_usd"]), reverse=True)
        return rows[:limit]

    def stats(self) -> dict[str, Any]:
        now = self._clock.now_ms()
        return {
            "orders_seen": self.orders_seen,
            "whale_trades": len(self.trades),
            "alerts": len(self.alerts),
            "impact_pending": self.impact.pending,
            "ticks": self.ticks,
            "tick_ms_max": round(self.tick_ms_max, 3),
            "liquidations_5m": self.liquidations.totals(now, 300),
            "positioning_symbols": len(self.positioning),
            "onchain_enabled": self._onchain is not None,
        }
