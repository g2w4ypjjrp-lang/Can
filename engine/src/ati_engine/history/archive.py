"""Binance toplu veri arşivi (data.binance.vision): listeleme, indirme, CHECKSUM doğrulama
ve mum dosyalarının ayrıştırılması.

Arşiv yalnızca herkese açık piyasa verisi içerir; API anahtarı gerekmez.

Biçim farkları (2026-11-07 itibarıyla doğrulandı):

* Spot dosyaları 2025'ten beri zaman damgalarını **mikrosaniye** verir ve başlık satırı
  içermez.
* USDⓈ-M Futures dosyaları **milisaniye** kullanır ve başlık satırıyla başlar.

Her dosya, yanındaki ``.CHECKSUM`` dosyasındaki SHA-256 ile doğrulanır; uyuşmayan dosya
asla veritabanına yazılmaz.
"""

from __future__ import annotations

import calendar
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime

import httpx

from ati_engine import __version__
from ati_engine.core.models import Market

ARCHIVE_BASE = "https://data.binance.vision"
LISTING_BASE = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"

INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}

_KEY_RE = re.compile(r"<Key>([^<]+)</Key>")
_TRUNCATED_RE = re.compile(r"<IsTruncated>(true|false)</IsTruncated>")
_PERIOD_RE = re.compile(r"-(\d{4}-\d{2}(?:-\d{2})?)\.zip$")

# (açılış zamanı ms, açılış, en yüksek, en düşük, kapanış, hacim, kapanış zamanı ms,
#  kote hacim, işlem sayısı, agresif alış hacmi, agresif alış kote hacmi)
KlineRow = tuple[int, float, float, float, float, float, int, float, int, float, float]


class ArchiveError(RuntimeError):
    pass


class ChecksumError(ArchiveError):
    pass


def market_prefix(market: Market) -> str:
    return "spot" if market is Market.SPOT else "futures/um"


def klines_prefix(market: Market, symbol: str, interval: str, granularity: str) -> str:
    if granularity not in {"monthly", "daily"}:
        raise ValueError("granularity: monthly | daily")
    if interval not in INTERVAL_MS:
        raise ValueError(f"Desteklenmeyen aralık: {interval}")
    return f"data/{market_prefix(market)}/{granularity}/klines/{symbol}/{interval}/"


@dataclass(frozen=True, order=True)
class ArchiveFile:
    start_ms: int
    end_ms: int  # hariç
    key: str
    period: str

    @property
    def monthly(self) -> bool:
        return len(self.period) == 7

    @classmethod
    def from_key(cls, key: str) -> ArchiveFile:
        match = _PERIOD_RE.search(key)
        if match is None:
            raise ArchiveError(f"Dönem çözümlenemedi: {key}")
        period = match.group(1)
        if len(period) == 7:
            year, month = (int(p) for p in period.split("-"))
            start = datetime(year, month, 1, tzinfo=UTC)
            days = calendar.monthrange(year, month)[1]
            end_ms = int(start.timestamp() * 1000) + days * 86_400_000
        else:
            start = datetime.strptime(period, "%Y-%m-%d").replace(tzinfo=UTC)
            end_ms = int(start.timestamp() * 1000) + 86_400_000
        return cls(start_ms=int(start.timestamp() * 1000), end_ms=end_ms, key=key, period=period)


def month_of(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _to_ms(raw: str) -> int:
    value = int(raw)
    # 16 haneli değer mikrosaniyedir (Spot, 2025 ve sonrası); 13 hane milisaniye.
    return value // 1000 if value >= 10**14 else value


def parse_klines(data: bytes) -> list[KlineRow]:
    """Arşivdeki zip içindeki CSV'yi ayrıştırır; zaman damgalarını milisaniyeye çevirir."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = [n for n in archive.namelist() if n.endswith(".csv")]
            if len(names) != 1:
                raise ArchiveError(f"Beklenmeyen zip içeriği: {archive.namelist()}")
            text = archive.read(names[0]).decode("ascii")
    except zipfile.BadZipFile as exc:
        raise ArchiveError(f"Bozuk zip: {exc}") from exc
    rows: list[KlineRow] = []
    for line in text.splitlines():
        if not line or not line[0].isdigit():
            continue  # boş satır veya başlık
        f = line.split(",")
        if len(f) < 11:
            raise ArchiveError(f"Eksik sütunlu satır: {line[:80]}")
        rows.append(
            (
                _to_ms(f[0]),
                float(f[1]),
                float(f[2]),
                float(f[3]),
                float(f[4]),
                float(f[5]),
                _to_ms(f[6]),
                float(f[7]),
                int(f[8]),
                float(f[9]),
                float(f[10]),
            )
        )
    return rows


class ArchiveClient:
    """data.binance.vision üzerinde listeleme ve doğrulamalı indirme."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str = ARCHIVE_BASE,
        listing_url: str = LISTING_BASE,
        timeout_s: float = 60.0,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout_s, headers={"User-Agent": f"ati-engine/{__version__}"}
        )
        self._base = base_url.rstrip("/")
        self._listing = listing_url.rstrip("/")
        self.bytes_downloaded = 0
        self.requests = 0

    async def list(self, prefix: str) -> list[ArchiveFile]:
        """Önekle eşleşen .zip dosyaları (S3 listesi; 1000'den fazlası sayfalanır)."""
        keys: list[str] = []
        marker = ""
        while True:
            params = {"delimiter": "/", "prefix": prefix}
            if marker:
                params["marker"] = marker
            response = await self._client.get(self._listing, params=params)
            self.requests += 1
            response.raise_for_status()
            page = _KEY_RE.findall(response.text)
            keys.extend(page)
            truncated = _TRUNCATED_RE.search(response.text)
            if not page or truncated is None or truncated.group(1) != "true":
                break
            marker = page[-1]
        return sorted(ArchiveFile.from_key(k) for k in keys if k.endswith(".zip"))

    async def download(self, key: str) -> bytes:
        data = await self._get(key)
        checksum = (await self._get(key + ".CHECKSUM")).decode("ascii", "replace").split()
        expected = checksum[0].lower() if checksum else ""
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise ChecksumError(f"{key}: SHA-256 uyuşmuyor (beklenen {expected}, gelen {actual})")
        return data

    async def _get(self, key: str) -> bytes:
        response = await self._client.get(f"{self._base}/{key}")
        self.requests += 1
        if response.status_code == 404:
            raise ArchiveError(f"Arşivde yok: {key}")
        response.raise_for_status()
        self.bytes_downloaded += len(response.content)
        return response.content

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
