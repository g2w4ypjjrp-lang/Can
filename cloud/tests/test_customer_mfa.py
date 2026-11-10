"""Müşteri iki adımlı doğrulaması (TOTP + kurtarma kodları). Gerçek PostgreSQL."""

from __future__ import annotations

import base64
import os
import time
from collections.abc import AsyncIterator

import httpx
import psycopg
import pytest
from pydantic import SecretStr

from ati_cloud.admin.security import totp_code
from ati_cloud.app import create_app
from ati_cloud.config import CloudSettings
from test_accounts import ORIGIN, PASSWORD, register_and_verify

EMAIL = "iki.adim@example.com"


@pytest.fixture
async def client(dsn: str) -> AsyncIterator[httpx.AsyncClient]:
    settings = CloudSettings(
        environment="test",
        database_url=SecretStr(dsn),
        session_cookie_secure=False,
        admin_secret_kek=SecretStr(base64.b64encode(os.urandom(32)).decode()),
    )
    app = create_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": ORIGIN},
    ) as http:
        yield http
    await app.state.db.close()


def secret_of(setup: dict[str, str]) -> bytes:
    raw = setup["secret"]
    return base64.b32decode(raw + "=" * (-len(raw) % 8))


def code(secret: bytes, step: int = 0) -> str:
    return totp_code(secret, int(time.time() // 30) + step)


async def login(client: httpx.AsyncClient) -> httpx.Response:
    return await client.post("/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})


async def test_enable_login_with_code_and_recovery_then_disable(
    client: httpx.AsyncClient, conn: psycopg.Connection
) -> None:
    await register_and_verify(client, conn, EMAIL)
    assert (await login(client)).json() == {"status": "ok"}
    assert (await client.get("/v1/me/2fa")).json()["enabled"] is False

    assert (await client.post("/v1/me/2fa/setup", json={"password": "yanlis"})).status_code == 401
    setup = (await client.post("/v1/me/2fa/setup", json={"password": PASSWORD})).json()
    assert (
        setup["otpauth_uri"].startswith("otpauth://totp/")
        and EMAIL.replace("@", "%40") in setup["otpauth_uri"]
    )
    secret = secret_of(setup)
    assert (await client.post("/v1/me/2fa/enable", json={"code": "000000"})).status_code == 400
    enabled = await client.post("/v1/me/2fa/enable", json={"code": code(secret)})
    assert enabled.status_code == 200, enabled.text
    recovery = enabled.json()["recovery_codes"]
    assert len(recovery) == 10
    status = (await client.get("/v1/me/2fa")).json()
    assert status["enabled"] is True and status["recovery_left"] == 10
    stored = conn.execute(
        "SELECT mfa_totp_secret_enc FROM customers WHERE email = %s", (EMAIL,)
    ).fetchone()
    assert stored is not None and secret not in bytes(stored[0])  # sır şifreli

    # Parola doğru olsa da oturum açılmaz; kod adımı gerekir.
    await client.post("/v1/auth/logout")
    client.cookies.clear()
    first = (await login(client)).json()
    assert first["status"] == "mfa_required" and "ati_session" not in client.cookies
    assert (await client.get("/v1/me")).status_code == 401
    wrong = await client.post(
        "/v1/auth/login/2fa", json={"challenge": first["challenge"], "code": "123456"}
    )
    assert wrong.status_code == 401
    ok = await client.post(
        "/v1/auth/login/2fa", json={"challenge": first["challenge"], "code": code(secret, 1)}
    )
    assert ok.status_code == 200 and (await client.get("/v1/me")).status_code == 200
    # Aynı kod (zaman adımı) ikinci kez kabul edilmez; kullanılmış kod adımı da geçersizdir.
    client.cookies.clear()
    again = (await login(client)).json()
    replay = await client.post(
        "/v1/auth/login/2fa", json={"challenge": again["challenge"], "code": code(secret, 1)}
    )
    assert replay.status_code == 401
    assert (
        await client.post(
            "/v1/auth/login/2fa", json={"challenge": first["challenge"], "code": code(secret)}
        )
    ).status_code == 401

    # Kurtarma kodu bir kez çalışır.
    by_recovery = await client.post(
        "/v1/auth/login/2fa", json={"challenge": again["challenge"], "code": recovery[0].lower()}
    )
    assert by_recovery.status_code == 200
    assert (await client.get("/v1/me/2fa")).json()["recovery_left"] == 9
    client.cookies.clear()
    third = (await login(client)).json()
    reused = await client.post(
        "/v1/auth/login/2fa", json={"challenge": third["challenge"], "code": recovery[0]}
    )
    assert reused.status_code == 401
    assert (
        await client.post(
            "/v1/auth/login/2fa", json={"challenge": third["challenge"], "code": recovery[1]}
        )
    ).status_code == 200
    actions = [r[0] for r in conn.execute("SELECT action FROM audit_log ORDER BY id").fetchall()]
    assert "customer.mfa_enabled" in actions and "customer.recovery_code_used" in actions

    # Kapatmak parola + kod ister.
    bad = await client.post("/v1/me/2fa/disable", json={"password": PASSWORD, "code": "000000"})
    assert bad.status_code == 400
    off = await client.post("/v1/me/2fa/disable", json={"password": PASSWORD, "code": recovery[2]})
    assert off.status_code == 200
    client.cookies.clear()
    assert (await login(client)).json() == {"status": "ok"}


async def test_code_step_locks_after_five_wrong_codes(
    client: httpx.AsyncClient, conn: psycopg.Connection
) -> None:
    await register_and_verify(client, conn, EMAIL)
    await login(client)
    secret = secret_of((await client.post("/v1/me/2fa/setup", json={"password": PASSWORD})).json())
    await client.post("/v1/me/2fa/enable", json={"code": code(secret)})
    client.cookies.clear()
    challenge = (await login(client)).json()["challenge"]
    for _ in range(5):
        response = await client.post(
            "/v1/auth/login/2fa", json={"challenge": challenge, "code": "999999"}
        )
        assert response.status_code == 401
    late = await client.post(
        "/v1/auth/login/2fa", json={"challenge": challenge, "code": code(secret, 1)}
    )
    assert late.status_code == 401 and "yeniden giriş" in late.json()["detail"]


async def test_unavailable_without_server_key(dsn: str, conn: psycopg.Connection) -> None:
    app = create_app(
        CloudSettings(environment="test", database_url=SecretStr(dsn), session_cookie_secure=False)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": ORIGIN},
    ) as http:
        await register_and_verify(http, conn, EMAIL)
        await login(http)
        assert (await http.get("/v1/me/2fa")).json()["available"] is False
        setup = await http.post("/v1/me/2fa/setup", json={"password": PASSWORD})
        assert setup.status_code == 503
    await app.state.db.close()
