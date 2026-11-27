"""Testler gerçek bir PostgreSQL 16 üzerinde, gerçek şema ve RLS kurallarıyla çalışır.

BC_TEST_ADMIN_DSN: test veritabanı oluşturabilen yönetici bağlantısı
(varsayılan: yerel geliştirme sunucusu). Bulunamazsa veritabanı testleri atlanır.
"""

import os
import time
import uuid
from pathlib import Path

import jwt
import psycopg
import pytest
from httpx import ASGITransport, AsyncClient

from bizcenter.config import Settings
from bizcenter.db import Database
from bizcenter.main import create_app

ROOT = Path(__file__).resolve().parents[2]
SECRET = "test-secret-" + "x" * 32
ADMIN_DSN = os.environ.get("BC_TEST_ADMIN_DSN", "host=/tmp/pgbc port=55432 user=postgres dbname=postgres")


def _admin_ok() -> bool:
    try:
        psycopg.connect(ADMIN_DSN, connect_timeout=2).close()
        return True
    except psycopg.Error:
        return False


@pytest.fixture(scope="session")
def dsn() -> str:
    if not _admin_ok():
        if os.environ.get("CI"):
            pytest.fail("CI ortamında test veritabanı zorunludur")
        pytest.skip("Test PostgreSQL sunucusu yok (BC_TEST_ADMIN_DSN)")
    name = "bc_test_" + uuid.uuid4().hex[:8]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as c:
        c.execute(f'create database "{name}"')
    base = psycopg.conninfo.conninfo_to_dict(ADMIN_DSN)
    base["dbname"] = name
    test_dsn = psycopg.conninfo.make_conninfo(**base)
    with psycopg.connect(test_dsn, autocommit=True) as c:
        for f in ("supabase/test/supabase_stub.sql", *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "supabase/migrations").glob("*.sql"))):
            c.execute((ROOT / f).read_text())
    yield test_dsn
    with psycopg.connect(ADMIN_DSN, autocommit=True) as c:
        c.execute(f'drop database "{name}" with (force)')


@pytest.fixture(scope="session")
def admin(dsn):
    with psycopg.connect(dsn, autocommit=True, row_factory=psycopg.rows.dict_row) as c:
        yield c


def make_user(admin, email: str) -> str:
    uid = str(uuid.uuid4())
    admin.execute("insert into auth.users(id, email) values (%s, %s)", (uid, email))
    return uid


def token(uid: str, *, exp: int | None = None, secret: str = SECRET, role: str = "authenticated") -> str:
    return jwt.encode({"sub": uid, "aud": "authenticated", "role": role, "email": "u@test",
                       "exp": exp or int(time.time()) + 600}, secret, algorithm="HS256")


def auth(uid: str) -> dict[str, str]:
    return {"authorization": "Bearer " + token(uid)}


@pytest.fixture(scope="session")
async def client(dsn):
    settings = Settings(database_url=dsn, supabase_jwt_secret=SECRET, rate_limit_per_minute=10_000)
    app = create_app(settings, Database(dsn, 4))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
