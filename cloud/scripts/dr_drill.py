"""Aşama 18: felaket kurtarma tatbikatı (bulut veritabanı).

1. Kaynak veritabanı gerçek iş akışlarıyla doldurulur: müşteriler, satılmış ve havuzdaki
   lisanslar, bir bilgisayarda etkin lisans (imzalı kira), ödemesi alınmış sipariş (fatura kaydı,
   e-posta kuyruğu), yönetici daveti ve hash zincirli denetim kaydı.
2. ``pg_dump`` (özel biçim) → boş bir veritabanına ``pg_restore``. Süreler ve boyut ölçülür.
3. Geri yüklenen veritabanında doğrulanır:
   * tüm tabloların satır sayıları aynı; denetim zinciri sağlam ve son özet aynı;
   * değiştirilemezlik tetikleyicileri çalışıyor (denetim kaydı güncellenemez);
   * kimlik/dizi sayaçları devam ediyor (yeni sipariş ve lisans numaraları çakışmaz);
   * aynı gizli anahtarlarla (KEK, pepper, kira imza anahtarı) iş sürüyor: müşteri tam lisans
     anahtarını görebiliyor, motor aynı cihaz anahtarıyla kirasını yenileyebiliyor;
   * gizli anahtarlar olmadan yedek tek başına lisans anahtarlarını açamıyor (yedekler ve
     gizli bilgi deposu ayrı saklanmalı).

    export ATI_TEST_DATABASE_URL=postgresql://ati_test:ati_test@127.0.0.1:5432/ati_test
    uv run python scripts/dr_drill.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import psycopg
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import SecretStr

from ati_cloud.accounts import token_digest
from ati_cloud.admin.admins import create_invited_admin
from ati_cloud.app import create_app
from ati_cloud.config import CloudSettings
from ati_cloud.db.migrate import apply_migrations
from ati_cloud.licensing.keys import KeyCipher
from ati_cloud.licensing.service import Licensing

ORIGIN = "http://localhost:3000"
ARGON2 = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNoaGFzaA"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def with_db(dsn: str, name: str) -> str:
    return urlunsplit(urlsplit(dsn)._replace(path=f"/{name}"))


def recreate(admin_dsn: str, name: str) -> str:
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {name}")
    return with_db(admin_dsn, name)


def settings_for(dsn: str, secret: dict[str, str]) -> CloudSettings:
    return CloudSettings(
        environment="test",
        database_url=SecretStr(dsn),
        session_cookie_secure=False,
        license_pepper=SecretStr(secret["pepper"]),
        license_kek=SecretStr(secret["kek"]),
        lease_signing_key=SecretStr(secret["lease"]),
        admin_secret_kek=SecretStr(secret["admin"]),
    )


class Device:
    def __init__(self) -> None:
        self.key = Ed25519PrivateKey.generate()
        self.fingerprint = secrets.token_bytes(32)
        self.ts = int(time.time() * 1000)
        self.lease: dict[str, Any] = {}

    def sign(self, payload: dict[str, Any]) -> dict[str, str]:
        self.ts = max(self.ts + 1, int(time.time() * 1000))
        payload = {**payload, "ts_ms": self.ts, "nonce": secrets.token_hex(8), "v": 1}
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return {"p": text, "s": b64(self.key.sign(text.encode()))}

    def activation(self, key: str) -> dict[str, str]:
        return self.sign({
            "type": "activate", "license_key": key,
            "device_key": b64(self.key.public_key().public_bytes_raw()),
            "fingerprint": self.fingerprint.hex(), "name": "Ofis PC", "platform": "windows",
            "app_version": "0.18.0", "os_version": "Windows 11",
        })  # fmt: skip

    def renewal(self) -> dict[str, str]:
        return self.sign({"type": "renew", "license_id": self.lease["license_id"],
                          "device_id": self.lease["device_id"]})  # fmt: skip


def client(app: Any, cookie: str | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": ORIGIN},
        cookies={"ati_session": cookie} if cookie else None,
    )


async def populate(dsn: str, secret: dict[str, str]) -> dict[str, Any]:
    app = create_app(settings_for(dsn, secret))
    licensing: Licensing = app.state.licensing
    facts: dict[str, Any] = {}
    with psycopg.connect(dsn, autocommit=True) as conn:
        customers = [
            conn.execute(
                "INSERT INTO customers (email, password_hash, email_verified_at, full_name) "
                "VALUES (%s, %s, now(), %s) RETURNING id",
                (f"musteri{i}@example.com", ARGON2, f"Müşteri {i}"),
            ).fetchone()[0]  # type: ignore[index]
            for i in range(20)
        ]
        token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO customer_sessions (customer_id, refresh_token_hash, client_kind, "
            "expires_at) VALUES (%s, %s, 'web', now() + interval '1 day')",
            (customers[0], token_digest(token)),
        )
        conn.execute(
            "INSERT INTO system_settings (key, value) VALUES ('payment', %s)",
            (json.dumps({"provider": "simulator", "mode": "test", "public": {}, "secrets": {}}),),
        )
        conn.execute(
            "UPDATE license_plans SET price_minor = 149900, currency = 'TRY', is_active = true "
            "WHERE code = 'd30_1dev'"
        )
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as aconn:
        aconn.row_factory = psycopg.rows.dict_row  # type: ignore[assignment]
        sold = []
        for i, customer in enumerate(customers):
            license_id, key = await licensing.issue(
                aconn, plan_code="d30_1dev", customer_id=customer
            )  # type: ignore[arg-type]
            sold.append((license_id, key))
            if i < 10:
                await licensing.issue(aconn, plan_code="d90_1dev")  # type: ignore[arg-type]
        await create_invited_admin(
            aconn, email="kok@example.com", full_name="Kök", roles=["super_admin"], created_by=None
        )
    facts["license_id"], facts["license_key"] = sold[0]
    facts["customer_id"] = str(customers[0])

    device = Device()
    async with client(app) as http:
        activated = await http.post("/v1/licenses/activate", json=device.activation(sold[0][1]))
        if activated.status_code != 200:
            raise RuntimeError(f"Etkinleştirme başarısız: {activated.text}")
        device.lease = json.loads(activated.json()["lease"]["p"])
    async with client(app, token) as http:
        checkout = await http.post(
            "/v1/checkout",
            json={"plan_code": "d30_1dev", "accept_preinfo": True, "accept_contract": True,
                  "accept_immediate_delivery": True,
                  "billing": {"full_name": "Müşteri Sıfır", "phone": "+90 532 000 00 00",
                              "address": "Örnek Mah. Deneme Sok. No: 1", "city": "İstanbul"}},
        )  # fmt: skip
        if checkout.status_code != 200:
            raise RuntimeError(f"Ödeme başlatılamadı: {checkout.text}")
        oturum = checkout.json()["redirect_url"].split("oturum=", 1)[1]
        paid = await http.post(
            "/v1/payments/simulator/complete", json={"token": oturum, "outcome": "success"}
        )
        if paid.status_code != 200:
            raise RuntimeError(f"Test ödemesi başarısız: {paid.text}")
    await app.state.db.close()
    facts["device"] = device
    facts["session"] = token
    return facts


def fingerprint(dsn: str) -> dict[str, Any]:
    with psycopg.connect(dsn) as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            ).fetchall()
        ]
        counts = {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}  # type: ignore[index]  # noqa: S608
        broken = conn.execute("SELECT audit_log_verify()").fetchone()[0]  # type: ignore[index]
        last = conn.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
        max_order = conn.execute("SELECT max(order_no) FROM orders").fetchone()[0]  # type: ignore[index]
        max_serial = conn.execute("SELECT max(serial) FROM licenses").fetchone()[0]  # type: ignore[index]
    return {
        "counts": counts,
        "audit_broken_at": broken,
        "audit_last_hash": bytes(last[0]).hex() if last else None,
        "max_order_no": max_order,
        "max_serial": max_serial,
    }


def run(cmd: list[str]) -> float:
    start = time.perf_counter()
    subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603 - sabit araç
    return time.perf_counter() - start


async def verify(dsn: str, secret: dict[str, str], facts: dict[str, Any]) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    with psycopg.connect(dsn, autocommit=True) as conn:
        try:
            conn.execute("UPDATE audit_log SET action = 'x.y' WHERE id = 1")
            checks["denetim kaydı değiştirilemez (tetikleyici)"] = False
        except psycopg.errors.InsufficientPrivilege:
            checks["denetim kaydı değiştirilemez (tetikleyici)"] = True
    app = create_app(settings_for(dsn, secret))
    device: Device = facts["device"]
    async with client(app) as http:
        renewed = await http.post("/v1/licenses/renew", json=device.renewal())
        checks["motor aynı cihaz anahtarıyla kirasını yeniliyor"] = renewed.status_code == 200
    async with client(app, facts["session"]) as http:
        me = await http.get("/v1/me")
        checks["müşteri oturumu ve lisansları yerinde"] = me.status_code == 200 and bool(
            me.json()["licenses"]
        )
    licensing: Licensing = app.state.licensing
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as aconn:
        aconn.row_factory = psycopg.rows.dict_row  # type: ignore[assignment]
        revealed = await licensing.reveal(
            aconn, customer_id=facts["customer_id"], license_id=facts["license_id"], ip="127.0.0.1"
        )
        checks["tam lisans anahtarı aynı KEK ile çözülüyor"] = revealed == facts["license_key"]
        _, new_key = await licensing.issue(aconn, plan_code="d30_1dev")  # type: ignore[arg-type]
        cur = await aconn.execute(
            "SELECT key_ciphertext, key_hash FROM licenses WHERE id = %s", (facts["license_id"],)
        )
        row = await cur.fetchone()
    await app.state.db.close()
    # Gizli anahtar olmadan yedek tek başına anahtarı açamaz.
    wrong = KeyCipher(secrets.token_bytes(32), "local-1")
    try:
        wrong.decrypt(bytes(row["key_ciphertext"]), bytes(row["key_hash"]))  # type: ignore[index]
        checks["yanlış KEK ile anahtarlar açılamıyor"] = False
    except Exception:
        checks["yanlış KEK ile anahtarlar açılamıyor"] = True
    checks["yeni lisans üretilebiliyor (dizi devam ediyor)"] = new_key.startswith("ATI-")
    return checks


async def main_async() -> int:
    admin_dsn = os.environ.get("ATI_TEST_DATABASE_URL")
    if not admin_dsn:
        print("ATI_TEST_DATABASE_URL gerekli", file=sys.stderr)
        return 2
    for tool in ("pg_dump", "pg_restore"):
        if shutil.which(tool) is None:
            print(f"{tool} bulunamadı", file=sys.stderr)
            return 2
    secret = {k: b64(secrets.token_bytes(32)) for k in ("pepper", "kek", "lease", "admin")}
    source = recreate(admin_dsn, "ati_dr_source")
    apply_migrations(source)
    print("Kaynak veritabanı dolduruluyor…")
    facts = await populate(source, secret)
    before = fingerprint(source)
    restored = recreate(admin_dsn, "ati_dr_restored")
    with tempfile.TemporaryDirectory(prefix="ati-dr-") as tmp:
        dump = Path(tmp) / "ati.dump"
        dump_s = run(["pg_dump", "--format=custom", "--no-owner", f"--file={dump}", source])
        size_kb = dump.stat().st_size / 1024
        restore_s = run(
            ["pg_restore", "--no-owner", "--exit-on-error", f"--dbname={restored}", str(dump)]
        )
    after = fingerprint(restored)
    checks = {
        "tablo satır sayıları aynı": before["counts"] == after["counts"],
        "denetim zinciri sağlam": after["audit_broken_at"] is None,
        "denetim zincirinin son özeti aynı": before["audit_last_hash"] == after["audit_last_hash"],
    }
    checks.update(await verify(restored, secret, facts))
    with psycopg.connect(restored) as conn:
        next_order = conn.execute(
            "SELECT nextval(pg_get_serial_sequence('orders', 'order_no'))"
        ).fetchone()[0]  # type: ignore[index]
    checks["sipariş numarası çakışmıyor"] = next_order > before["max_order_no"]
    total_rows = sum(before["counts"].values())
    print(f"\nYedek: {size_kb:.0f} KB, {len(before['counts'])} tablo, {total_rows} satır")
    print(f"pg_dump {dump_s:.2f} sn, pg_restore {restore_s:.2f} sn")
    for name, ok in checks.items():
        print(f"  {'✓' if ok else '✗'} {name}")
    ok = all(checks.values())
    print("Sonuç:", "BAŞARILI" if ok else "BAŞARISIZ")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
