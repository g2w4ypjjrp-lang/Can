"""Canlı fırsat motoru.

* 1 dakikalık kapanmış mumlar (zaten tüm semboller için akıyor) puanlama aralığına (varsayılan
  1 saat) birleştirilir; ek WebSocket akışı gerekmez.
* Isınma: her sembol için son ``warmup_bars`` mum REST'ten düşük öncelikle alınır.
* Her kapanan mumda sembolün strateji defteri güncellenir ve puan hesaplanır. Hesap olay
  döngüsünde küçük parçalar halinde yapılır (Python GIL'i nedeniyle iş parçacığı gecikmeyi
  azaltmaz); böylece piyasa verisinin bekleme süresi sınırlı kalır. Yalnızca numpy ağırlıklı
  benzerlik araması ve isteğe bağlı değerlendirme ayrı iş parçacığında çalışır.
* Bağlam: 24 saatlik hacim, balina akışı, emir defteri (odak sembolleri), funding ve büyük
  oyuncu konumlanması (Futures), varsa eğitilmiş modeller.
* Eşik üstü puanlar arayüze olay olarak gider ve ``opportunities`` tablosuna yazılır.

Puan tek başına emir üretmez.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections import deque
from collections.abc import Awaitable, Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from ati_engine.analysis.features import Bar, FuturesContext, vectorize
from ati_engine.analysis.service import _with_quote
from ati_engine.config import ScoringSettings
from ati_engine.core.bus import EventBus
from ati_engine.core.clock import Clock, SystemClock
from ati_engine.core.events import SystemEvent
from ati_engine.core.models import Market
from ati_engine.exchange.rate_limit import Priority
from ati_engine.history.archive import INTERVAL_MS
from ati_engine.history.similarity import find_similar
from ati_engine.market.events import Kline
from ati_engine.ml.dataset import _bar
from ati_engine.ml.registry import ModelError, ModelRegistry, Predictor
from ati_engine.scoring.costs import CostModel, CostSettingsView
from ati_engine.scoring.score import (
    BookContext,
    Opportunity,
    OpportunityScorer,
    ScoreInputs,
    SimilarityContext,
    WhaleContext,
)
from ati_engine.storage.database import Database
from ati_engine.strategies.base import MarketKind, ModelView
from ati_engine.strategies.book import StrategyBook

if TYPE_CHECKING:
    from ati_engine.history.service import HistoryService
    from ati_engine.market.service import MarketDataService
    from ati_engine.scanner.scanner import MarketScanner
    from ati_engine.whales.radar import WhaleRadar

logger = logging.getLogger(__name__)
MINUTE_MS = 60_000
SIMILARITY_WINDOW = 48
BATCH_CHUNK = 20  # kapanan mumlar bu kadar sembolde bir döngüye söz verilerek işlenir
WARMUP_CHUNK = 25
SIMILARITY_HISTORY = 20_000


class OpportunityScored(SystemEvent, frozen=True, kw_only=True):
    """Eşik üstü fırsat puanı (arayüz bildirimi; emir değildir)."""

    market: Market
    symbol: str
    interval: str
    bar_open_time_ms: int
    direction: str
    score: float
    price: float
    stop_price: float | None
    target_price: float | None
    reward_risk: float | None
    cost_pct: float
    reasons: list[str]
    historical_hit_rate: float | None = None
    historical_net_return_pct: float | None = None


@dataclass(frozen=True)
class LiveBarScore:
    """Canlı akışta kapanan bir mumun puanlama girdileri ve sonucu (dinleyicilere iletilir;
    ör. sanal işlem yarışması). Isınma mumları iletilmez: eski sinyalle işlem açılmaz."""

    market: Market
    symbol: str
    inputs: ScoreInputs
    opportunity: Opportunity


@dataclass
class _Partial:
    bucket: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    quote_volume: float = 0.0
    taker_buy_quote: float = 0.0
    minutes: int = 0


class BarAggregator:
    """Kapanmış 1 dakikalık mumları daha büyük aralığa birleştirir. Aralığın son dakikası
    kapandığında mum hemen yayımlanır; dakika eksikse bir sonraki aralığın ilk mumu gelince."""

    def __init__(self, interval_ms: int) -> None:
        self.interval_ms = interval_ms
        self._open: dict[tuple[Market, str], _Partial] = {}
        self.incomplete = 0

    def add(self, kline: Kline) -> list[tuple[Market, str, Bar, bool]]:
        """Tamamlanan mumları (piyasa, sembol, mum, eksiksiz mi) olarak döndürür. Eksik mum
        (motor aralığın ortasında başladı veya bağlantı koptu) stratejilere verilmemelidir."""
        if kline.interval != "1m" or not kline.closed:
            return []
        key = (kline.market, kline.symbol)
        bucket = kline.open_time_ms - kline.open_time_ms % self.interval_ms
        out: list[tuple[Market, str, Bar, bool]] = []
        partial = self._open.get(key)
        if partial is not None and partial.bucket != bucket:
            if bucket > partial.bucket:
                out.append((kline.market, kline.symbol, *self._finish(partial)))
                partial = None
            else:
                return []  # eski dakika
        if partial is None:
            partial = _Partial(bucket, kline.open, kline.high, kline.low, kline.close)
            self._open[key] = partial
        partial.high = max(partial.high, kline.high)
        partial.low = min(partial.low, kline.low)
        partial.close = kline.close
        partial.volume += kline.volume
        partial.quote_volume += kline.quote_volume
        partial.taker_buy_quote += kline.taker_buy_quote_volume
        partial.minutes += 1
        if kline.open_time_ms + MINUTE_MS >= bucket + self.interval_ms:
            out.append((kline.market, kline.symbol, *self._finish(partial)))
            del self._open[key]
        return out

    def _finish(self, p: _Partial) -> tuple[Bar, bool]:
        complete = p.minutes >= self.interval_ms // MINUTE_MS
        if not complete:
            self.incomplete += 1
        bar = Bar(
            open_time_ms=p.bucket,
            open=p.open,
            high=p.high,
            low=p.low,
            close=p.close,
            volume=p.volume,
            quote_volume=p.quote_volume,
            taker_buy_quote=p.taker_buy_quote,
        )
        return bar, complete


@dataclass
class _Context:
    quote_volume_24h: float | None = None
    whale: WhaleContext | None = None
    book: BookContext | None = None
    futures: FuturesContext | None = None


@dataclass
class EngineStats:
    repairs_requested: int = 0
    repaired: int = 0
    repair_failed: int = 0
    bars: int = 0
    scored: int = 0
    published: int = 0
    warmup_symbols: dict[str, int] = field(default_factory=dict)
    batch_ms_max: float = 0.0
    last_batch_size: int = 0


def load_calibration(directory: Path, market: str, interval: str, horizon: int) -> dict[str, Any]:
    path = directory / f"calibration-{market}-{interval}-h{horizon}.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        logger.warning("Kalibrasyon dosyası okunamadı", extra={"path": str(path)})
        return {}
    return data if isinstance(data, dict) else {}


class OpportunityEngine:
    def __init__(
        self,
        *,
        settings: ScoringSettings,
        bus: EventBus,
        db: Database,
        calibration_dir: Path,
        registry: ModelRegistry | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.cfg = settings
        self.bus = bus
        self.db = db
        self.clock = clock or SystemClock()
        self.interval_ms = INTERVAL_MS[settings.interval]
        self.aggregator = BarAggregator(self.interval_ms)
        self.calibration_dir = calibration_dir
        self.calibration = {
            market.value: load_calibration(
                calibration_dir, market.value, settings.interval, settings.horizon_bars
            )
            for market in Market
        }
        cost_model = CostModel(
            CostSettingsView(
                spot_taker_fee=settings.spot_taker_fee,
                futures_taker_fee=settings.futures_taker_fee,
                notional_usd=settings.notional_usd,
            )
        )
        self.scorers = {
            market: OpportunityScorer(
                weights=settings.weights,
                cost_model=cost_model,
                calibration=self.calibration[market.value] or None,
            )
            for market in Market
        }
        self.books: dict[tuple[Market, str], StrategyBook] = {}
        self.latest: dict[tuple[Market, str], Opportunity] = {}
        self.stats = EngineStats()
        self._pending: list[tuple[Market, str, Bar]] = []
        # İşçi iş parçacığı ekler, olay döngüsü tüketir (deque ekleme/çıkarma iş parçacığı
        # güvenlidir).
        self._warm_scored: deque[Opportunity] = deque()
        self._repairs: asyncio.Queue[tuple[Market, str, int]] = asyncio.Queue()
        self._inputs: dict[tuple[Market, str], ScoreInputs] = {}
        self._listeners: list[Callable[[list[LiveBarScore]], Awaitable[None]]] = []
        self._history: HistoryService | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scoring")
        self._services: dict[Market, MarketDataService] = {}
        self._scanner: MarketScanner | None = None
        self._radar: WhaleRadar | None = None
        self.predictors = self._load_models(registry)

    # --- Kurulum -------------------------------------------------------------------------

    def _load_models(self, registry: ModelRegistry | None) -> dict[Market, dict[str, Predictor]]:
        result: dict[Market, dict[str, Predictor]] = {}
        if registry is None:
            return result
        for market_name, sides in self.cfg.models.items():
            market = Market(market_name)
            for side, model_id in sides.items():
                try:
                    predictor = registry.load(model_id)
                except ModelError as exc:
                    logger.warning(
                        "Model yüklenemedi", extra={"model": model_id, "error": str(exc)}
                    )
                    continue
                if predictor.meta.interval != self.cfg.interval or predictor.meta.side != side:
                    logger.warning(
                        "Model puanlama aralığı/yönüyle uyumsuz", extra={"model": model_id}
                    )
                    continue
                result.setdefault(market, {})[side] = predictor
        return result

    def attach(
        self,
        services: Iterable[MarketDataService] = (),
        *,
        scanner: MarketScanner | None = None,
        radar: WhaleRadar | None = None,
        history: HistoryService | None = None,
    ) -> None:
        self._services = {s.market: s for s in services}
        self._history = history
        self._scanner = scanner
        self._radar = radar
        self.bus.subscribe(Kline, self.on_kline, name="opportunity-klines", maxsize=200_000)

    def add_listener(self, listener: Callable[[list[LiveBarScore]], Awaitable[None]]) -> None:
        self._listeners.append(listener)

    def book(self, market: Market, symbol: str) -> StrategyBook:
        key = (market, symbol)
        book = self.books.get(key)
        if book is None:
            kind: MarketKind = "spot" if market is Market.SPOT else "usdm_futures"
            book = self.books[key] = StrategyBook(kind, symbol)
        return book

    # --- Canlı akış ----------------------------------------------------------------------

    async def on_kline(self, kline: Kline) -> None:
        for market, symbol, bar, complete in self.aggregator.add(kline):
            self.stats.bars += 1
            if complete:
                self._pending.append((market, symbol, bar))
            else:
                # Eksik mum yanlış açılış/hacim verir: kapanmış mumun aslı REST'ten alınır.
                self.stats.repairs_requested += 1
                self._repairs.put_nowait((market, symbol, bar.open_time_ms))

    def _context(self, market: Market, symbol: str, whale_rows: Mapping[str, Any]) -> _Context:
        ctx = _Context()
        service = self._services.get(market)
        if service is not None:
            ticker = service.state.tickers.get(symbol)
            ctx.quote_volume_24h = ticker.quote_volume if ticker else None
        whale = whale_rows.get(symbol)
        if whale is not None:
            ctx.whale = WhaleContext(
                net_usd=float(whale["net_usd"]),
                threshold_usd=float(whale["threshold_usd"]),
                count=int(whale["count"]),
            )
        if self._scanner is not None:
            row = self._scanner.rows.get((market, symbol))
            if row is not None and row.book_imbalance_10 is not None:
                ctx.book = BookContext(
                    imbalance=row.book_imbalance_10,
                    spread_bps=row.spread_bps,
                    notional=row.book_notional_10,
                )
        if market is Market.USDM_FUTURES:
            mark = service.state.marks.get(symbol) if service is not None else None
            position = self._radar.positioning.get(symbol) if self._radar else None
            ctx.futures = FuturesContext(
                funding_rate=mark.funding_rate if mark else None,
                open_interest_usd=position.open_interest_usd if position else None,
                top_long_short=position.top_ratio if position else None,
                global_long_short=position.global_ratio if position else None,
            )
        return ctx

    def _model_fn(self, market: Market) -> Callable[[dict[str, float]], ModelView | None] | None:
        predictors = self.predictors.get(market)
        if not predictors:
            return None

        def predict(features: dict[str, float]) -> ModelView | None:
            values: dict[str, float | None] = {}
            for side in ("long", "short"):
                predictor = predictors.get(side)
                if predictor is None:
                    values[side] = None
                    continue
                names = tuple(predictor.meta.feature_names)
                vector = np.asarray(vectorize(features, names), dtype=np.float32)
                values[side] = float(predictor.predict(vector)[0])
            base = {
                side: p.meta.report.get("oos", {}).get("base_rate")
                for side, p in predictors.items()
            }
            return ModelView(
                p_long=values["long"],
                p_short=values["short"],
                base_long=base.get("long"),
                base_short=base.get("short"),
            )

        return predict

    def _score_batch(self, batch: list[tuple[Market, str, Bar, _Context]]) -> list[Opportunity]:
        """İşçi iş parçacığında çalışır (defterlere yalnızca buradan dokunulur)."""
        result = []
        hours = self.interval_ms / 3_600_000
        for market, symbol, bar, ctx in batch:
            update = self.book(market, symbol).update(bar, ctx.futures, self._model_fn(market))
            if update is None:
                continue
            inputs = ScoreInputs(
                market=market.value,
                symbol=symbol,
                interval=self.cfg.interval,
                interval_hours=hours,
                horizon_bars=self.cfg.horizon_bars,
                snapshot=update.snapshot,
                signals=update.signals,
                levels=update.levels,
                patterns=update.patterns,
                context=update.context,
                quote_volume_24h=ctx.quote_volume_24h,
                whale=ctx.whale,
                book=ctx.book,
                model=update.model,
            )
            opportunity = self.scorers[market].score(inputs)
            self._inputs[(market, symbol)] = inputs
            result.append(opportunity)
        return result

    # --- Tarihsel benzerlik (yalnızca eşik üstü adaylar için) -------------------------------

    def _similarity(
        self, times: list[int], closes: list[float], end_time_ms: int
    ) -> SimilarityContext | None:
        """``end_time_ms`` ile biten pencereye benzeyen geçmiş dönemler (ileriye bakmadan:
        yalnızca o mum dahil öncesi kullanılır)."""
        if end_time_ms not in times:
            return None
        end = times.index(end_time_ms)
        window = SIMILARITY_WINDOW
        if end + 1 < window * 4:
            return None
        result = find_similar(
            times[: end + 1],
            closes[: end + 1],
            window=window,
            top_k=10,
            horizons=(self.cfg.horizon_bars,),
        )
        if not result.forward:
            return None
        stat = result.forward[0]
        return SimilarityContext(
            n=stat.n, positive_rate=stat.positive_rate, median_pct=stat.median_pct
        )

    async def _with_similarity(self, opportunities: list[Opportunity]) -> list[Opportunity]:
        if self._history is None:
            return opportunities
        loop = asyncio.get_running_loop()
        out = []
        for opp in opportunities:
            market = Market(opp.market)
            inputs = self._inputs.get((market, opp.symbol))
            if (
                opp.direction == "none"
                or opp.score < self.cfg.publish_min_score
                or inputs is None
                or inputs.snapshot.open_time_ms != opp.time_ms
            ):
                out.append(opp)
                continue
            rows = await self._history.store.candles(
                opp.market, opp.symbol, self.cfg.interval, tail=SIMILARITY_HISTORY
            )
            if len(rows) < SIMILARITY_WINDOW * 4:
                out.append(opp)
                continue
            times = [int(r[0]) for r in rows]
            closes = [float(r[4]) for r in rows]
            similarity = await loop.run_in_executor(
                self._executor, self._similarity, times, closes, opp.time_ms
            )
            if similarity is None:
                out.append(opp)
                continue
            out.append(self.scorers[market].score(replace(inputs, similarity=similarity)))
        return out

    async def process_pending(self) -> list[Opportunity]:
        warm: list[Opportunity] = []
        while self._warm_scored:
            warm.append(self._warm_scored.popleft())
        if warm:
            await self._publish(await self._with_similarity(warm))
        if not self._pending:
            return []
        items, self._pending = self._pending, []
        whale_rows: dict[Market, dict[str, Any]] = {}
        if self._radar is not None:
            for market in {m for m, _, _ in items}:
                whale_rows[market] = {
                    r["symbol"]: r for r in self._radar.summary(market, window_s=3600, limit=10_000)
                }
        batch = [(m, s, bar, self._context(m, s, whale_rows.get(m, {}))) for m, s, bar in items]
        loop = asyncio.get_running_loop()
        started = loop.time()
        opportunities: list[Opportunity] = []
        for offset in range(0, len(batch), BATCH_CHUNK):
            opportunities.extend(self._score_batch(batch[offset : offset + BATCH_CHUNK]))
            await asyncio.sleep(0)  # piyasa verisi işlenmeye devam etsin
        elapsed = (loop.time() - started) * 1000
        self.stats.batch_ms_max = max(self.stats.batch_ms_max, elapsed)
        self.stats.last_batch_size = len(batch)
        opportunities = await self._with_similarity(opportunities)
        await self._publish(opportunities)
        if self._listeners:
            scored = [
                LiveBarScore(Market(o.market), o.symbol, inputs, o)
                for o in opportunities
                if (inputs := self._inputs.get((Market(o.market), o.symbol))) is not None
                and inputs.snapshot.open_time_ms == o.time_ms
            ]
            for listener in self._listeners:
                try:
                    await listener(scored)
                except Exception as exc:  # dinleyici hatası puanlamayı durdurmaz
                    logger.error("Fırsat dinleyicisi hatası", extra={"error": repr(exc)})
        return opportunities

    async def _publish(self, opportunities: list[Opportunity]) -> None:
        rows = []
        for opp in opportunities:
            market = Market(opp.market)
            self.latest[(market, opp.symbol)] = opp
            self.stats.scored += 1
            if opp.direction == "none" or opp.score < self.cfg.publish_min_score:
                continue
            self.stats.published += 1
            calibration = opp.calibration or {}
            await self.bus.publish(
                OpportunityScored(
                    market=market,
                    symbol=opp.symbol,
                    interval=opp.interval,
                    bar_open_time_ms=opp.time_ms,
                    direction=opp.direction,
                    score=opp.score,
                    price=opp.price,
                    stop_price=opp.stop_price,
                    target_price=opp.target_price,
                    reward_risk=opp.reward_risk,
                    cost_pct=opp.cost.total_pct,
                    reasons=top_reasons(opp),
                    historical_hit_rate=calibration.get("hit_rate"),
                    historical_net_return_pct=calibration.get("mean_net_return_pct"),
                )
            )
            rows.append(
                (
                    opp.time_ms,
                    opp.market,
                    opp.symbol,
                    opp.interval,
                    opp.direction,
                    opp.score,
                    opp.price,
                    opp.stop_price,
                    opp.target_price,
                    opp.reward_risk,
                    opp.cost.total_pct,
                    json.dumps(opp.to_dict(), ensure_ascii=False),
                )
            )
        if rows:
            await self.db.executemany(
                """
                INSERT OR IGNORE INTO opportunities (ts, market, symbol, interval, direction,
                    score, price, stop_price, target_price, reward_risk, cost_pct, breakdown)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    # --- Isınma --------------------------------------------------------------------------

    async def _load_rows(
        self,
        market: Market,
        symbol: str,
        rows: list[list[Any]],
        now_ms: int,
        ctx: _Context | None = None,
    ) -> int:
        """Isınma mumlarını deftere yükler; ``ctx`` verilirse son kapanmış mum hemen puanlanır
        (arayüz bir sonraki mumu beklemeden güncel puanları görür).

        Hesap olay döngüsünde küçük parçalar halinde yapılır: Python'un küresel kilidi (GIL)
        nedeniyle ayrı bir iş parçacığı döngüyü rahatlatmaz, aksine gecikmeyi öngörülemez
        kılar (canlı ölçümde p99 157 ms). Her ``WARMUP_CHUNK`` mumda döngüye söz verilir."""
        book = self.book(market, symbol)
        loaded = 0
        last_bar: Bar | None = None
        closed = [r for r in rows if int(r[6]) < now_ms]
        for index, row in enumerate(closed):
            bar = Bar(
                open_time_ms=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
                quote_volume=float(row[7]),
                taker_buy_quote=float(row[10]),
            )
            if ctx is not None and index == len(closed) - 1:
                last_bar = bar
                break
            book.update(bar)
            loaded += 1
            if loaded % WARMUP_CHUNK == 0:
                await asyncio.sleep(0)
        if last_bar is not None and ctx is not None:
            self._warm_scored.extend(self._score_batch([(market, symbol, last_bar, ctx)]))
            loaded += 1
        return loaded

    async def warmup(self, service: MarketDataService, *, concurrency: int = 3) -> int:
        await service.discovered.wait()
        endpoints = service.endpoints
        limit = self.cfg.warmup_bars
        sem = asyncio.Semaphore(concurrency)
        done = 0
        whale_cache: dict[str, Any] = {}
        whale_cached_at = -1e9
        loop = asyncio.get_running_loop()

        async def one(symbol: str) -> None:
            nonlocal done
            async with sem:
                try:
                    rows = await service.rest.get(
                        endpoints.klines_path,
                        params={"symbol": symbol, "interval": self.cfg.interval, "limit": limit},
                        weight=endpoints.klines_weight(limit),
                        priority=Priority.LOW,
                    )
                except Exception as exc:
                    logger.warning(
                        "Puanlama ısınması: mumlar alınamadı",
                        extra={"symbol": symbol, "error": repr(exc)},
                    )
                    return
                nonlocal whale_cache, whale_cached_at
                if self._radar is not None and loop.time() - whale_cached_at > 30:
                    # Balina özeti tüm işlemleri tarar: sembol başına değil, 30 sn'de bir.
                    whale_cache = {
                        r["symbol"]: r for r in self._radar.summary(service.market, limit=10_000)
                    }
                    whale_cached_at = loop.time()
                await self._load_rows(
                    service.market,
                    symbol,
                    rows,
                    self.clock.now_ms(),
                    self._context(service.market, symbol, whale_cache),
                )
                done += 1
                self.stats.warmup_symbols[service.market.value] = done

        await asyncio.gather(*(one(s) for s in service.tracked_symbols()))
        logger.info(
            "Puanlama ısınması tamamlandı", extra={"market": service.market.value, "symbols": done}
        )
        return done

    async def repair_one(self, market: Market, symbol: str, open_ms: int) -> bool:
        """Eksik toplanan mumun kapanmış aslını REST'ten alıp işleme kuyruğuna ekler."""
        service = self._services.get(market)
        if service is None:
            self.stats.repair_failed += 1
            return False
        endpoints = service.endpoints
        try:
            rows = await service.rest.get(
                endpoints.klines_path,
                params={
                    "symbol": symbol,
                    "interval": self.cfg.interval,
                    "startTime": open_ms,
                    "limit": 1,
                },
                weight=endpoints.klines_weight(1),
                priority=Priority.LOW,
            )
        except Exception as exc:
            logger.warning("Eksik mum onarılamadı", extra={"symbol": symbol, "error": repr(exc)})
            self.stats.repair_failed += 1
            return False
        row = rows[0] if rows else None
        if row is None or int(row[0]) != open_ms or int(row[6]) >= self.clock.now_ms():
            self.stats.repair_failed += 1
            return False
        self._pending.append(
            (
                market,
                symbol,
                Bar(
                    open_time_ms=open_ms,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                    quote_volume=float(row[7]),
                    taker_buy_quote=float(row[10]),
                ),
            )
        )
        self.stats.repaired += 1
        return True

    async def _repair_loop(self, concurrency: int = 3) -> None:
        sem = asyncio.Semaphore(concurrency)

        async def one(item: tuple[Market, str, int]) -> None:
            async with sem:
                await self.repair_one(*item)

        tasks: set[asyncio.Task[None]] = set()
        while True:
            item = await self._repairs.get()
            task = asyncio.create_task(one(item))
            tasks.add(task)
            task.add_done_callback(tasks.discard)

    async def run(self) -> None:
        warmups: list[asyncio.Task[Any]] = [
            asyncio.create_task(self.warmup(s)) for s in self._services.values()
        ]
        warmups.append(asyncio.create_task(self._repair_loop()))
        try:
            while True:
                await asyncio.sleep(1.0)
                await self.process_pending()
        finally:
            for task in warmups:
                task.cancel()
            for task in warmups:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    # --- İsteğe bağlı değerlendirme (tarihsel depodan) -------------------------------------

    async def evaluate_from_history(
        self, history: HistoryService, market: Market, symbol: str
    ) -> Opportunity:
        """Canlı akışı olmayan bir sembolü depodaki mumlarla değerlendirir (son kapanmış mum)."""
        symbol = symbol.upper()
        rows = await history.bars(market, symbol, self.cfg.interval, tail=self.cfg.warmup_bars)
        if len(rows) < 230:
            raise ValueError(
                f"Yeterli tarihsel veri yok ({len(rows)} mum); önce {self.cfg.interval} "
                "aralığında eşitleyin"
            )
        whale_rows: dict[str, Any] = {}
        if self._radar is not None:
            whale_rows = {
                r["symbol"]: r for r in self._radar.summary(market, window_s=3600, limit=10_000)
            }
        ctx = self._context(market, symbol, whale_rows)
        day_bars = max(1, 86_400_000 // self.interval_ms)
        kind: MarketKind = "spot" if market is Market.SPOT else "usdm_futures"
        model_fn = self._model_fn(market)
        last_inputs: list[ScoreInputs] = []

        def run() -> Opportunity:
            book = StrategyBook(kind, symbol)
            update = None
            normalized = [_with_quote(r) for r in rows]
            for i, row in enumerate(normalized):
                last = i == len(normalized) - 1
                update = book.update(
                    _bar(row), ctx.futures if last else None, model_fn if last else None
                )
            if update is None:
                raise ValueError("Göstergeler ısınmadı")
            quote_24h = ctx.quote_volume_24h or sum(float(r[6]) for r in normalized[-day_bars:])
            inputs = ScoreInputs(
                market=market.value,
                symbol=symbol,
                interval=self.cfg.interval,
                interval_hours=self.interval_ms / 3_600_000,
                horizon_bars=self.cfg.horizon_bars,
                snapshot=update.snapshot,
                signals=update.signals,
                levels=update.levels,
                patterns=update.patterns,
                context=update.context,
                quote_volume_24h=quote_24h,
                whale=ctx.whale,
                book=ctx.book,
                model=update.model,
            )
            last_inputs.append(inputs)
            return self.scorers[market].score(inputs)

        loop = asyncio.get_running_loop()
        opportunity = await loop.run_in_executor(self._executor, run)
        long_rows = await history.store.candles(
            market.value, symbol, self.cfg.interval, tail=SIMILARITY_HISTORY
        )
        if opportunity.direction != "none" and len(long_rows) >= SIMILARITY_WINDOW * 4:
            similarity = await loop.run_in_executor(
                self._executor,
                self._similarity,
                [int(r[0]) for r in long_rows],
                [float(r[4]) for r in long_rows],
                opportunity.time_ms,
            )
            if similarity is not None:
                opportunity = self.scorers[market].score(
                    replace(last_inputs[0], similarity=similarity)
                )
        return opportunity

    # --- Sorgular ------------------------------------------------------------------------

    def top(
        self,
        market: Market | None = None,
        *,
        min_score: float = 0.0,
        direction: str | None = None,
        limit: int = 50,
    ) -> list[Opportunity]:
        rows = [
            o
            for (m, _), o in self.latest.items()
            if (market is None or m is market)
            and o.score >= min_score
            and o.direction != "none"
            and (direction is None or o.direction == direction)
        ]
        rows.sort(key=lambda o: -o.score)
        return rows[:limit]

    async def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def top_reasons(opp: Opportunity, limit: int = 3) -> list[str]:
    """En çok katkı yapan bileşenler ve en güçlü strateji gerekçeleri (kısa liste)."""
    reasons = [
        f"{c.title}: {c.detail}"
        for c in sorted(opp.components, key=lambda c: -c.points)
        if c.points > 0
    ][:limit]
    strongest = sorted(
        (s for s in opp.signals if s["direction"] == opp.direction),
        key=lambda s: -s["strength"],
    )
    if strongest:
        reasons.append(f"Strateji: {strongest[0]['reason']}")
    return reasons
