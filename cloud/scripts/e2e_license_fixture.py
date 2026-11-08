"""Uçtan uca lisans testleri için yardımcı (YALNIZCA test ortamı).

Motor testleri (``engine/tests/test_license_e2e.py``) bulut veritabanına doğrudan erişemez; bu
betik bulutun kendi koduyla test verisini hazırlar:

    setup                 boş veritabanı oluşturur ve geçişleri uygular
    issue EMAIL PLAN      doğrulanmış müşteri + o müşteriye satılmış lisans; JSON yazar
    sql "SQL"             test verisini değiştirmek için tek komut (ör. lisansı dondurma)

``ATI_ENVIRONMENT=test`` değilse çalışmaz.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
from urllib.parse import urlparse, urlunparse

import psycopg

from ati_cloud.accounts import Database, hasher
from ati_cloud.config import CloudSettings
from ati_cloud.db.migrate import apply_migrations
from ati_cloud.licensing.service import Licensing


def _admin_dsn(dsn: str) -> tuple[str, str]:
    url = urlparse(dsn)
    name = url.path.lstrip("/")
    return urlunparse(url._replace(path="/postgres")), name


def setup(dsn: str) -> None:
    admin, name = _admin_dsn(dsn)
    if not name.endswith("_e2e"):
        raise SystemExit("Güvenlik: yalnızca adı _e2e ile biten test veritabanı sıfırlanır")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{name}"')
    apply_migrations(dsn)


async def issue(email: str, plan: str) -> dict[str, str]:
    settings = CloudSettings()
    licensing = Licensing.from_settings(settings)
    if licensing is None:
        raise SystemExit("Lisans gizli değerleri tanımlı değil")
    db = Database(settings.database_url.get_secret_value())
    try:
        async with db.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO customers (email, password_hash, email_verified_at) "
                "VALUES (%s, %s, now()) ON CONFLICT (email) WHERE status <> 'deleted' "
                "DO UPDATE SET email = excluded.email "
                "RETURNING id",
                (email, hasher.hash(secrets.token_urlsafe(16))),
            )
            row = await cur.fetchone()
            if row is None:
                raise SystemExit("müşteri oluşturulamadı")
            license_id, key = await licensing.issue(conn, plan_code=plan, customer_id=row["id"])
    finally:
        await db.close()
    return {"license_id": license_id, "key": key}


def main() -> None:
    if os.environ.get("ATI_ENVIRONMENT") != "test":
        raise SystemExit("Bu betik yalnızca ATI_ENVIRONMENT=test ile çalışır")
    dsn = os.environ["ATI_DATABASE_URL"]
    command = sys.argv[1]
    if command == "setup":
        setup(dsn)
    elif command == "issue":
        print(json.dumps(asyncio.run(issue(sys.argv[2], sys.argv[3]))))
    elif command == "sql":
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(sys.argv[2])
    else:
        raise SystemExit(f"Bilinmeyen komut: {command}")


if __name__ == "__main__":
    main()
