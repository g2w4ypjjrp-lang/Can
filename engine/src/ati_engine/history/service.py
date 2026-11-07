"""Motor içindeki tarihsel veri servisi: depo, arka plan eşitleme işleri ve analiz uçları.

DuckDB dosyası tek bir süreç tarafından yazılabilir; motor çalışırken eşitleme bu servis
(yerel API) üzerinden yapılır.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ati_engine.core.models import Market
from ati_engine.history.archive import INTERVAL_MS, ArchiveClient
from ati_engine.history.levels import Level, TrendAnalysis, find_levels, trend_analysis
from ati_engine.history.similarity import SimilarityResult, find_similar
from ati_engine.history.store import KlineStore
from ati_engine.history.sync import HistorySync, RestSource, SyncReport
from ati_engine.storage.database import Database

logger = logging.getLogger(__name__)


@dataclass
class SyncJob:
    id: int
    market: Market
    symbols: list[str]
    interval: str
    state: str = "running"  # running | done | failed
    started_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    finished_ms: int | None = None
    current: str | None = None
    reports: list[SyncReport] = field(default_factory=list)
    error: str | None = None


class HistoryService:
    def __init__(
        self,
        store: KlineStore,
        db: Database,
        *,
        archive: ArchiveClient | None = None,
        concurrency: int = 6,
        rest: Mapping[Market, RestSource] | None = None,
        owned_rest: Sequence[Any] = (),
    ) -> None:
        self.store = store
        self.archive = archive or ArchiveClient()
        self.sync = HistorySync(self.archive, store, db, concurrency=concurrency, rest=rest)
        self._owned_rest = list(owned_rest)  # yalnızca bu servisin açtığı REST istemcileri
        self.jobs: dict[int, SyncJob] = {}
        self._ids = itertools.count(1)
        self._tasks: set[asyncio.Task[None]] = set()
        self._lock = asyncio.Lock()  # aynı anda tek eşitleme (arşiv sunucusuna nazik)

    # --- Eşitleme ----------------------------------------------------------------------

    def start_sync(self, market: Market, symbols: Sequence[str], interval: str) -> SyncJob:
        if interval not in INTERVAL_MS:
            raise ValueError(f"Desteklenmeyen aralık: {interval}")
        job = SyncJob(
            id=next(self._ids),
            market=market,
            symbols=[s.upper() for s in symbols],
            interval=interval,
        )
        self.jobs[job.id] = job
        task = asyncio.create_task(self._run(job), name=f"history-sync-{job.id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def _run(self, job: SyncJob) -> None:
        try:
            async with self._lock:
                for symbol in job.symbols:
                    job.current = symbol
                    job.reports.append(
                        await self.sync.sync_klines(job.market, symbol, job.interval)
                    )
            job.state = "done"
        except asyncio.CancelledError:
            job.state = "failed"
            job.error = "iptal edildi"
            raise
        except Exception as exc:
            job.state = "failed"
            job.error = f"{type(exc).__name__}: {exc}"[:300]
            logger.warning("Tarihsel veri eşitlemesi başarısız", extra={"error": job.error})
        finally:
            job.current = None
            job.finished_ms = int(time.time() * 1000)

    # --- Veri ----------------------------------------------------------------------------

    async def bars(
        self, market: Market, symbol: str, interval: str, *, tail: int
    ) -> list[tuple[Any, ...]]:
        """Son ``tail`` mum. Aralık depoda yoksa 1 dakikalık veriden üretilir."""
        if interval not in INTERVAL_MS:
            raise ValueError(f"Desteklenmeyen aralık: {interval}")
        symbol = symbol.upper()
        direct = await self.store.candles(market.value, symbol, interval, tail=tail)
        if direct:
            return direct
        coverage = await self.store.coverage(market.value, symbol, "1m")
        if not coverage.rows or coverage.last_open_ms is None or interval == "1m":
            return []
        step = INTERVAL_MS[interval]
        last_bucket = coverage.last_open_ms - coverage.last_open_ms % step
        rows = await self.store.resample(
            market.value,
            symbol,
            source_interval="1m",
            target_ms=step,
            start_ms=last_bucket - (tail - 1) * step,
        )
        return rows[-tail:]

    async def levels(
        self, market: Market, symbol: str, interval: str, *, tail: int
    ) -> tuple[list[tuple[Any, ...]], list[Level]]:
        rows = await self.bars(market, symbol, interval, tail=tail)
        return rows, await asyncio.to_thread(find_levels, rows)

    async def trend(
        self, market: Market, symbol: str, interval: str, *, tail: int
    ) -> tuple[list[tuple[Any, ...]], TrendAnalysis]:
        rows = await self.bars(market, symbol, interval, tail=tail)
        return rows, await asyncio.to_thread(trend_analysis, rows)

    async def similar(
        self,
        market: Market,
        symbol: str,
        interval: str,
        *,
        tail: int,
        window: int,
        top_k: int,
        horizons: Sequence[int],
    ) -> SimilarityResult:
        rows = await self.bars(market, symbol, interval, tail=tail)
        if len(rows) < window * 3:
            raise ValueError("Benzerlik araması için yeterli tarihsel veri yok; önce eşitleyin")
        times = [int(r[0]) for r in rows]
        closes = [float(r[4]) for r in rows]
        return await asyncio.to_thread(
            find_similar, times, closes, window=window, top_k=top_k, horizons=tuple(horizons)
        )

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await self.archive.close()
        for client in self._owned_rest:
            with contextlib.suppress(Exception):
                await client.close()
        await self.store.close()
