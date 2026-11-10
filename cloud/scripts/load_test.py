"""Aşama 18: yük testi — lisans uç noktaları ve aktarma servisi.

Gerçek sunucular alt süreç olarak başlatılır (``ati-cloud-api``: uvicorn + PostgreSQL;
``ati-cloud-relay``). Ayrı bir veritabanı kurulur (adı ``_load`` ile biter, her çalıştırmada
sıfırdan). Her motor farklı bir istemci adresinden (güvenilen vekil başlığı) gelir; böylece IP
başına hız sınırları gerçek kullanımdaki gibi davranır.

Senaryolar:

1. Etkinleştirme fırtınası: N motor aynı anda lisansını etkinleştirir.
2. Kira yenileme: her motor R kez yeniler (normalde 6 saatte bir; burada art arda).
3. Herkese açık okumalar: paket listesi ve ödeme durumu.
4. Aktarma: E motor + E telefon; telefon → motor → telefon gidiş-dönüş süresi.

Her senaryo için hata oranı ve gecikme yüzdelikleri (p50/p95/p99) raporlanır; eşik aşılırsa çıkış
kodu 1 olur. Eşikler paylaşımlı CI makinesine göre cömerttir; asıl amaç gerilemeyi yakalamaktır.

    export ATI_TEST_DATABASE_URL=postgresql://ati_test:ati_test@127.0.0.1:5432/ati_test
    uv run python scripts/load_test.py --engines 200 --renewals 5 --concurrency 50
    uv run python scripts/load_test.py --quick   # CI duman testi
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import secrets
import socket
import statistics
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import psycopg
import websockets
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from pydantic import SecretStr

from ati_cloud.config import CloudSettings
from ati_cloud.db.migrate import apply_migrations
from ati_cloud.licensing.service import Licensing
from ati_cloud.relay import hello_text, key_id

DB_NAME = "ati_load"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def now_ms() -> int:
    return int(time.time() * 1000)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class Result:
    name: str
    latencies_ms: list[float] = field(default_factory=list)
    errors: dict[str, int] = field(default_factory=dict)
    started: float = 0.0
    finished: float = 0.0

    def record(self, ms: float, error: str | None = None) -> None:
        if error:
            self.errors[error] = self.errors.get(error, 0) + 1
        else:
            self.latencies_ms.append(ms)

    def pct(self, p: float) -> float:
        if not self.latencies_ms:
            return float("nan")
        values = sorted(self.latencies_ms)
        return values[min(len(values) - 1, round(p / 100 * (len(values) - 1)))]

    @property
    def total(self) -> int:
        return len(self.latencies_ms) + sum(self.errors.values())

    def summary(self) -> dict[str, Any]:
        seconds = max(self.finished - self.started, 1e-9)
        return {
            "senaryo": self.name,
            "istek": self.total,
            "hata": sum(self.errors.values()),
            "hatalar": self.errors,
            "saniyede": round(len(self.latencies_ms) / seconds, 1),
            "p50_ms": round(self.pct(50), 1),
            "p95_ms": round(self.pct(95), 1),
            "p99_ms": round(self.pct(99), 1),
            "ort_ms": round(statistics.fmean(self.latencies_ms), 1) if self.latencies_ms else None,
        }


async def run_bounded(
    concurrency: int, jobs: list[Callable[[], Awaitable[None]]], result: Result
) -> None:
    semaphore = asyncio.Semaphore(concurrency)

    async def one(job: Callable[[], Awaitable[None]]) -> None:
        async with semaphore:
            await job()

    result.started = time.perf_counter()
    await asyncio.gather(*(one(job) for job in jobs))
    result.finished = time.perf_counter()


# --- Kurulum -------------------------------------------------------------------------------------


def database(admin_dsn: str) -> str:
    parts = urlsplit(admin_dsn)
    dsn = urlunsplit(parts._replace(path=f"/{DB_NAME}"))
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {DB_NAME}")
    apply_migrations(dsn)
    return dsn


def secrets_env() -> dict[str, str]:
    return {
        "ATI_LICENSE_PEPPER": b64(secrets.token_bytes(32)),
        "ATI_LICENSE_KEK": b64(secrets.token_bytes(32)),
        "ATI_LEASE_SIGNING_KEY": b64(secrets.token_bytes(32)),
        "ATI_ADMIN_SECRET_KEK": b64(secrets.token_bytes(32)),
    }


async def issue_licenses(dsn: str, env: dict[str, str], count: int) -> list[str]:
    settings = CloudSettings(
        environment="test",
        database_url=SecretStr(dsn),
        session_cookie_secure=False,
        license_pepper=SecretStr(env["ATI_LICENSE_PEPPER"]),
        license_kek=SecretStr(env["ATI_LICENSE_KEK"]),
        lease_signing_key=SecretStr(env["ATI_LEASE_SIGNING_KEY"]),
    )
    licensing = Licensing.from_settings(settings)
    assert licensing is not None
    keys = []
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        conn.row_factory = psycopg.rows.dict_row  # type: ignore[assignment]
        cur = await conn.execute(
            "INSERT INTO customers (email, password_hash, email_verified_at) "
            "VALUES ('yuk@example.com', '$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA', now()) "
            "RETURNING id"
        )
        row = await cur.fetchone()
        assert row is not None
        for _ in range(count):
            _, key = await licensing.issue(conn, plan_code="d30_1dev", customer_id=row["id"])  # type: ignore[arg-type]
            keys.append(key)
    return keys


LOG_DIR = Path(os.environ.get("ATI_LOAD_LOG_DIR", "."))


def start(cmd: list[str], env: dict[str, str], name: str) -> subprocess.Popen[bytes]:
    # Günlük dosyaya yazılır (okunmayan bir boru dolarsa sunucu yazarken takılır).
    log = (LOG_DIR / f"load-{name}.log").open("wb")
    return subprocess.Popen(  # noqa: S603 - sabit komut
        cmd, env={**os.environ, **env}, stdout=log, stderr=subprocess.STDOUT
    )


async def wait_http(url: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient() as client:
        while time.monotonic() < deadline:
            try:
                if (await client.get(url)).status_code < 500:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.2)
    raise RuntimeError(f"Sunucu başlamadı: {url}")


# --- Lisans senaryoları ------------------------------------------------------------------------


class EngineClient:
    """Motorun lisans istemcisi: cihaz anahtarı, imzalı istekler, kendi IP adresi."""

    def __init__(self, index: int) -> None:
        self.key = Ed25519PrivateKey.generate()
        self.fingerprint = secrets.token_bytes(32)
        self.ip = f"10.{(index >> 16) & 255}.{(index >> 8) & 255}.{index & 255}"
        self.ts = now_ms()
        self.lease: dict[str, Any] | None = None

    def _ts(self) -> int:
        self.ts = max(self.ts + 1, now_ms())
        return self.ts

    def sign(self, payload: dict[str, Any]) -> dict[str, str]:
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return {"p": text, "s": b64(self.key.sign(text.encode()))}

    def activation(self, license_key: str) -> dict[str, str]:
        return self.sign({
            "v": 1, "type": "activate", "license_key": license_key,
            "device_key": b64(self.key.public_key().public_bytes_raw()),
            "fingerprint": self.fingerprint.hex(), "name": "Yük PC", "platform": "windows",
            "app_version": "0.18.0", "os_version": "Windows 11", "ts_ms": self._ts(),
            "nonce": secrets.token_hex(8),
        })  # fmt: skip

    def renewal(self) -> dict[str, str]:
        assert self.lease is not None
        return self.sign({
            "v": 1, "type": "renew", "license_id": self.lease["license_id"],
            "device_id": self.lease["device_id"], "ts_ms": self._ts(),
            "nonce": secrets.token_hex(8),
        })  # fmt: skip


async def timed(
    result: Result, call: Callable[[], Awaitable[httpx.Response]], ok: int = 200
) -> httpx.Response | None:
    start_ = time.perf_counter()
    try:
        response = await call()
    except httpx.HTTPError as exc:
        result.record(0, type(exc).__name__)
        return None
    ms = (time.perf_counter() - start_) * 1000
    result.record(ms, None if response.status_code == ok else f"HTTP {response.status_code}")
    return response


async def license_scenarios(
    base: str, keys: list[str], renewals: int, concurrency: int
) -> list[Result]:
    engines = [EngineClient(i + 1) for i in range(len(keys))]
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=base, limits=limits, timeout=30) as http:
        activation = Result("Etkinleştirme fırtınası")

        def activate(engine: EngineClient, key: str) -> Callable[[], Awaitable[None]]:
            async def job() -> None:
                response = await timed(activation, lambda: http.post(
                    "/v1/licenses/activate", json=engine.activation(key),
                    headers={"X-Forwarded-For": engine.ip},
                ))  # fmt: skip
                if response is not None and response.status_code == 200:
                    engine.lease = json.loads(response.json()["lease"]["p"])

            return job

        await run_bounded(
            concurrency, [activate(e, k) for e, k in zip(engines, keys, strict=True)], activation
        )

        renewal = Result("Kira yenileme")
        active = [e for e in engines if e.lease is not None]

        def renew(engine: EngineClient) -> Callable[[], Awaitable[None]]:
            async def job() -> None:
                for _ in range(renewals):
                    await timed(renewal, lambda: http.post(
                        "/v1/licenses/renew", json=engine.renewal(),
                        headers={"X-Forwarded-For": engine.ip},
                    ))  # fmt: skip

            return job

        await run_bounded(concurrency, [renew(e) for e in active], renewal)

        reads = Result("Herkese açık okumalar")
        paths = ["/v1/plans", "/v1/payments/status", "/v1/licenses/signing-key"]

        def read(i: int) -> Callable[[], Awaitable[None]]:
            async def job() -> None:
                await timed(reads, lambda: http.get(paths[i % len(paths)]))

            return job

        await run_bounded(concurrency, [read(i) for i in range(len(keys) * 2)], reads)
    return [activation, renewal, reads]


# --- Aktarma senaryosu -----------------------------------------------------------------------------


def device_hello(key: ec.EllipticCurvePrivateKey, engine_id: str) -> dict[str, Any]:
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    device_id, stamp = key_id(public), now_ms()
    r, s = decode_dss_signature(
        key.sign(hello_text("device", device_id, engine_id, str(stamp)), ec.ECDSA(hashes.SHA256()))
    )
    return {"type": "hello", "role": "device", "device_id": device_id, "engine_id": engine_id,
            "key": b64(public), "ts_ms": stamp,
            "sig": b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))}  # fmt: skip


async def relay_pair(url: str, messages: int, result: Result, payload_bytes: int) -> None:
    engine_key = Ed25519PrivateKey.generate()
    public = engine_key.public_key().public_bytes_raw()
    engine_id, stamp = key_id(public), now_ms()
    async with websockets.connect(url + "/v1/relay/engine") as engine_ws:
        await engine_ws.send(json.dumps({
            "type": "hello", "role": "engine", "engine_id": engine_id, "key": b64(public),
            "ts_ms": stamp, "sig": b64(engine_key.sign(hello_text("engine", engine_id, str(stamp)))),
        }))  # fmt: skip
        assert json.loads(await engine_ws.recv())["type"] == "welcome"
        async with websockets.connect(url + "/v1/relay/device") as phone:
            await phone.send(
                json.dumps(device_hello(ec.generate_private_key(ec.SECP256R1()), engine_id))
            )
            assert json.loads(await phone.recv())["type"] == "welcome"
            online = json.loads(await engine_ws.recv())
            device_id = online["device_id"]

            async def echo() -> None:
                # Motor: gelen her şifreli zarfı aynen telefona geri gönderir.
                async for raw in engine_ws:
                    frame = json.loads(raw)
                    if frame.get("type") == "from_device":
                        await engine_ws.send(json.dumps(
                            {"type": "to_device", "device_id": device_id, "msg": frame["msg"]}
                        ))  # fmt: skip

            echo_task = asyncio.create_task(echo())
            blob = b64(secrets.token_bytes(payload_bytes))  # şifreli zarf boyutunda içerik
            try:
                for i in range(messages):
                    start_ = time.perf_counter()
                    await phone.send(json.dumps(
                        {"type": "to_engine", "msg": {"v": 1, "e": str(i), "n": "", "c": blob}}
                    ))  # fmt: skip
                    try:
                        async with asyncio.timeout(10):
                            while True:
                                frame = json.loads(await phone.recv())
                                if frame.get("type") == "from_engine" and frame["msg"]["e"] == str(
                                    i
                                ):
                                    break
                        result.record((time.perf_counter() - start_) * 1000)
                    except TimeoutError:
                        result.record(0, "zaman aşımı")
            finally:
                echo_task.cancel()


async def relay_scenario(url: str, pairs: int, messages: int, payload_bytes: int) -> Result:
    result = Result(f"Aktarma gidiş-dönüş ({pairs} motor + {pairs} telefon)")
    result.started = time.perf_counter()
    await asyncio.gather(*(relay_pair(url, messages, result, payload_bytes) for _ in range(pairs)))
    result.finished = time.perf_counter()
    return result


# --- Ana akış ------------------------------------------------------------------------------------


def report(results: list[Result], limits: dict[str, float], out: Path | None) -> bool:
    rows = [r.summary() for r in results]
    ok = True
    print(f"\n{'Senaryo':<44} {'İstek':>6} {'Hata':>5} {'/sn':>7} {'p50':>7} {'p95':>7} {'p99':>7}")
    for row, result in zip(rows, results, strict=True):
        limit = limits.get(result.name.split(" (")[0], limits["varsayılan"])
        passed = row["hata"] == 0 and row["p95_ms"] <= limit
        ok &= passed
        print(
            f"{row['senaryo']:<44} {row['istek']:>6} {row['hata']:>5} {row['saniyede']:>7} "
            f"{row['p50_ms']:>7} {row['p95_ms']:>7} {row['p99_ms']:>7}  "
            f"{'✓' if passed else '✗'} (p95 ≤ {limit:.0f} ms)"
        )
        if row["hatalar"]:
            print(f"    hatalar: {row['hatalar']}")
    if out is not None:
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return ok


async def main_async(args: argparse.Namespace) -> int:
    admin_dsn = os.environ.get("ATI_TEST_DATABASE_URL")
    if not admin_dsn:
        print("ATI_TEST_DATABASE_URL gerekli", file=sys.stderr)
        return 2
    dsn = database(admin_dsn)
    env = secrets_env()
    print(f"{args.engines} lisans üretiliyor…")
    keys = await issue_licenses(dsn, env, args.engines)
    api_port, relay_port = free_port(), free_port()
    api_env = {
        **env,
        "ATI_DATABASE_URL": dsn,
        "ATI_ENVIRONMENT": "test",
        "ATI_SESSION_COOKIE_SECURE": "false",
        "ATI_TRUSTED_PROXIES": '["127.0.0.1"]',
    }
    api = start([sys.executable, "-m", "ati_cloud.server", "--port", str(api_port)], api_env, "api")
    relay = start([sys.executable, "-m", "ati_cloud.relay", "--port", str(relay_port)], {}, "relay")
    try:
        await wait_http(f"http://127.0.0.1:{api_port}/health")
        await wait_http(f"http://127.0.0.1:{relay_port}/health")
        results = await license_scenarios(
            f"http://127.0.0.1:{api_port}", keys, args.renewals, args.concurrency
        )
        results.append(
            await relay_scenario(
                f"ws://127.0.0.1:{relay_port}", args.relay_pairs, args.relay_messages, 1500
            )
        )
    finally:
        for proc in (api, relay):
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    limits = {
        "Etkinleştirme fırtınası": args.max_p95_ms * 2,  # cihaz kaydı + kilitli yazma
        "varsayılan": args.max_p95_ms,
    }
    ok = report(results, limits, Path(args.json) if args.json else None)
    print("\nSonuç:", "BAŞARILI" if ok else "EŞİK AŞILDI")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Lisans ve aktarma yük testi")
    parser.add_argument("--engines", type=int, default=200)
    parser.add_argument("--renewals", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--relay-pairs", type=int, default=50)
    parser.add_argument("--relay-messages", type=int, default=20)
    parser.add_argument("--max-p95-ms", type=float, default=500)
    parser.add_argument("--quick", action="store_true", help="CI duman testi (küçük)")
    parser.add_argument("--json", help="sonuçları bu dosyaya yaz")
    args = parser.parse_args()
    if args.quick:
        args.engines, args.renewals, args.concurrency = 60, 3, 20
        args.relay_pairs, args.relay_messages, args.max_p95_ms = 20, 10, 1500
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
