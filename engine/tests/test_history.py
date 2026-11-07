"""Tarihsel veri: arşiv listeleme/indirme, CHECKSUM doğrulama, biçim farkları (Spot
mikrosaniye, Futures başlık satırı), artımlı eşitleme, yeniden örnekleme ve sorgu hızı."""

from __future__ import annotations

import hashlib
import io
import time
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from ati_engine.core.models import Market
from ati_engine.history.archive import (
    ArchiveClient,
    ArchiveFile,
    ChecksumError,
    klines_prefix,
    parse_klines,
)
from ati_engine.history.store import KlineStore
from ati_engine.history.sync import HistorySync
from ati_engine.storage.database import Database

LISTING = "https://listing.test/bucket"
BASE = "https://archive.test"
FUTURES_HEADER = (
    "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
    "taker_buy_volume,taker_buy_quote_volume,ignore"
)


def ms(year: int, month: int, day: int = 1) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp() * 1000)


def kline_csv(start_ms: int, count: int, *, micro: bool, header: bool, step: int = 60_000) -> str:
    unit = 1000 if micro else 1
    lines = [FUTURES_HEADER] if header else []
    for i in range(count):
        t = start_ms + i * step
        price = 100 + i * 0.01
        lines.append(
            f"{t * unit},{price:.2f},{price + 1:.2f},{price - 1:.2f},{price + 0.5:.2f},2.0,"
            f"{(t + step - 1) * unit + (unit - 1)},{price * 2:.4f},7,1.0,{price:.4f},0"
        )
    return "\n".join(lines) + "\n"


def make_zip(name: str, text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, text)
    return buffer.getvalue()


class FakeArchive:
    """data.binance.vision + S3 listesi taklidi (sayfa boyutu küçültülebilir)."""

    def __init__(self, page_size: int = 1000) -> None:
        self.files: dict[str, bytes] = {}
        self.checksums: dict[str, str] = {}
        self.page_size = page_size
        self.downloads: list[str] = []
        self.list_calls = 0

    def add(self, key: str, data: bytes, *, corrupt_checksum: bool = False) -> None:
        self.files[key] = data
        digest = hashlib.sha256(data).hexdigest()
        if corrupt_checksum:
            digest = "0" * 64
        self.checksums[key + ".CHECKSUM"] = f"{digest}  {key.rsplit('/', 1)[-1]}\n"

    def add_klines(
        self, market: Market, symbol: str, period: str, count: int, *, interval: str = "1m"
    ) -> ArchiveFile:
        granularity = "monthly" if len(period) == 7 else "daily"
        key = f"{klines_prefix(market, symbol, interval, granularity)}{symbol}-{interval}-{period}.zip"
        item = ArchiveFile.from_key(key)
        text = kline_csv(
            item.start_ms,
            count,
            micro=market is Market.SPOT,
            header=market is not Market.SPOT,
        )
        self.add(key, make_zip(f"{symbol}-{interval}-{period}.csv", text))
        return item

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(LISTING):
            self.list_calls += 1
            prefix = request.url.params.get("prefix", "")
            marker = request.url.params.get("marker", "")
            keys = sorted(k for k in self.files if k.startswith(prefix) and k > marker)
            page, truncated = keys[: self.page_size], len(keys) > self.page_size
            body = "".join(f"<Contents><Key>{k}</Key></Contents>" for k in page)
            xml = (
                '<?xml version="1.0"?><ListBucketResult>'
                f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>{body}"
                "</ListBucketResult>"
            )
            return httpx.Response(200, text=xml)
        key = url.removeprefix(BASE + "/")
        if key in self.files:
            self.downloads.append(key)
            return httpx.Response(200, content=self.files[key])
        if key in self.checksums:
            return httpx.Response(200, text=self.checksums[key])
        return httpx.Response(404)

    def client(self) -> ArchiveClient:
        transport = httpx.MockTransport(self.handler)
        return ArchiveClient(
            client=httpx.AsyncClient(transport=transport), base_url=BASE, listing_url=LISTING
        )


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(tmp_path / "engine.db")
    await database.open()
    await database.migrate()
    yield database
    await database.close()


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[KlineStore]:
    kline_store = KlineStore(tmp_path / "market" / "history.duckdb")
    yield kline_store
    await kline_store.close()


# --- Ayrıştırma ----------------------------------------------------------------------


def test_spot_microseconds_are_normalized() -> None:
    start = ms(2026, 11, 5)
    rows = parse_klines(make_zip("a.csv", kline_csv(start, 3, micro=True, header=False)))
    assert [r[0] for r in rows] == [start, start + 60_000, start + 120_000]
    assert rows[0][6] == start + 59_999  # kapanış zamanı da milisaniyeye indirildi
    assert rows[0][8] == 7


def test_futures_header_is_skipped() -> None:
    start = ms(2026, 11, 5)
    rows = parse_klines(make_zip("a.csv", kline_csv(start, 2, micro=False, header=True)))
    assert len(rows) == 2
    assert rows[0][0] == start


def test_real_archive_line_formats() -> None:
    # data.binance.vision'dan 2026-11-05 için alınan gerçek satırlar.
    spot = (
        "1793836800000000,80504.01000000,80584.01000000,80483.99000000,80580.89000000,"
        "23.13316000,1793836859999999,1862328.89106290,3841,9.65715000,777499.73735090,0\n"
    )
    futures = (
        FUTURES_HEADER + "\n1793836800000,80466.40,80556.10,80441.70,80538.00,98.049,"
        "1793836859999,7892886.29630,2785,60.139,4841173.47870,0\n"
    )
    s = parse_klines(make_zip("s.csv", spot))[0]
    f = parse_klines(make_zip("f.csv", futures))[0]
    assert s[0] == f[0] == 1793836800000
    assert s[6] == f[6] == 1793836859999
    assert s[4] == pytest.approx(80580.89)
    assert f[8] == 2785


def test_archive_file_periods() -> None:
    month = ArchiveFile.from_key("data/spot/monthly/klines/X/1m/X-1m-2024-02.zip")
    assert month.monthly and month.end_ms - month.start_ms == 29 * 86_400_000  # artık yıl
    day = ArchiveFile.from_key("data/spot/daily/klines/X/1m/X-1m-2026-11-05.zip")
    assert not day.monthly and day.start_ms == ms(2026, 11, 5)


# --- İndirme ve doğrulama ------------------------------------------------------------


async def test_checksum_mismatch_is_rejected(db: Database, store: KlineStore) -> None:
    fake = FakeArchive()
    item = fake.add_klines(Market.SPOT, "BTCUSDT", "2026-11-01", 10)
    fake.add(item.key, fake.files[item.key], corrupt_checksum=True)
    archive = fake.client()
    with pytest.raises(ChecksumError):
        await archive.download(item.key)
    sync = HistorySync(archive, store, db, today=lambda: date(2026, 11, 2))
    with pytest.raises(ChecksumError):
        await sync.sync_klines(Market.SPOT, "BTCUSDT")
    # Doğrulanmayan dosya yazılmadı, eşitleme durumu ilerlemedi.
    assert (await store.coverage("spot", "BTCUSDT", "1m")).rows == 0
    assert await sync.state(Market.SPOT, "BTCUSDT", "1m") == (None, None)
    await archive.close()


async def test_listing_is_paginated() -> None:
    fake = FakeArchive(page_size=2)
    for day in range(1, 6):
        fake.add_klines(Market.SPOT, "NEWUSDT", f"2026-11-{day:02d}", 1)
    archive = fake.client()
    files = await archive.list(klines_prefix(Market.SPOT, "NEWUSDT", "1m", "daily"))
    assert [f.period for f in files] == [f"2026-11-{d:02d}" for d in range(1, 6)]
    assert fake.list_calls == 3
    await archive.close()


# --- Artımlı eşitleme ------------------------------------------------------------------


async def test_full_history_then_incremental(db: Database, store: KlineStore) -> None:
    fake = FakeArchive()
    # Listelenme Eylül 2026: iki tamamlanmış ay aylık dosya, Kasım günlük dosyalar.
    fake.add_klines(Market.SPOT, "BTCUSDT", "2026-09", 30 * 1440)
    fake.add_klines(Market.SPOT, "BTCUSDT", "2026-10", 31 * 1440)
    for day in range(1, 5):
        fake.add_klines(Market.SPOT, "BTCUSDT", f"2026-11-{day:02d}", 1440)
    # Ekim'in günlük dosyaları da arşivde durur ama aylık dosya varken kullanılmamalı.
    fake.add_klines(Market.SPOT, "BTCUSDT", "2026-10-31", 1440)
    archive = fake.client()
    today = [date(2026, 11, 5)]
    sync = HistorySync(archive, store, db, today=lambda: today[0])

    first = await sync.sync_klines(Market.SPOT, "BTCUSDT")
    assert first.files_downloaded == 6
    assert first.rows_inserted == (30 + 31 + 4) * 1440
    assert first.first_open_ms == ms(2026, 9, 1)
    assert first.last_open_ms == ms(2026, 11, 5) - 60_000
    coverage = await store.coverage("spot", "BTCUSDT", "1m")
    assert coverage.rows == first.rows_inserted
    assert coverage.missing == 0  # listelenmeden bugüne boşluksuz
    assert not any("2026-10-31" in key for key in fake.downloads)

    # İkinci çalıştırma: yeni dosya yok → hiçbir şey indirilmez.
    fake.downloads.clear()
    second = await sync.sync_klines(Market.SPOT, "BTCUSDT")
    assert second.files_downloaded == 0
    assert second.files_skipped == 6
    assert fake.downloads == []

    # Ertesi gün yalnızca yeni günün dosyası indirilir.
    fake.add_klines(Market.SPOT, "BTCUSDT", "2026-11-05", 1440)
    today[0] = date(2026, 11, 6)
    third = await sync.sync_klines(Market.SPOT, "BTCUSDT")
    assert third.downloaded == ["2026-11-05"]
    assert third.rows_inserted == 1440
    await archive.close()


async def test_month_rollover_does_not_duplicate(db: Database, store: KlineStore) -> None:
    """Ay bittikten sonra aylık dosya yayınlanır; günlüklerle zaten alınan günler tekrar
    yazılmaz, eksik kalan günler aylık dosyadan tamamlanır."""
    fake = FakeArchive()
    for day in range(1, 31):
        fake.add_klines(Market.USDM_FUTURES, "ETHUSDT", f"2026-11-{day:02d}", 1440)
    archive = fake.client()
    sync = HistorySync(archive, store, db, today=lambda: date(2026, 11, 20))
    report = await sync.sync_klines(Market.USDM_FUTURES, "ETHUSDT")
    assert report.files_downloaded == 30  # henüz aylık dosya yok, bu ay listelenmiş sembol
    fake.add_klines(Market.USDM_FUTURES, "ETHUSDT", "2026-11", 30 * 1440)
    fake.add_klines(Market.USDM_FUTURES, "ETHUSDT", "2026-12-01", 1440)
    sync = HistorySync(archive, store, db, today=lambda: date(2026, 12, 2))
    report = await sync.sync_klines(Market.USDM_FUTURES, "ETHUSDT")
    assert report.downloaded == ["2026-12-01"]  # aylık Kasım dosyası atlandı
    coverage = await store.coverage("usdm_futures", "ETHUSDT", "1m")
    assert coverage.rows == 31 * 1440
    assert coverage.missing == 0
    await archive.close()


async def test_interrupted_sync_resumes_without_duplicates(db: Database, store: KlineStore) -> None:
    fake = FakeArchive()
    for day in range(1, 4):
        fake.add_klines(Market.SPOT, "SOLUSDT", f"2026-11-{day:02d}", 1440)
    broken = fake.add_klines(Market.SPOT, "SOLUSDT", "2026-11-04", 1440)
    good = fake.files[broken.key]
    fake.add(broken.key, good, corrupt_checksum=True)
    archive = fake.client()
    sync = HistorySync(archive, store, db, today=lambda: date(2026, 11, 5))
    with pytest.raises(ChecksumError):
        await sync.sync_klines(Market.SPOT, "SOLUSDT")
    assert (await store.coverage("spot", "SOLUSDT", "1m")).rows == 3 * 1440
    fake.add(broken.key, good)  # sunucu düzeltildi
    fake.downloads.clear()
    report = await sync.sync_klines(Market.SPOT, "SOLUSDT")
    assert report.downloaded == ["2026-11-04"]
    assert (await store.coverage("spot", "SOLUSDT", "1m")).rows == 4 * 1440
    await archive.close()


# --- Sorgular --------------------------------------------------------------------------


async def test_resample_and_range_query(store: KlineStore) -> None:
    start = ms(2026, 11, 1)
    rows = parse_klines(make_zip("a.csv", kline_csv(start, 480, micro=False, header=False)))
    assert await store.insert("spot", "BTCUSDT", "1m", rows) == 480
    assert await store.insert("spot", "BTCUSDT", "1m", rows) == 0  # tekrar yazılmaz
    bars = await store.resample("spot", "BTCUSDT", source_interval="1m", target_ms=4 * 3_600_000)
    assert len(bars) == 2
    bucket, open_, high, low, close, volume, *_ = bars[0]
    assert bucket == start
    assert open_ == pytest.approx(rows[0][1])
    assert close == pytest.approx(rows[239][4])
    assert high == pytest.approx(max(r[2] for r in rows[:240]))
    assert low == pytest.approx(min(r[3] for r in rows[:240]))
    assert volume == pytest.approx(240 * 2.0)
    window = await store.candles(
        "spot", "BTCUSDT", "1m", start_ms=start + 60_000, end_ms=start + 180_000
    )
    assert [c[0] for c in window] == [start + 60_000, start + 120_000]


async def test_query_performance_one_year_of_minutes(store: KlineStore) -> None:
    """Bir yıllık 1 dakikalık mum (525.600 satır): yükleme ve sorgular hızlı olmalı."""
    start = ms(2025, 1, 1)
    rows = parse_klines(make_zip("y.csv", kline_csv(start, 365 * 1440, micro=False, header=False)))
    t0 = time.perf_counter()
    assert await store.insert("spot", "BTCUSDT", "1m", rows) == len(rows)
    load_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    month = await store.candles(
        "spot", "BTCUSDT", "1m", start_ms=ms(2025, 6, 1), end_ms=ms(2025, 7, 1)
    )
    month_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    daily = await store.resample("spot", "BTCUSDT", source_interval="1m", target_ms=86_400_000)
    resample_s = time.perf_counter() - t0
    assert len(month) == 30 * 1440
    assert len(daily) == 365
    # Sınırlar yavaş CI makineleri için geniş tutuldu; tipik değerler çok daha düşüktür.
    assert load_s < 20
    assert month_s < 2
    assert resample_s < 2


# --- REST ile baş/kuyruk tamamlama ---------------------------------------------------------


class FakeKlinesRest:
    """Binance ``klines`` uç noktası taklidi: listelenmeden ``now``a kadar 1 dakikalık mumlar;
    son (henüz kapanmamış) mum da döner — eşitleme onu yazmamalı."""

    def __init__(self, listing_ms: int, now_ms: int) -> None:
        self.listing_ms = listing_ms
        self.now_ms = now_ms
        self.requests: list[dict[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.requests.append(params)
        start = max(int(params.get("startTime", 0)), self.listing_ms)
        end = int(params.get("endTime", self.now_ms))
        limit = int(params.get("limit", 500))
        first = start + (-start % 60_000)
        rows = []
        t = first
        while t <= min(end, self.now_ms) and len(rows) < limit:
            rows.append(
                [
                    t,
                    "100.0",
                    "101.0",
                    "99.0",
                    "100.5",
                    "2.0",
                    t + 59_999,
                    "200.0",
                    7,
                    "1.0",
                    "100.0",
                    "0",
                ]
            )
            t += 60_000
        return httpx.Response(200, json=rows)


def rest_source(fake: FakeKlinesRest, market: Market = Market.SPOT) -> tuple[Any, Any]:
    from ati_engine.config import BinanceEndpoints
    from ati_engine.exchange.endpoints import endpoints_for
    from ati_engine.exchange.rate_limit import WeightBudget
    from ati_engine.exchange.rest import BinanceRestClient

    endpoints = endpoints_for(market, BinanceEndpoints())
    client = BinanceRestClient(
        endpoints.rest_base,
        budget=WeightBudget(6000),
        client=httpx.AsyncClient(
            base_url=endpoints.rest_base, transport=httpx.MockTransport(fake.handler)
        ),
    )
    return client, endpoints


async def test_rest_fills_pre_archive_head_and_today_tail(db: Database, store: KlineStore) -> None:
    listing = ms(2026, 10, 30)
    now = [ms(2026, 11, 4) + 6 * 3_600_000 + 30 * 60_000 + 30_000]  # 06:30:30
    archive_fake = FakeArchive()
    for day in range(31, 32):
        archive_fake.add_klines(Market.SPOT, "NEWUSDT", f"2026-10-{day}", 1440)
    for day in range(1, 4):
        archive_fake.add_klines(Market.SPOT, "NEWUSDT", f"2026-11-{day:02d}", 1440)
    rest = FakeKlinesRest(listing, now[0])
    client, endpoints = rest_source(rest)
    archive = archive_fake.client()
    sync = HistorySync(
        archive,
        store,
        db,
        today=lambda: date(2026, 11, 4),
        rest={Market.SPOT: (client, endpoints)},
        now_ms=lambda: now[0],
    )
    report = await sync.sync_klines(Market.SPOT, "NEWUSDT")
    assert report.files_downloaded == 4
    # Baş: 30 Ekim (arşivde yok) 1440 mum; kuyruk: bugün 00:00-06:29 (06:30 henüz açık).
    assert report.rest_rows == 1440 + 390
    assert report.first_open_ms == listing
    assert report.last_open_ms == ms(2026, 11, 4) + 389 * 60_000
    coverage = await store.coverage("spot", "NEWUSDT", "1m")
    assert coverage.rows == 1440 * 5 + 390
    assert coverage.missing == 0
    assert all(int(r["limit"]) == 1000 for r in rest.requests)

    # Beş dakika sonra: baş tekrar istenmez, yalnızca yeni kapanan 5 mum eklenir.
    rest.requests.clear()
    now[0] += 5 * 60_000
    rest.now_ms = now[0]
    again = await sync.sync_klines(Market.SPOT, "NEWUSDT")
    assert again.files_downloaded == 0
    assert again.rest_rows == 5
    assert len(rest.requests) == 1
    assert int(rest.requests[0]["startTime"]) == ms(2026, 11, 4) + 390 * 60_000
    await archive.close()
    await client.close()


async def test_daily_files_before_first_monthly_are_included(
    db: Database, store: KlineStore
) -> None:
    """ETHUSDT vadeli gibi: arşivin ilk günü (31 Aralık) yalnızca günlük dosya olarak var."""
    fake = FakeArchive()
    fake.add_klines(Market.USDM_FUTURES, "ETHUSDT", "2019-12-31", 1440)
    fake.add_klines(Market.USDM_FUTURES, "ETHUSDT", "2020-01", 31 * 1440)
    fake.add_klines(Market.USDM_FUTURES, "ETHUSDT", "2020-01-15", 1440)  # aylıkla örtüşen
    archive = fake.client()
    sync = HistorySync(archive, store, db, today=lambda: date(2020, 2, 1))
    report = await sync.sync_klines(Market.USDM_FUTURES, "ETHUSDT")
    assert report.downloaded == ["2019-12-31", "2020-01"]
    assert report.first_open_ms == ms(2019, 12, 31)
    assert (await store.coverage("usdm_futures", "ETHUSDT", "1m")).missing == 0
    await archive.close()


async def test_archive_gap_is_repaired_from_rest(db: Database, store: KlineStore) -> None:
    """Arşivde eksik gün (Binance'te gerçekten görüldü): REST'ten tamamlanır; ikinci
    eşitlemede aynı boşluk (artık yok) tekrar sorulmaz."""
    fake = FakeArchive()
    for day in (1, 2, 4):  # 3 Kasım arşivde yok
        fake.add_klines(Market.SPOT, "GAPUSDT", f"2026-11-{day:02d}", 1440)
    now = ms(2026, 11, 5)
    rest = FakeKlinesRest(ms(2026, 11, 1), now)
    client, endpoints = rest_source(rest)
    archive = fake.client()
    sync = HistorySync(
        archive,
        store,
        db,
        today=lambda: date(2026, 11, 5),
        rest={Market.SPOT: (client, endpoints)},
        now_ms=lambda: now,
    )
    report = await sync.sync_klines(Market.SPOT, "GAPUSDT")
    assert report.gaps_checked == 1
    assert report.gaps_rows == 1440
    coverage = await store.coverage("spot", "GAPUSDT", "1m")
    assert coverage.missing == 0 and coverage.rows == 4 * 1440
    rest.requests.clear()
    again = await sync.sync_klines(Market.SPOT, "GAPUSDT")
    assert again.gaps_checked == 0
    assert rest.requests == []  # boşluk kalmadı, veri de güncel: hiç istek yok
    await archive.close()
    await client.close()
