"""Tarihsel mum deposu (DuckDB, sütun tabanlı ve sıkıştırılmış).

Ana SQLite veritabanından ayrı bir dosyadır (``market/history.duckdb``): yüz milyonlarca
satırlık analitik sorgular işlem motorunun veritabanını yavaşlatmaz. Fiyatlar analiz
amaçlı ``DOUBLE`` saklanır; para hesapları bu depodan yapılmaz.

DuckDB bağlantısı iş parçacığı güvenli olmadığından tüm çağrılar tek bir işçi iş parçacığında
sırayla yürütülür.
"""

from __future__ import annotations

import asyncio
import csv
import os
import tempfile
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import duckdb

from ati_engine.history.archive import INTERVAL_MS, KlineRow

T = TypeVar("T")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS klines (
    market          VARCHAR NOT NULL,
    symbol          VARCHAR NOT NULL,
    interval        VARCHAR NOT NULL,
    open_time       BIGINT  NOT NULL,
    open            DOUBLE  NOT NULL,
    high            DOUBLE  NOT NULL,
    low             DOUBLE  NOT NULL,
    close           DOUBLE  NOT NULL,
    volume          DOUBLE  NOT NULL,
    close_time      BIGINT  NOT NULL,
    quote_volume    DOUBLE  NOT NULL,
    trades          BIGINT  NOT NULL,
    taker_buy_base  DOUBLE  NOT NULL,
    taker_buy_quote DOUBLE  NOT NULL,
    PRIMARY KEY (market, symbol, interval, open_time)
)
"""

_COLUMNS = (
    "open_time, open, high, low, close, volume, close_time, quote_volume, trades, "
    "taker_buy_base, taker_buy_quote"
)


@dataclass(frozen=True)
class Coverage:
    rows: int
    first_open_ms: int | None
    last_open_ms: int | None
    missing: int  # ilk ve son mum arasında beklenen ama bulunmayan mum sayısı


class KlineStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(path) if path is not None else ":memory:")
        self._con.execute(_SCHEMA)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="history-db")
        self._tmp_dir = path.parent if path is not None else Path(tempfile.gettempdir())

    async def _run(self, fn: Callable[[], T]) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, fn)

    # --- Yazma -------------------------------------------------------------------------

    def _insert_sync(
        self, market: str, symbol: str, interval: str, rows: Sequence[KlineRow]
    ) -> int:
        if not rows:
            return 0
        # Toplu yükleme: satır satır INSERT yerine geçici CSV + read_csv (çok daha hızlı).
        fd, name = tempfile.mkstemp(suffix=".csv", dir=self._tmp_dir)
        try:
            with os.fdopen(fd, "w", newline="", encoding="ascii") as handle:
                csv.writer(handle).writerows(rows)
            before = self._count_sync(market, symbol, interval)
            self._con.execute(
                f"""
                INSERT OR IGNORE INTO klines
                SELECT ?, ?, ?, {_COLUMNS}
                FROM read_csv(?, header = false, columns = {{
                    'open_time': 'BIGINT', 'open': 'DOUBLE', 'high': 'DOUBLE',
                    'low': 'DOUBLE', 'close': 'DOUBLE', 'volume': 'DOUBLE',
                    'close_time': 'BIGINT', 'quote_volume': 'DOUBLE', 'trades': 'BIGINT',
                    'taker_buy_base': 'DOUBLE', 'taker_buy_quote': 'DOUBLE'
                }})
                """,  # noqa: S608 - sütun listesi sabittir, değerler parametredir
                [market, symbol, interval, name],
            )
            return self._count_sync(market, symbol, interval) - before
        finally:
            Path(name).unlink(missing_ok=True)

    async def insert(
        self, market: str, symbol: str, interval: str, rows: Sequence[KlineRow]
    ) -> int:
        """Satırları ekler (aynı mum varsa yok sayılır); eklenen satır sayısını döndürür."""
        return await self._run(lambda: self._insert_sync(market, symbol, interval, rows))

    # --- Okuma -------------------------------------------------------------------------

    def _count_sync(self, market: str, symbol: str, interval: str) -> int:
        row = self._con.execute(
            "SELECT count(*) FROM klines WHERE market = ? AND symbol = ? AND interval = ?",
            [market, symbol, interval],
        ).fetchone()
        return int(row[0]) if row else 0

    async def coverage(self, market: str, symbol: str, interval: str) -> Coverage:
        def run() -> Coverage:
            row = self._con.execute(
                "SELECT count(*), min(open_time), max(open_time) FROM klines "
                "WHERE market = ? AND symbol = ? AND interval = ?",
                [market, symbol, interval],
            ).fetchone()
            if row is None:
                return Coverage(rows=0, first_open_ms=None, last_open_ms=None, missing=0)
            count, first, last = int(row[0]), row[1], row[2]
            missing = 0
            if count:
                expected = (int(last) - int(first)) // INTERVAL_MS[interval] + 1
                missing = expected - count
            return Coverage(rows=count, first_open_ms=first, last_open_ms=last, missing=missing)

        return await self._run(run)

    async def gaps(
        self, market: str, symbol: str, interval: str, *, since_ms: int = 0, limit: int = 1000
    ) -> list[tuple[int, int]]:
        """Veri içindeki boşluklar: (boşluktan önceki son mum, boşluktan sonraki ilk mum)."""
        step = INTERVAL_MS[interval]

        def run() -> list[tuple[int, int]]:
            rows = self._con.execute(
                """
                SELECT open_time, nxt FROM (
                    SELECT open_time, lead(open_time) OVER (ORDER BY open_time) AS nxt
                    FROM klines WHERE market = ? AND symbol = ? AND interval = ?
                      AND open_time >= ?
                ) WHERE nxt - open_time > ? ORDER BY open_time LIMIT ?
                """,
                [market, symbol, interval, since_ms, step, limit],
            ).fetchall()
            return [(int(a), int(b)) for a, b in rows]

        return await self._run(run)

    async def candles(
        self,
        market: str,
        symbol: str,
        interval: str,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int | None = None,
        tail: int | None = None,
    ) -> list[tuple[Any, ...]]:
        """[start_ms, end_ms) aralığındaki mumlar, zamana göre artan. ``tail`` verilirse
        aralıktaki son ``tail`` mum döner."""

        def run() -> list[tuple[Any, ...]]:
            sql = f"SELECT {_COLUMNS} FROM klines WHERE market = ? AND symbol = ? AND interval = ?"  # noqa: S608
            params: list[Any] = [market, symbol, interval]
            if start_ms is not None:
                sql += " AND open_time >= ?"
                params.append(start_ms)
            if end_ms is not None:
                sql += " AND open_time < ?"
                params.append(end_ms)
            if tail is not None:
                sql += " ORDER BY open_time DESC LIMIT ?"
                params.append(tail)
                return list(reversed(self._con.execute(sql, params).fetchall()))
            sql += " ORDER BY open_time"
            if limit is not None:
                sql += " LIMIT ?"
                params.append(limit)
            return self._con.execute(sql, params).fetchall()

        return await self._run(run)

    async def resample(
        self,
        market: str,
        symbol: str,
        *,
        source_interval: str,
        target_ms: int,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[tuple[Any, ...]]:
        """Küçük aralıklı mumlardan büyük aralık üretir (ör. 1m → 4h): açılış, en yüksek,
        en düşük, kapanış, hacim, kote hacim, işlem sayısı, agresif alış kote hacmi."""
        if target_ms % INTERVAL_MS[source_interval]:
            raise ValueError("Hedef aralık kaynak aralığın katı olmalı")

        def run() -> list[tuple[Any, ...]]:
            sql = """
                SELECT open_time - open_time % ? AS bucket,
                       arg_min(open, open_time), max(high), min(low), arg_max(close, open_time),
                       sum(volume), sum(quote_volume), sum(trades), sum(taker_buy_quote)
                FROM klines WHERE market = ? AND symbol = ? AND interval = ?
            """
            params: list[Any] = [target_ms, market, symbol, source_interval]
            if start_ms is not None:
                sql += " AND open_time >= ?"
                params.append(start_ms)
            if end_ms is not None:
                sql += " AND open_time < ?"
                params.append(end_ms)
            sql += " GROUP BY bucket ORDER BY bucket"
            return self._con.execute(sql, params).fetchall()

        return await self._run(run)

    async def symbols(self) -> list[tuple[str, str, str, int]]:
        def run() -> list[tuple[str, str, str, int]]:
            rows = self._con.execute(
                "SELECT market, symbol, interval, count(*) FROM klines "
                "GROUP BY ALL ORDER BY market, symbol, interval"
            ).fetchall()
            return [(str(a), str(b), str(c), int(d)) for a, b, c, d in rows]

        return await self._run(run)

    async def close(self) -> None:
        await self._run(self._con.close)
        self._executor.shutdown(wait=True)
