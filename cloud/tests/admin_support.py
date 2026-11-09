"""Yönetici testleri için ortak yardımcılar: ayarlar, saat (TOTP), davetle yönetici oluşturma."""

from __future__ import annotations

import base64
import secrets
import time
from dataclasses import dataclass
from typing import Any

import httpx
import psycopg
from pydantic import SecretStr

from ati_cloud.accounts import Database
from ati_cloud.admin import security
from ati_cloud.admin.admins import create_invited_admin
from ati_cloud.config import CloudSettings

ADMIN_ORIGIN = "http://localhost:3000"
ADMIN_PASSWORD = "Yonetici-Parolasi-2026!"


def b64(n: int) -> SecretStr:
    return SecretStr(base64.b64encode(secrets.token_bytes(n)).decode())


def admin_settings(dsn: str, **extra: Any) -> CloudSettings:
    return CloudSettings(
        environment="test",
        database_url=SecretStr(dsn),
        session_cookie_secure=False,
        license_pepper=b64(32),
        license_kek=b64(32),
        lease_signing_key=b64(32),
        admin_secret_kek=b64(32),
        **extra,
    )


class Clock:
    """TOTP için kontrollü saat: her kod üretiminde bir zaman adımı ilerler (kod tekrar kullanımı
    reddedildiği için gerçek saatte aynı 30 sn içinde ikinci kod üretilemezdi)."""

    def __init__(self) -> None:
        self.now = float(int(time.time()) // 30 * 30)

    def __call__(self) -> float:
        return self.now

    def code(self, secret: bytes) -> str:
        self.now += 30
        return security.totp_code(secret, int(self.now // 30))


@dataclass
class AdminClient:
    http: httpx.AsyncClient
    secret: bytes
    email: str
    id: str
    recovery_codes: list[str]


async def invite_admin(
    app: Any, email: str, roles: list[str], name: str = "Test Yönetici"
) -> tuple[str, str]:
    db: Database = app.state.db
    async with db.connection() as conn:
        admin_id, token = await create_invited_admin(
            conn, email=email, full_name=name, roles=roles, created_by=None
        )
    return str(admin_id), token


async def activate_admin(app: Any, clock: Clock, email: str, roles: list[str]) -> AdminClient:
    admin_id, token = await invite_admin(app, email, roles)
    http = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": ADMIN_ORIGIN},
    )
    start = await http.post("/admin/v1/auth/invite/start", json={"token": token})
    assert start.status_code == 200, start.text
    secret = base64.b32decode(start.json()["secret"] + "=" * (-len(start.json()["secret"]) % 8))
    done = await http.post(
        "/admin/v1/auth/invite/complete",
        json={"token": token, "password": ADMIN_PASSWORD, "code": clock.code(secret)},
    )
    assert done.status_code == 200, done.text
    return AdminClient(http, secret, email, admin_id, done.json()["recovery_codes"])


def sync_conn(dsn: str) -> psycopg.Connection[Any]:
    return psycopg.connect(dsn, autocommit=True)
