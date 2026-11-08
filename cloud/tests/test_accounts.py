"""Aşama 14: müşteri hesapları — kayıt, doğrulama, giriş, oturum, parola sıfırlama, panel ve
güvenlik kuralları (Argon2id, özetlenmiş belirteçler, köken denetimi, hız sınırı, e-posta
sızdırmama). Gerçek PostgreSQL üzerinde."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import psycopg
import pytest
from pydantic import SecretStr

from ati_cloud.app import create_app
from ati_cloud.config import CloudSettings

ORIGIN = "http://localhost:3000"
PASSWORD = "Gizli-Parola-2026!"


@pytest.fixture
async def client(dsn: str) -> AsyncIterator[httpx.AsyncClient]:
    settings = CloudSettings(
        environment="test", database_url=SecretStr(dsn), session_cookie_secure=False
    )
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", headers={"Origin": ORIGIN}
    ) as http:
        yield http
    await app.state.db.close()


def outbox_link(conn: psycopg.Connection, email: str, template: str) -> str:
    row = conn.execute(
        "SELECT payload->>'link' FROM email_outbox WHERE to_email = %s AND template = %s "
        "ORDER BY created_at DESC LIMIT 1",
        (email, template),
    ).fetchone()
    assert row, f"{template} e-postası yok"
    return str(row[0])


def token_of(link: str) -> str:
    return parse_qs(urlparse(link).query)["token"][0]


async def register_and_verify(
    client: httpx.AsyncClient, conn: psycopg.Connection, email: str = "can@example.com"
) -> None:
    response = await client.post(
        "/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "Can", "accept_terms": True},
    )
    assert response.status_code == 202, response.text
    token = token_of(outbox_link(conn, email, "verify_email"))
    verified = await client.post("/v1/auth/verify-email", json={"token": token})
    assert verified.status_code == 200, verified.text


async def test_register_verify_login_me_logout(
    client: httpx.AsyncClient, conn: psycopg.Connection, scalar: Callable[..., Any]
) -> None:
    response = await client.post(
        "/v1/auth/register",
        json={"email": "Can@Example.com", "password": PASSWORD, "accept_terms": True},
    )
    assert response.status_code == 202
    stored = scalar("SELECT password_hash FROM customers WHERE email = 'can@example.com'")
    assert stored.startswith("$argon2id$") and PASSWORD not in stored

    login = await client.post(
        "/v1/auth/login", json={"email": "can@example.com", "password": PASSWORD}
    )
    assert login.status_code == 403 and "doğrulayın" in login.json()["detail"]

    link = outbox_link(conn, "can@example.com", "verify_email")
    assert link.startswith("http://localhost:3000/eposta-dogrula?token=")
    token = token_of(link)
    # Veritabanında belirtecin kendisi değil yalnızca özeti var.
    assert (
        scalar(
            "SELECT count(*) FROM customer_tokens WHERE token_hash = %s",
            (hashlib.sha256(token.encode()).digest(),),
        )
        == 1
    )
    assert (await client.post("/v1/auth/verify-email", json={"token": token})).status_code == 200
    again = await client.post("/v1/auth/verify-email", json={"token": token})
    assert again.status_code == 400  # tek kullanımlık

    login = await client.post(
        "/v1/auth/login", json={"email": "CAN@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200
    cookie = login.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "ati_session=" in cookie
    session_token = client.cookies["ati_session"]
    assert (
        scalar(
            "SELECT count(*) FROM customer_sessions WHERE refresh_token_hash = %s",
            (hashlib.sha256(session_token.encode()).digest(),),
        )
        == 1
    )

    me = await client.get("/v1/me")
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "can@example.com" and body["email_verified"] and body["licenses"] == []

    assert (await client.post("/v1/auth/logout")).status_code == 200
    client.cookies.set("ati_session", session_token)  # çalınmış eski çerez
    assert (await client.get("/v1/me")).status_code == 401
    actions = [r[0] for r in conn.execute("SELECT action FROM audit_log ORDER BY id").fetchall()]
    assert actions == [
        "customer.registered",
        "customer.email_verified",
        "customer.login",
        "customer.logout",
    ]


async def test_wrong_password_and_unknown_email_look_the_same(
    client: httpx.AsyncClient, conn: psycopg.Connection
) -> None:
    await register_and_verify(client, conn)
    wrong = await client.post(
        "/v1/auth/login", json={"email": "can@example.com", "password": "yanlis-parola-123"}
    )
    unknown = await client.post(
        "/v1/auth/login", json={"email": "yok@example.com", "password": PASSWORD}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    failures = conn.execute(
        "SELECT count(*) FROM audit_log WHERE action = 'customer.login_failed'"
    ).fetchone()
    assert failures == (2,)


async def test_registration_does_not_reveal_existing_accounts(
    client: httpx.AsyncClient, conn: psycopg.Connection
) -> None:
    await register_and_verify(client, conn)
    again = await client.post(
        "/v1/auth/register",
        json={"email": "can@example.com", "password": "Baska-Parola-99!", "accept_terms": True},
    )
    fresh = await client.post(
        "/v1/auth/register",
        json={"email": "yeni@example.com", "password": "Baska-Parola-99!", "accept_terms": True},
    )
    assert again.status_code == fresh.status_code == 202
    assert again.json() == fresh.json()
    # Mevcut hesabın sahibine bilgi e-postası gider; parolası değişmez.
    assert outbox_link(conn, "can@example.com", "account_exists").endswith("/giris")
    login = await client.post(
        "/v1/auth/login", json={"email": "can@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200


@pytest.mark.parametrize(
    ("password", "reason"),
    [
        ("kisa1!", "en az"),
        ("1234567890", "kolay"),
        ("aaaaaaaaaaaa", "kolay"),
        ("canbey-2026-xyz", "e-posta"),
    ],
)
async def test_weak_passwords_rejected(
    client: httpx.AsyncClient, password: str, reason: str
) -> None:
    response = await client.post(
        "/v1/auth/register",
        json={"email": "canbey@example.com", "password": password, "accept_terms": True},
    )
    assert response.status_code == 422 and reason in response.json()["detail"]


async def test_terms_must_be_accepted(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/auth/register",
        json={"email": "a@example.com", "password": PASSWORD, "accept_terms": False},
    )
    assert response.status_code == 422 and "koşul" in response.json()["detail"]


async def test_foreign_origin_is_rejected(
    client: httpx.AsyncClient, conn: psycopg.Connection
) -> None:
    await register_and_verify(client, conn)
    evil = await client.post(
        "/v1/auth/login",
        json={"email": "can@example.com", "password": PASSWORD},
        headers={"Origin": "https://kotu-site.example"},
    )
    assert evil.status_code == 403
    missing = await client.post(
        "/v1/auth/login",
        json={"email": "can@example.com", "password": PASSWORD},
        headers={"Origin": ""},
    )
    assert missing.status_code == 403
    assert (
        await client.post("/v1/auth/login", json={"email": "can@example.com", "password": PASSWORD})
    ).status_code == 200
    assert (
        await client.post("/v1/auth/logout", headers={"Origin": "https://kotu-site.example"})
    ).status_code == 403


async def test_login_rate_limit(client: httpx.AsyncClient, conn: psycopg.Connection) -> None:
    await register_and_verify(client, conn)
    codes = [
        (
            await client.post(
                "/v1/auth/login", json={"email": "can@example.com", "password": "yanlis-parola-123"}
            )
        ).status_code
        for _ in range(6)
    ]
    assert codes[:5] == [401] * 5 and codes[5] == 429
    # Doğru parola da sınır dolunca reddedilir (kaba kuvvet denemesi yavaşlatılır).
    assert (
        await client.post("/v1/auth/login", json={"email": "can@example.com", "password": PASSWORD})
    ).status_code == 429


async def test_password_reset_revokes_sessions(
    client: httpx.AsyncClient, conn: psycopg.Connection
) -> None:
    await register_and_verify(client, conn)
    assert (
        await client.post("/v1/auth/login", json={"email": "can@example.com", "password": PASSWORD})
    ).status_code == 200
    old_session = client.cookies["ati_session"]
    unknown = await client.post("/v1/auth/password-reset", json={"email": "yok@example.com"})
    known = await client.post("/v1/auth/password-reset", json={"email": "can@example.com"})
    assert unknown.status_code == known.status_code == 202 and unknown.json() == known.json()
    token = token_of(outbox_link(conn, "can@example.com", "password_reset"))
    weak = await client.post(
        "/v1/auth/password-reset/confirm", json={"token": token, "password": "123"}
    )
    assert weak.status_code == 422
    token = token_of(outbox_link(conn, "can@example.com", "password_reset"))
    # Zayıf parola denemesi işlemi geri aldı: belirteç hâlâ kullanılabilir.
    done = await client.post(
        "/v1/auth/password-reset/confirm", json={"token": token, "password": "Yeni-Guclu-Parola-7"}
    )
    assert done.status_code == 200
    client.cookies.set("ati_session", old_session)
    assert (await client.get("/v1/me")).status_code == 401
    assert (
        await client.post("/v1/auth/login", json={"email": "can@example.com", "password": PASSWORD})
    ).status_code == 401
    assert (
        await client.post(
            "/v1/auth/login", json={"email": "can@example.com", "password": "Yeni-Guclu-Parola-7"}
        )
    ).status_code == 200


async def test_blocked_customer_cannot_log_in_or_use_session(
    client: httpx.AsyncClient, conn: psycopg.Connection
) -> None:
    await register_and_verify(client, conn)
    assert (
        await client.post("/v1/auth/login", json={"email": "can@example.com", "password": PASSWORD})
    ).status_code == 200
    conn.execute(
        "UPDATE customers SET status = 'blocked', blocked_at = now(), blocked_reason = 'test' "
        "WHERE email = 'can@example.com'"
    )
    assert (await client.get("/v1/me")).status_code == 401
    blocked = await client.post(
        "/v1/auth/login", json={"email": "can@example.com", "password": PASSWORD}
    )
    assert blocked.status_code == 403


async def test_plans_only_show_priced_active_packages(
    client: httpx.AsyncClient, conn: psycopg.Connection
) -> None:
    assert (await client.get("/v1/plans")).json() == []  # fiyatlar henüz girilmedi
    conn.execute(
        "UPDATE license_plans SET price_minor = 2900, is_active = true WHERE code = 'd30_1dev'"
    )
    plans = (await client.get("/v1/plans")).json()
    assert [(p["code"], p["price_minor"], p["device_limit"]) for p in plans] == [
        ("d30_1dev", 2900, 1)
    ]


async def test_me_lists_licenses_with_active_devices(
    client: httpx.AsyncClient, conn: psycopg.Connection, factory: Any
) -> None:
    await register_and_verify(client, conn)
    customer = conn.execute("SELECT id FROM customers WHERE email = 'can@example.com'").fetchone()
    assert customer
    license_id = factory.license()
    _, item = factory.order(customer[0])
    factory.sell(license_id, customer[0], item)
    factory.activate(license_id, factory.device(customer[0]))
    assert (
        await client.post("/v1/auth/login", json={"email": "can@example.com", "password": PASSWORD})
    ).status_code == 200
    (lic,) = (await client.get("/v1/me")).json()["licenses"]
    assert lic["plan_code"] == "d30_1dev" and lic["key_hint"] == "ATI-****-****-****-ZR61"
    assert lic["active_devices"] == 1 and lic["status"] in ("sold", "active")
    assert "key" not in lic and "key_ciphertext" not in lic  # tam anahtar panelde gösterilmez


# --- İletişim formu ------------------------------------------------------------------------

CONTACT = {
    "name": "Ayşe",
    "email": "Ayse@Example.com",
    "topic": "support",
    "message": "Kurulumda bir sorun yaşıyorum, yardımcı olur musunuz?",
}


async def test_contact_message_is_stored_without_emailing_sender(
    client: httpx.AsyncClient, conn: psycopg.Connection
) -> None:
    response = await client.post("/v1/contact", json=CONTACT)
    assert response.status_code == 202
    row = conn.execute(
        "SELECT name, email, topic, status, customer_id FROM contact_messages"
    ).fetchone()
    assert row == ("Ayşe", "ayse@example.com", "support", "new", None)
    # Form, rastgele adreslere e-posta yollatmak için kullanılamaz.
    assert conn.execute("SELECT count(*) FROM email_outbox").fetchone() == (0,)


async def test_contact_links_logged_in_customer(
    client: httpx.AsyncClient, conn: psycopg.Connection
) -> None:
    await register_and_verify(client, conn)
    assert (
        await client.post("/v1/auth/login", json={"email": "can@example.com", "password": PASSWORD})
    ).status_code == 200
    assert (await client.post("/v1/contact", json=CONTACT)).status_code == 202
    row = conn.execute(
        "SELECT m.customer_id = c.id FROM contact_messages m, customers c WHERE c.email = 'can@example.com'"
    ).fetchone()
    assert row == (True,)


async def test_contact_honeypot_rate_limit_and_origin(
    client: httpx.AsyncClient, conn: psycopg.Connection
) -> None:
    bot = await client.post("/v1/contact", json={**CONTACT, "website": "http://spam.example"})
    assert bot.status_code == 202  # bot fark etmez
    assert conn.execute("SELECT count(*) FROM contact_messages").fetchone() == (0,)
    foreign = await client.post(
        "/v1/contact", json=CONTACT, headers={"Origin": "https://kotu.example"}
    )
    assert foreign.status_code == 403
    short = await client.post("/v1/contact", json={**CONTACT, "message": "kısa"})
    assert short.status_code == 422
    codes = [(await client.post("/v1/contact", json=CONTACT)).status_code for _ in range(5)]
    assert codes == [202, 202, 202, 202, 429]  # tuzak isteği de sınırdan düşer


async def test_resend_verification_replaces_old_link_and_reveals_nothing(
    client: httpx.AsyncClient, conn: psycopg.Connection
) -> None:
    response = await client.post(
        "/v1/auth/register",
        json={"email": "can@example.com", "password": PASSWORD, "accept_terms": True},
    )
    assert response.status_code == 202
    first = token_of(outbox_link(conn, "can@example.com", "verify_email"))
    known = await client.post("/v1/auth/resend-verification", json={"email": "CAN@example.com"})
    unknown = await client.post("/v1/auth/resend-verification", json={"email": "yok@example.com"})
    assert known.status_code == unknown.status_code == 202 and known.json() == unknown.json()
    second = token_of(outbox_link(conn, "can@example.com", "verify_email"))
    assert second != first
    assert (await client.post("/v1/auth/verify-email", json={"token": first})).status_code == 400
    assert (await client.post("/v1/auth/verify-email", json={"token": second})).status_code == 200
    # Doğrulanmış hesaba yeni bağlantı gitmez.
    before = conn.execute("SELECT count(*) FROM email_outbox").fetchone()
    await client.post("/v1/auth/resend-verification", json={"email": "can@example.com"})
    assert conn.execute("SELECT count(*) FROM email_outbox").fetchone() == before


async def test_resend_verification_is_limited_per_address(
    client: httpx.AsyncClient, conn: psycopg.Connection
) -> None:
    await client.post(
        "/v1/auth/register",
        json={"email": "can@example.com", "password": PASSWORD, "accept_terms": True},
    )
    for _ in range(5):
        assert (
            await client.post("/v1/auth/resend-verification", json={"email": "can@example.com"})
        ).status_code == 202
    sent = conn.execute(
        "SELECT count(*) FROM email_outbox WHERE template = 'verify_email'"
    ).fetchone()
    assert sent == (4,)  # kayıt + 3 yeniden gönderim; sonrası sessizce yok sayılır
    assert (
        await client.post("/v1/auth/resend-verification", json={"email": "can@example.com"})
    ).status_code == 429
