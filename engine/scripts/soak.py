"""Aşama 18: motor dayanıklılık (soak) testi.

Gerçek motor; piyasa verisi sahte Binance yayınından (hızlandırılmış), test ağı işlemleri sahte
borsadan, lisans sahte lisans sunucusundan gelir (masaüstü uçtan uca arka ucuyla aynı düzen; hiçbir
gerçek adrese bağlanılmaz). Süre boyunca yerel API sürekli sorgulanır ve olay akışı (WebSocket)
dinlenir; düzenli aralıklarla ölçülür:

* bellek (RSS) ve Python yığını, çalışan asyncio görev sayısı, açık dosya sayısı (Linux),
* olay döngüsü gecikmesi (zamanlanmış uykunun ne kadar geciktiği),
* veritabanı dosyası boyutu, API hata sayısı.

Sonunda acil durdurmanın tepki süresi ölçülür ve şu koşullar denetlenir: API hatası yok, motor
sağlıklı, ısınmadan sonra bellek ve görev sayısı sınırlı büyümüş, olay döngüsü takılmamış. Rapor
JSON olarak da yazılabilir.

    uv run python scripts/soak.py --minutes 3          # CI
    uv run python scripts/soak.py --hours 24 --json soak.json   # Windows bilgisayarda tam test
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import statistics
import sys
import tempfile
import time
import tracemalloc
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))  # sahte sunucular (fake_binance, fake_exchange, ...)

from ati_engine.app import TOKEN_ENV, Engine  # noqa: E402
from ati_engine.config import (  # noqa: E402
    BinanceEndpoints,
    EngineSettings,
    HistorySettings,
    LicenseSettings,
    LocalApiSettings,
    MarketDataSettings,
)
from fake_binance import FakeBinance  # noqa: E402
from fake_exchange import FakeExchange  # noqa: E402
from fake_license import FakeLicenseServer  # noqa: E402

TOKEN = "soak-belirtec-0123456789abcdef"  # noqa: S105 - yalnızca test
POLLED = [
    "/v1/status", "/v1/market/status", "/v1/market/tickers", "/v1/scanner/top",
    "/v1/scanner/signals", "/v1/whales/summary", "/v1/whales/alerts", "/v1/opportunities",
    "/v1/paper/leaderboard", "/v1/paper/positions", "/v1/audit", "/v1/license",
]  # fmt: skip


def rss_bytes() -> int | None:
    """Süreç bellek kullanımı (yerleşik). Linux /proc, Windows psapi; yoksa None."""
    with contextlib.suppress(OSError, ValueError):
        if sys.platform.startswith("linux"):
            pages = int(Path("/proc/self/statm").read_text().split()[1])
            return pages * os.sysconf("SC_PAGE_SIZE")
    if sys.platform == "win32":  # pragma: no cover - Windows'ta çalışır
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]  # fmt: skip

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        handle = ctypes.windll.kernel32.GetCurrentProcess()  # type: ignore[attr-defined]
        if ctypes.windll.psapi.GetProcessMemoryInfo(  # type: ignore[attr-defined]
            handle, ctypes.byref(counters), counters.cb
        ):
            return int(counters.WorkingSetSize)
    return None


def open_files() -> int | None:
    with contextlib.suppress(OSError):
        return len(os.listdir("/proc/self/fd"))
    return None


def median(values: list[float]) -> float:
    return statistics.median(values) if values else float("nan")


class Soak:
    def __init__(self, seconds: float, sample_s: float, data_dir: Path) -> None:
        self.seconds = seconds
        self.sample_s = sample_s
        self.data_dir = data_dir
        self.samples: list[dict[str, Any]] = []
        self.requests = 0
        self.errors: dict[str, int] = {}
        self.events = 0
        self.lags_ms: list[float] = []
        self.stop = asyncio.Event()

    async def poll(self, base: str) -> None:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        async with httpx.AsyncClient(base_url=base, headers=headers, timeout=10) as http:
            i = 0
            while not self.stop.is_set():
                path = POLLED[i % len(POLLED)]
                i += 1
                try:
                    response = await http.get(path)
                    self.requests += 1
                    if response.status_code >= 500 or response.status_code in (401, 403):
                        key = f"{path} {response.status_code}"
                        self.errors[key] = self.errors.get(key, 0) + 1
                except httpx.HTTPError as exc:
                    key = f"{path} {type(exc).__name__}"
                    self.errors[key] = self.errors.get(key, 0) + 1
                await asyncio.sleep(0.05)

    async def listen(self, ws_url: str, origin: str) -> None:
        while not self.stop.is_set():
            try:
                async with websockets.connect(ws_url, origin=origin) as ws:  # type: ignore[arg-type]
                    await ws.send(json.dumps({"type": "auth", "token": TOKEN}))
                    while not self.stop.is_set():
                        with contextlib.suppress(TimeoutError):
                            await asyncio.wait_for(ws.recv(), timeout=1)
                            self.events += 1
            except (OSError, websockets.WebSocketException):
                await asyncio.sleep(1)

    async def loop_lag(self) -> None:
        while not self.stop.is_set():
            start = time.perf_counter()
            await asyncio.sleep(0.1)
            self.lags_ms.append(max(0.0, (time.perf_counter() - start - 0.1) * 1000))

    def sample(self, started: float) -> None:
        current, _peak = tracemalloc.get_traced_memory()
        db = self.data_dir / "engine.db"
        self.samples.append(
            {
                "t_s": round(time.monotonic() - started, 1),
                "rss_mb": round((rss_bytes() or 0) / 2**20, 1),
                "py_heap_mb": round(current / 2**20, 1),
                "tasks": len(asyncio.all_tasks()),
                "open_files": open_files(),
                "db_mb": round(db.stat().st_size / 2**20, 2) if db.exists() else 0,
                "requests": self.requests,
                "events": self.events,
                "lag_p99_ms": round(sorted(self.lags_ms)[int(len(self.lags_ms) * 0.99)], 1)
                if self.lags_ms
                else 0,
            }
        )
        self.lags_ms.clear()


async def kill_switch_latency(base: str) -> float:
    async with httpx.AsyncClient(
        base_url=base, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=10
    ) as http:
        start = time.perf_counter()
        engaged = await http.post("/v1/kill-switch/engage", json={"reason": "dayanıklılık testi"})
        elapsed = (time.perf_counter() - start) * 1000
        if engaged.status_code != 200 or not engaged.json()["kill_switch"]["engaged"]:
            raise RuntimeError(f"Acil durdurma devreye girmedi: {engaged.text}")
        released = await http.post(
            "/v1/kill-switch/release", json={"confirmation": "SERBEST BIRAK"}
        )
        if released.status_code != 200:
            raise RuntimeError(f"Acil durdurma kaldırılamadı: {released.text}")
        return elapsed


def evaluate(soak: Soak, healthy: bool, kill_ms: float, args: argparse.Namespace) -> dict[str, Any]:
    samples = soak.samples
    warm = max(1, len(samples) // 5)
    early, late = samples[warm : warm * 2] or samples[:1], samples[-warm:]

    def growth(key: str) -> float:
        before = median([s[key] for s in early])
        after = median([s[key] for s in late])
        return (after - before) / before * 100 if before else 0.0

    checks = {
        "API hatası yok": not soak.errors,
        "motor sağlıklı": healthy,
        f"RSS büyümesi ≤ %{args.max_rss_growth:.0f}": growth("rss_mb") <= args.max_rss_growth,
        f"Python yığını büyümesi ≤ %{args.max_rss_growth:.0f}": growth("py_heap_mb")
        <= args.max_rss_growth,
        "görev sayısı sabit (≤ +10)": median([s["tasks"] for s in late])
        <= median([s["tasks"] for s in early]) + 10,
        f"olay döngüsü gecikmesi p99 ≤ {args.max_lag_ms:.0f} ms": max(
            s["lag_p99_ms"] for s in samples
        )
        <= args.max_lag_ms,
        "olay akışı sürdü": samples[-1]["events"] > samples[warm]["events"],
        "acil durdurma ≤ 500 ms": kill_ms <= 500,
    }
    return {
        "sure_s": samples[-1]["t_s"],
        "istek": soak.requests,
        "olay": soak.events,
        "api_hatalari": soak.errors,
        "rss_buyume_yuzde": round(growth("rss_mb"), 1),
        "yigin_buyume_yuzde": round(growth("py_heap_mb"), 1),
        "acil_durdurma_ms": round(kill_ms, 1),
        "denetimler": checks,
        "basarili": all(checks.values()),
        "ornekler": samples,
    }


async def run(args: argparse.Namespace) -> int:
    tracemalloc.start()
    os.environ[TOKEN_ENV] = TOKEN
    origin = "http://127.0.0.1:4173"
    market = await FakeBinance(interval_s=args.tick_s).start()
    exchange = await FakeExchange(
        api_key="SoakAnahtar0123456789abcdef",
        secret="SoakGizli0123456789abcdefXYZ",  # noqa: S106 - sahte borsa (yalnızca test)
    ).start()
    exchange.prices.update({"BTCUSDT": Decimal(100), "ETHUSDT": Decimal(50)})
    licensing = await FakeLicenseServer().start()
    seconds = args.hours * 3600 + args.minutes * 60
    with tempfile.TemporaryDirectory(prefix="ati-soak-") as tmp:
        data_dir = Path(tmp) / "data"
        settings = EngineSettings(
            data_dir=data_dir,
            log_to_console=False,
            api=LocalApiSettings(port=0, allowed_origins=[origin]),
            binance=BinanceEndpoints(
                **market.binance_endpoints(),
                futures_testnet_rest=exchange.rest_url,
                futures_testnet_ws_private=exchange.private_ws_url,
                spot_testnet_rest=exchange.rest_url,
                spot_testnet_ws_api=exchange.ws_api_url,
            ),
            market_data=MarketDataSettings(
                enabled=True,
                symbol_allowlist=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
                focus_symbols=["BTCUSDT"],
                depth_snapshot_limit=100,
            ),
            history=HistorySettings(enabled=False),
            license=LicenseSettings(
                server_url=licensing.url,
                trusted_keys={licensing.kid: licensing.public_key},
                fingerprint_override="soak-bilgisayar",
            ),
        )
        engine = Engine(settings)
        task = asyncio.create_task(engine.run())
        await asyncio.wait_for(engine.ready.wait(), timeout=60)
        base = f"http://127.0.0.1:{engine.bound_port}"
        soak = Soak(seconds, args.sample_s, data_dir)
        workers = [
            asyncio.create_task(soak.poll(base)),
            asyncio.create_task(
                soak.listen(f"ws://127.0.0.1:{engine.bound_port}/v1/events", origin)
            ),
            asyncio.create_task(soak.loop_lag()),
        ]
        started = time.monotonic()
        print(f"Dayanıklılık testi: {seconds / 60:.0f} dk, örnek aralığı {args.sample_s:.0f} sn")
        while time.monotonic() - started < seconds and not task.done():
            await asyncio.sleep(args.sample_s)
            soak.sample(started)
            last = soak.samples[-1]
            print(
                f"  {last['t_s']:>7.0f} sn  RSS {last['rss_mb']:>6} MB  "
                f"yığın {last['py_heap_mb']:>5} MB  "
                f"görev {last['tasks']:>3}  gecikme p99 {last['lag_p99_ms']:>6} ms  "
                f"istek {last['requests']:>6}  olay {last['events']:>6}",
                flush=True,
            )
        healthy = not task.done()
        async with httpx.AsyncClient(
            base_url=base, headers={"Authorization": f"Bearer {TOKEN}"}
        ) as http:
            status = (await http.get("/v1/status")).json()
        healthy &= status.get("engine_state") in ("running", "degraded", "starting")
        kill_ms = await kill_switch_latency(base)
        soak.stop.set()
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        if engine.runtime is not None:
            engine.runtime.request_shutdown()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(task, timeout=30)
        report = evaluate(soak, healthy, kill_ms, args)
    await exchange.stop()
    await market.stop()
    await licensing.stop()
    print("\nDenetimler:")
    for name, ok in report["denetimler"].items():
        print(f"  {'✓' if ok else '✗'} {name}")
    print(
        f"İstek {report['istek']}, olay {report['olay']}, "
        f"RSS büyümesi %{report['rss_buyume_yuzde']}, "
        f"yığın büyümesi %{report['yigin_buyume_yuzde']}, "
        f"acil durdurma {report['acil_durdurma_ms']} ms"
    )
    if report["api_hatalari"]:
        print("API hataları:", report["api_hatalari"])
    if args.json:
        Path(args.json).write_text(  # noqa: ASYNC240 - test sonu, tek yazım
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print("Sonuç:", "BAŞARILI" if report["basarili"] else "BAŞARISIZ")
    return 0 if report["basarili"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Motor dayanıklılık testi")
    parser.add_argument("--hours", type=float, default=0)
    parser.add_argument("--minutes", type=float, default=0)
    parser.add_argument("--sample-s", type=float, default=0)
    parser.add_argument("--tick-s", type=float, default=0.05, help="sahte piyasa olay aralığı")
    parser.add_argument("--max-rss-growth", type=float, default=25.0)
    parser.add_argument("--max-lag-ms", type=float, default=250.0)
    parser.add_argument("--json")
    args = parser.parse_args()
    if args.hours == 0 and args.minutes == 0:
        args.minutes = 3
    if args.sample_s == 0:
        total = args.hours * 3600 + args.minutes * 60
        args.sample_s = max(5.0, min(300.0, total / 60))
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
