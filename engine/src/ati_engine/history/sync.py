"""Artımlı tarihsel veri eşitleme.

İlk çalıştırmada sembolün arşivdeki ilk ayından (listelenme tarihi) bugüne kadar tüm dosyalar
indirilir: tamamlanmış aylar için aylık dosyalar, aylık dosyası henüz yayınlanmamış aylar için
günlük dosyalar. İşlenen son mum ``history_sync_state`` tablosuna yazılır; sonraki
çalıştırmalarda yalnızca bu noktadan sonraki dosyalar indirilir.

Her dosyadan sonra durum güncellenir. İşlem yarıda kesilirse en fazla bir dosya yeniden
indirilir; aynı mum ikinci kez yazılmaz (birincil anahtar).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from ati_engine.core.models import Market
from ati_engine.history.archive import (
    INTERVAL_MS,
    ArchiveClient,
    ArchiveFile,
    klines_prefix,
    month_of,
    parse_klines,
)
from ati_engine.history.store import KlineStore
from ati_engine.storage.database import Database

logger = logging.getLogger(__name__)


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
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency >= 1 olmalı")
        self.concurrency = concurrency
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
        self, market: Market, symbol: str, interval: str, first: int, last: int
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO history_sync_state (market, symbol, dataset, first_ts, last_ts, source,
                                            updated_at)
            VALUES (?, ?, ?, ?, ?, 'bulk_archive', ?)
            ON CONFLICT (market, symbol, dataset) DO UPDATE SET
                first_ts = min(coalesce(first_ts, excluded.first_ts), excluded.first_ts),
                last_ts = max(coalesce(last_ts, excluded.last_ts), excluded.last_ts),
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (market.value, symbol, self.dataset(interval), first, last, int(time.time() * 1000)),
        )

    async def plan(self, market: Market, symbol: str, interval: str) -> list[ArchiveFile]:
        """Arşivde bulunan ve sembolün tüm geçmişini kapsayan dosya listesi."""
        monthly = await self.archive.list(klines_prefix(market, symbol, interval, "monthly"))
        daily_prefix = klines_prefix(market, symbol, interval, "daily")
        today = self._today()
        daily: list[ArchiveFile] = []
        if monthly:
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
