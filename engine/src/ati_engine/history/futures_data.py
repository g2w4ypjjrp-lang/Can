"""USDⓈ-M Futures tarihsel bağlam verisi (Binance arşivi):

* ``metrics`` (günlük dosyalar, 5 dakikalık): açık pozisyon değeri, büyük oyuncu hesap/pozisyon
  long-short oranları, genel hesap long-short oranı, agresif alış/satış hacim oranı.
* ``fundingRate`` (aylık dosyalar): funding oranları.

Veriler mumlarla aynı DuckDB dosyasında tutulur. Mumlarla birleştirme **ASOF** ile yapılır:
her mum, kapanış zamanında veya öncesinde yayımlanmış en son kayıtla eşleşir (ileriye bakma
yok).
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ati_engine.core.models import Market
from ati_engine.history.archive import ArchiveClient, ArchiveError, ArchiveFile
from ati_engine.history.store import KlineStore
from ati_engine.storage.database import Database

logger = logging.getLogger(__name__)

METRICS_DATASET = "metrics_5m"
FUNDING_DATASET = "funding"
METRICS_STEP_MS = 300_000
# Bir mumla eşleşen kaydın en fazla yaşı. Daha eskiyse veri eksik sayılır (nan); aksi halde
# arşivde henüz yayınlanmamış dönemde haftalar önceki değer kullanılırdı.
METRICS_MAX_AGE_MS = 15 * 60_000
FUNDING_MAX_AGE_MS = 9 * 3_600_000

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS futures_metrics (
        symbol            VARCHAR NOT NULL,
        time_ms           BIGINT  NOT NULL,
        oi_usd            DOUBLE,
        top_ls_accounts   DOUBLE,
        top_ls_positions  DOUBLE,
        global_ls         DOUBLE,
        taker_ls          DOUBLE,
        PRIMARY KEY (symbol, time_ms)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS funding_rates (
        symbol      VARCHAR NOT NULL,
        time_ms     BIGINT  NOT NULL,
        rate        DOUBLE  NOT NULL,
        interval_h  INTEGER,
        PRIMARY KEY (symbol, time_ms)
    )
    """,
)


def _csv_lines(data: bytes) -> list[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = [n for n in archive.namelist() if n.endswith(".csv")]
            if len(names) != 1:
                raise ArchiveError(f"Beklenmeyen zip içeriği: {archive.namelist()}")
            return archive.read(names[0]).decode("ascii").splitlines()
    except zipfile.BadZipFile as exc:
        raise ArchiveError(f"Bozuk zip: {exc}") from exc


def _float(raw: str) -> float | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


MetricsRow = tuple[int, float | None, float | None, float | None, float | None, float | None]
FundingRow = tuple[int, float, int | None]


def parse_metrics(data: bytes) -> list[MetricsRow]:
    rows: list[MetricsRow] = []
    for line in _csv_lines(data):
        if not line or not line[0].isdigit():
            continue  # başlık
        f = line.split(",")
        stamp = datetime.strptime(f[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        rows.append(
            (
                int(stamp.timestamp() * 1000),
                _float(f[3]),  # sum_open_interest_value
                _float(f[4]),  # count_toptrader_long_short_ratio
                _float(f[5]),  # sum_toptrader_long_short_ratio
                _float(f[6]),  # count_long_short_ratio
                _float(f[7]),  # sum_taker_long_short_vol_ratio
            )
        )
    return rows


def parse_funding(data: bytes) -> list[FundingRow]:
    rows: list[FundingRow] = []
    for line in _csv_lines(data):
        if not line or not line[0].isdigit():
            continue
        f = line.split(",")
        interval = _float(f[1])
        rate = _float(f[2])
        if rate is None:
            continue
        rows.append((int(f[0]), rate, int(interval) if interval is not None else None))
    return rows


@dataclass
class FuturesSyncReport:
    symbol: str
    metrics_files: int = 0
    metrics_rows: int = 0
    funding_files: int = 0
    funding_rows: int = 0
    seconds: float = 0.0


class FuturesDataSync:
    def __init__(
        self, archive: ArchiveClient, store: KlineStore, db: Database, *, concurrency: int = 8
    ) -> None:
        self.archive = archive
        self.store = store
        self.db = db
        self.concurrency = concurrency
        store.execute_script(_SCHEMA)

    async def _state(self, symbol: str, dataset: str) -> tuple[int | None, int | None]:
        row = await self.db.fetchone(
            "SELECT first_ts, last_ts FROM history_sync_state "
            "WHERE market = ? AND symbol = ? AND dataset = ?",
            (Market.USDM_FUTURES.value, symbol, dataset),
        )
        if not row:
            return None, None
        return (
            int(row[0]) if row[0] is not None else None,
            int(row[1]) if row[1] is not None else None,
        )

    async def _save(self, symbol: str, dataset: str, first: int, last: int) -> None:
        await self.db.execute(
            """
            INSERT INTO history_sync_state (market, symbol, dataset, first_ts, last_ts, source,
                                            updated_at)
            VALUES (?, ?, ?, ?, ?, 'bulk_archive', ?)
            ON CONFLICT (market, symbol, dataset) DO UPDATE SET
                first_ts = min(coalesce(first_ts, excluded.first_ts), excluded.first_ts),
                last_ts = max(coalesce(last_ts, excluded.last_ts), excluded.last_ts),
                updated_at = excluded.updated_at
            """,
            (Market.USDM_FUTURES.value, symbol, dataset, first, last, int(time.time() * 1000)),
        )

    async def _files(
        self,
        prefix: str,
        *,
        first: int | None,
        last: int | None,
        since_ms: int | None,
        step_ms: int,
    ) -> list[ArchiveFile]:
        """İndirilecek dosyalar:

        * ``since_ms`` öncesine ait dosyalar istenmez;
        * kayıtlı ilk verinin öncesi eksikse (daha geriden başlayan yeni bir istek) o dönem
          tamamlanır;
        * son kaydı dosya sonuna bir adımdan yakın olan dosya tamamlanmış sayılır.
        """
        result = []
        for item in await self.archive.list(prefix):
            if since_ms is not None and item.end_ms <= since_ms:
                continue
            if (
                last is None
                or first is None
                or item.end_ms <= first
                or item.end_ms - step_ms > last
            ):
                result.append(item)
        return result

    async def sync(self, symbol: str, *, since_ms: int | None = None) -> FuturesSyncReport:
        """Metrik ve funding arşivini artımlı eşitler. ``since_ms`` verilirse ilk eşitlemede
        bu tarihten önceki dosyalar atlanır (eğitim penceresi kadar veri yeter)."""
        symbol = symbol.upper()
        started = time.perf_counter()
        report = FuturesSyncReport(symbol=symbol)
        for dataset, prefix, parser, table, step in (
            (
                METRICS_DATASET,
                f"data/futures/um/daily/metrics/{symbol}/",
                parse_metrics,
                "futures_metrics",
                METRICS_STEP_MS,
            ),
            (
                FUNDING_DATASET,
                f"data/futures/um/monthly/fundingRate/{symbol}/",
                parse_funding,
                "funding_rates",
                FUNDING_MAX_AGE_MS,
            ),
        ):
            first, last = await self._state(symbol, dataset)
            files = await self._files(
                prefix, first=first, last=last, since_ms=since_ms, step_ms=step
            )
            for offset in range(0, len(files), self.concurrency):
                batch = files[offset : offset + self.concurrency]
                results = await asyncio.gather(
                    *(self.archive.download(f.key) for f in batch), return_exceptions=True
                )
                for item, result in zip(batch, results, strict=True):
                    if isinstance(result, BaseException):
                        raise result
                    rows: list[Any] = parser(result)
                    if not rows:
                        continue
                    inserted = await self.store.insert_rows(table, symbol, rows)
                    await self._save(symbol, dataset, rows[0][0], rows[-1][0])
                    if dataset == METRICS_DATASET:
                        report.metrics_files += 1
                        report.metrics_rows += inserted
                    else:
                        report.funding_files += 1
                        report.funding_rows += inserted
                    logger.debug("Futures verisi yazıldı", extra={"file": item.key})
        report.seconds = round(time.perf_counter() - started, 3)
        return report
