"""Gerçek PostgreSQL üzerinde çalışan test altyapısı.

``ATI_TEST_DATABASE_URL`` bir süper kullanıcı (veya CREATEDB yetkili) bağlantısı olmalıdır.
Oturum başında geçişler bir şablon veritabanına bir kez uygulanır; her test bu şablondan
kopyalanan temiz bir veritabanında çalışır.
"""

from __future__ import annotations

import os
import secrets
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest

from admin_support import Clock, admin_settings
from ati_cloud.admin import security as admin_security
from ati_cloud.app import create_app
from ati_cloud.db.migrate import apply_migrations

BASE_URL = os.environ.get("ATI_TEST_DATABASE_URL")
TEMPLATE_DB = f"ati_tpl_{os.getpid()}"


def _with_db(url: str, dbname: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{dbname}"))


@pytest.fixture(scope="session")
def template_dsn() -> Iterator[str]:
    if not BASE_URL:
        pytest.skip("ATI_TEST_DATABASE_URL tanımlı değil")
    with psycopg.connect(BASE_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{TEMPLATE_DB}"')
        admin.execute(f'CREATE DATABASE "{TEMPLATE_DB}"')
    dsn = _with_db(BASE_URL, TEMPLATE_DB)
    apply_migrations(dsn)
    yield dsn
    with psycopg.connect(BASE_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{TEMPLATE_DB}" WITH (FORCE)')


@pytest.fixture
def dsn(template_dsn: str) -> Iterator[str]:
    assert BASE_URL
    name = f"ati_t_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(BASE_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}" TEMPLATE "{TEMPLATE_DB}"')
    yield _with_db(BASE_URL, name)
    with psycopg.connect(BASE_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def empty_dsn() -> Iterator[str]:
    if not BASE_URL:
        pytest.skip("ATI_TEST_DATABASE_URL tanımlı değil")
    name = f"ati_e_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(BASE_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    yield _with_db(BASE_URL, name)
    with psycopg.connect(BASE_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def conn(dsn: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(dsn, autocommit=True) as connection:
        yield connection


ARGON2_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNoaGFzaA"


@dataclass
class Factory:
    conn: psycopg.Connection

    def customer(self, email: str | None = None) -> uuid.UUID:
        row = self.conn.execute(
            "INSERT INTO customers (email, password_hash) VALUES (%s, %s) RETURNING id",
            (email or f"{uuid.uuid4().hex[:8]}@example.com", ARGON2_HASH),
        ).fetchone()
        assert row
        return row[0]  # type: ignore[no-any-return]

    def license(self, *, plan: str = "d30_1dev", status: str = "ready_for_sale") -> uuid.UUID:
        row = self.conn.execute(
            """
            INSERT INTO licenses (key_hash, key_ciphertext, key_hint, plan_code, status,
                                  duration_days, device_limit, companion_device_limit)
            SELECT %s, %s, %s, code, %s, duration_days, device_limit, companion_device_limit
            FROM license_plans WHERE code = %s
            RETURNING id
            """,
            (
                secrets.token_bytes(32),
                secrets.token_bytes(60),
                "ATI-****-****-****-ZR61",
                status,
                plan,
            ),
        ).fetchone()
        assert row
        return row[0]  # type: ignore[no-any-return]

    def order(
        self, customer_id: uuid.UUID, *, plan: str = "d30_1dev", quantity: int = 1
    ) -> tuple[uuid.UUID, uuid.UUID]:
        order = self.conn.execute(
            "INSERT INTO orders (customer_id, currency, subtotal_minor, total_minor, payment_provider) "
            "VALUES (%s, 'USD', %s, %s, 'test') RETURNING id",
            (customer_id, 1000 * quantity, 1000 * quantity),
        ).fetchone()
        assert order
        item = self.conn.execute(
            "INSERT INTO order_items (order_id, plan_code, quantity, unit_price_minor, line_total_minor) "
            "VALUES (%s, %s, %s, 1000, %s) RETURNING id",
            (order[0], plan, quantity, 1000 * quantity),
        ).fetchone()
        assert item
        return order[0], item[0]

    def sell(
        self, license_id: uuid.UUID, customer_id: uuid.UUID, item_id: uuid.UUID, unit: int = 1
    ) -> None:
        self.conn.execute(
            "UPDATE licenses SET status = 'sold', customer_id = %s, order_item_id = %s, "
            "order_item_unit = %s, sold_at = now() WHERE id = %s",
            (customer_id, item_id, unit, license_id),
        )

    def device(self, customer_id: uuid.UUID, platform: str = "windows") -> uuid.UUID:
        row = self.conn.execute(
            "INSERT INTO devices (customer_id, platform, fingerprint_hash, display_name) "
            "VALUES (%s, %s, %s, 'Test') RETURNING id",
            (customer_id, platform, secrets.token_bytes(32)),
        ).fetchone()
        assert row
        return row[0]  # type: ignore[no-any-return]

    def activate(self, license_id: uuid.UUID, device_id: uuid.UUID) -> uuid.UUID:
        row = self.conn.execute(
            "INSERT INTO license_activations (license_id, device_id) VALUES (%s, %s) RETURNING id",
            (license_id, device_id),
        ).fetchone()
        assert row
        return row[0]  # type: ignore[no-any-return]

    def status(self, license_id: uuid.UUID) -> str:
        row = self.conn.execute(
            "SELECT status FROM licenses WHERE id = %s", (license_id,)
        ).fetchone()
        assert row
        return str(row[0])


@pytest.fixture
def factory(conn: psycopg.Connection) -> Factory:
    return Factory(conn)


@pytest.fixture
def scalar(conn: psycopg.Connection) -> Callable[..., Any]:
    def _scalar(sql: str, params: tuple[Any, ...] = ()) -> Any:
        row = conn.execute(sql, params).fetchone()
        return None if row is None else row[0]

    return _scalar


# --- Yönetici paneli testleri (Aşama 16) --------------------------------------------------------


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    """TOTP için kontrollü saat (bkz. admin_support.Clock)."""
    fake = Clock()
    monkeypatch.setattr(admin_security.time, "time", fake)
    return fake


@pytest.fixture
async def app(dsn: str) -> AsyncIterator[Any]:
    application = create_app(admin_settings(dsn))
    yield application
    await application.state.db.close()
