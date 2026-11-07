"""Artımlı tarihsel veri eşitleme.

İlk çalıştırmada sembolün arşivdeki ilk ayından bugüne kadar tüm dosyalar indirilir:
tamamlanmış aylar için aylık dosyalar, aylık dosyası henüz yayınlanmamış aylar için günlük
dosyalar. Arşivin kapsamadığı iki uç REST ``klines`` ile tamamlanır (REST istemcisi
verildiyse):

* **Baş:** bazı semboller arşivin başlangıcından önce listelenmiştir (ör. ETHUSDT vadeli
  2019-11-27'de listelendi, arşiv 2019-12-31'de başlıyor). İlk eşitlemede bu dönem REST ile
  alınır.
* **Kuyruk:** arşiv yalnızca dünü içerir; bugünün **kapanmış** mumları REST ile alınır.
 İşlenen son mum ``history_sync_state`` tablosuna yazılır; sonraki
çalıştırmalarda yalnızca bu noktadan sonraki dosyalar indirilir.

Her dosyadan sonra durum güncellenir. İşlem yarıda kesilirse en fazla bir dosya yeniden
indirilir; aynı mum ikinci kez yazılmaz (birincil anahtar).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from ati_engine.core.models import Market
from ati_engine.exchange.endpoints import MarketEndpoints
from ati_engine.exchange.rate_limit import Priority
from ati_engine.exchange.rest import BinanceRestClient
from ati_engine.history.archive import (
    INTERVAL_MS,
    ArchiveClient,
    ArchiveFile,
    kline_from_rest,
    klines_prefix,
    month_of,
    parse_klines,
)
from ati_engine.history.store import KlineStore
from ati_engine.storage.database import Database

logger = logging.getLogger(__name__)

RestSource = tuple[BinanceRestClient, MarketEndpoints]
REST_PAGE = 1000


@dataclass
class SyncReport:
    market: str
    symbol: str
    interval: str
    files_listed: int = 0
    files_downloaded: int = 0
    files_skipped: int = 0
    rows_inserted: int = 0
    bytes_downloaded: int = 0
    first_open_ms: int | None = None
    last_open_ms: int | None = None
    seconds: float = 0.0
    downloaded: list[str] = field(default_factory=list)
    rest_requests: int = 0
    rest_rows: int = 0
    gaps_checked: int = 0  # veri içindeki boşluklar (borsa kesintisi veya eksik arşiv)
    gaps_rows: int = 0  # boşluklardan REST ile tamamlanan mum


def _months_after(month: str, until: date) -> list[str]:
    year, mon = (int(p) for p in month.split("-"))
    result: list[str] = []
    while True:
        mon += 1
        if mon == 13:
            year, mon = year + 1, 1
        candidate = f"{year:04d}-{mon:02d}"
        if candidate > month_of(until):
            return result
        result.append(candidate)


class HistorySync:
    def __init__(
        self,
        archive: ArchiveClient,
        store: KlineStore,
        db: Database,
        *,
        today: Callable[[], date] = lambda: datetime.now(UTC).date(),
        concurrency: int = 6,
        rest: Mapping[Market, RestSource] | None = None,
        now_ms: Callable[[], int] = lambda: int(time.time() * 1000),
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency >= 1 olmalı")
        self.concurrency = concurrency
        self._rest: dict[Market, RestSource] = dict(rest or {})
        self.max_gap_repairs = 500
        self._now_ms = now_ms
        self.archive = archive
        self.store = store
        self.db = db
        self._today = today

    @staticmethod
    def dataset(interval: str) -> str:
        return f"klines_{interval}"

    async def state(
        self, market: Market, symbol: str, interval: str
    ) -> tuple[int | None, int | None]:
        row = await self.db.fetchone(
            "SELECT first_ts, last_ts FROM history_sync_state "
            "WHERE market = ? AND symbol = ? AND dataset = ?",
            (market.value, symbol, self.dataset(interval)),
        )
        return (row[0], row[1]) if row else (None, None)

    async def _save_state(
        self,
        market: Market,
        symbol: str,
        interval: str,
        first: int,
        last: int,
        source: str = "bulk_archive",
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO history_sync_state (market, symbol, dataset, first_ts, last_ts, source,
                                            updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (market, symbol, dataset) DO UPDATE SET
                first_ts = min(coalesce(first_ts, excluded.first_ts), excluded.first_ts),
                last_ts = max(coalesce(last_ts, excluded.last_ts), excluded.last_ts),
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (
                market.value,
                symbol,
                self.dataset(interval),
                first,
                last,
                source,
                int(time.time() * 1000),
            ),
        )

    async def _rest_fill(
        self,
        market: Market,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        report: SyncReport,
    ) -> None:
        """[start_ms, end_ms) aralığındaki **kapanmış** mumları REST ile alır (düşük öncelik,
        motorun ortak ağırlık bütçesiyle)."""
        client, endpoints = self._rest[market]
        step = INTERVAL_MS[interval]
        cursor = start_ms
        while cursor < end_ms:
            payload = await client.get(
                endpoints.klines_path,
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": end_ms - 1,
                    "limit": REST_PAGE,
                },
                weight=endpoints.klines_weight(REST_PAGE),
                priority=Priority.LOW,
            )
            report.rest_requests += 1
            now = self._now_ms()
            rows = [kline_from_rest(r) for r in payload]
            closed = [r for r in rows if r[6] < now and start_ms <= r[0] < end_ms]
            if closed:
                report.rest_rows += await self.store.insert(market.value, symbol, interval, closed)
                await self._save_state(
                    market, symbol, interval, closed[0][0], closed[-1][0], source="rest"
                )
            if len(rows) < REST_PAGE or not closed:
                break
            cursor = closed[-1][0] + step

    async def plan(self, market: Market, symbol: str, interval: str) -> list[ArchiveFile]:
        """Arşivde bulunan ve sembolün tüm geçmişini kapsayan dosya listesi."""
        monthly = await self.archive.list(klines_prefix(market, symbol, interval, "monthly"))
        daily_prefix = klines_prefix(market, symbol, interval, "daily")
        today = self._today()
        daily: list[ArchiveFile] = []
        if monthly:
            # İlk aylık dosyadan önceki ayda yalnızca günlük dosyası olan günler (ör. ayın
            # son günü listelenen semboller).
            year, mon = (int(p) for p in monthly[0].period.split("-"))
            previous = f"{year - 1:04d}-12" if mon == 1 else f"{year:04d}-{mon - 1:02d}"
            head = await self.archive.list(f"{daily_prefix}{symbol}-{interval}-{previous}")
            daily.extend(f for f in head if f.end_ms <= monthly[0].start_ms)
            for month in _months_after(monthly[-1].period, today):
                daily.extend(await self.archive.list(f"{daily_prefix}{symbol}-{interval}-{month}"))
        else:
            daily = await self.archive.list(daily_prefix)  # bu ay listelenmiş yeni sembol
        return sorted(monthly + daily)

    async def sync_klines(self, market: Market, symbol: str, interval: str = "1m") -> SyncReport:
        if interval not in INTERVAL_MS:
            raise ValueError(f"Desteklenmeyen aralık: {interval}")
        symbol = symbol.upper()
        started = time.perf_counter()
        bytes_before = self.archive.bytes_downloaded
        report = SyncReport(market=market.value, symbol=symbol, interval=interval)
        _, last_ts = await self.state(market, symbol, interval)
        initial = last_ts is None
        previous_last = last_ts or 0
        files = await self.plan(market, symbol, interval)
        report.files_listed = len(files)
        step = INTERVAL_MS[interval]
        pending: list[ArchiveFile] = []
        for item in files:
            if last_ts is not None and item.end_ms - step <= last_ts:
                report.files_skipped += 1
            else:
                pending.append(item)
        # İndirmeler paralel (sınırlı), yazma ve durum güncellemesi dönem sırasıyla yapılır:
        # bir dosya başarısız olursa ondan önceki dosyalar yazılmış ve kaydedilmiş olur.
        for offset in range(0, len(pending), self.concurrency):
            batch = pending[offset : offset + self.concurrency]
            results = await asyncio.gather(
                *(self.archive.download(item.key) for item in batch), return_exceptions=True
            )
            for item, result in zip(batch, results, strict=True):
                if isinstance(result, BaseException):
                    raise result
                # Dosya dönemi dışındaki satırlar (olmamalı) güvenlik için atılır.
                rows = [r for r in parse_klines(result) if item.start_ms <= r[0] < item.end_ms]
                if not rows:
                    continue
                inserted = await self.store.insert(market.value, symbol, interval, rows)
                await self._save_state(market, symbol, interval, rows[0][0], rows[-1][0])
                report.files_downloaded += 1
                report.rows_inserted += inserted
                report.downloaded.append(item.period)
        if market in self._rest:
            first_ts, _ = await self.state(market, symbol, interval)
            if initial:
                # Arşivden önceki dönem (veya arşivde hiç yoksa tüm geçmiş).
                head_end = first_ts if first_ts is not None else self._now_ms()
                await self._rest_fill(market, symbol, interval, 0, head_end, report)
            _, last_ts = await self.state(market, symbol, interval)
            if last_ts is not None:
                await self._rest_fill(
                    market, symbol, interval, last_ts + step, self._now_ms(), report
                )
            # Binance arşivinde nadiren eksik günler olur (ör. 2026-10-28 vadeli dosyaları);
            # REST bu günleri içerir. Yalnızca bu eşitlemede eklenen aralıktaki boşluklar
            # denenir: gerçek borsa kesintileri boş döner ve her seferinde tekrar sorulmaz.
            since = max(previous_last - step, 0)
            for before, after in await self.store.gaps(
                market.value, symbol, interval, since_ms=since, limit=self.max_gap_repairs
            ):
                report.gaps_checked += 1
                rows_before = report.rest_rows
                await self._rest_fill(market, symbol, interval, before + step, after, report)
                report.gaps_rows += report.rest_rows - rows_before
        first_ts, last_ts = await self.state(market, symbol, interval)
        report.first_open_ms, report.last_open_ms = first_ts, last_ts
        report.bytes_downloaded = self.archive.bytes_downloaded - bytes_before
        report.seconds = round(time.perf_counter() - started, 3)
        logger.info(
            "Tarihsel veri eşitlendi",
            extra={
                "market": market.value,
                "symbol": symbol,
                "interval": interval,
                "downloaded": report.files_downloaded,
                "skipped": report.files_skipped,
                "rows": report.rows_inserted,
            },
        )
        return report
