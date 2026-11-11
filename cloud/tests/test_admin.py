"""Aşama 16: yönetici paneli API'si — davet, giriş (parola + TOTP / kurtarma kodu), kilitlenme,
paketler, lisans işlemleri, müşteri/cihaz, yönetici hesapları, ödeme ve şirket ayarları, denetim
kaydı. Gerçek PostgreSQL üzerinde."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import psycopg
import pytest

from admin_support import (
    ADMIN_ORIGIN,
    ADMIN_PASSWORD,
    AdminClient,
    Clock,
    activate_admin,
    admin_settings,
    invite_admin,
)
from ati_cloud.admin.security import totp_code, verify_totp
from ati_cloud.admin.settings_api import load_payment_secrets
from ati_cloud.app import create_app
from ati_cloud.licensing.keys import normalize


def client_for(application: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
        headers={"Origin": ADMIN_ORIGIN},
    )


async def login(
    http: httpx.AsyncClient, email: str, password: str = ADMIN_PASSWORD
) -> httpx.Response:
    return await http.post("/admin/v1/auth/login", json={"email": email, "password": password})


async def full_login(http: httpx.AsyncClient, clock: Clock, admin: AdminClient) -> None:
    first = await login(http, admin.email)
    assert first.status_code == 200, first.text
    done = await http.post(
        "/admin/v1/auth/verify",
        json={"challenge": first.json()["challenge"], "code": clock.code(admin.secret)},
    )
    assert done.status_code == 200, done.text


@pytest.fixture
async def root(app: Any, clock: Clock) -> AdminClient:
    return await activate_admin(app, clock, "kok@example.com", ["super_admin"])


def audit_actions(dsn: str) -> list[str]:
    with psycopg.connect(dsn) as conn:
        return [r[0] for r in conn.execute("SELECT action FROM audit_log ORDER BY id").fetchall()]


# --- TOTP ---------------------------------------------------------------------------------------


def test_totp_rfc6238_vectors_and_reuse() -> None:
    secret = b"12345678901234567890"  # RFC 6238 Ek B (SHA1)
    assert totp_code(secret, 59 // 30) == "287082"
    assert totp_code(secret, 1111111109 // 30) == "081804"
    assert totp_code(secret, 2000000000 // 30) == "279037"
    counter = verify_totp(secret, "081804", last_counter=None, now=1111111109)
    assert counter == 1111111109 // 30
    assert verify_totp(secret, "081804", last_counter=counter, now=1111111109) is None  # tekrar
    assert verify_totp(secret, "123", last_counter=None, now=59) is None


# --- Davet ve giriş -------------------------------------------------------------------------------


async def test_invite_flow_activates_with_password_and_totp(
    app: Any, clock: Clock, dsn: str
) -> None:
    admin_id, token = await invite_admin(app, "yeni@example.com", ["support"])
    http = client_for(app)
    assert (
        await http.post("/admin/v1/auth/invite/start", json={"token": "x" * 40})
    ).status_code == 400
    start = (await http.post("/admin/v1/auth/invite/start", json={"token": token})).json()
    assert start["otpauth_uri"].startswith("otpauth://totp/") and "secret=" in start["otpauth_uri"]
    secret = base64.b32decode(start["secret"] + "=" * (-len(start["secret"]) % 8))
    weak = await http.post(
        "/admin/v1/auth/invite/complete",
        json={"token": token, "password": "kisa-parola", "code": clock.code(secret)},
    )
    assert weak.status_code == 422
    wrong = await http.post(
        "/admin/v1/auth/invite/complete",
        json={"token": token, "password": ADMIN_PASSWORD, "code": "000000"},
    )
    assert wrong.status_code == 400
    done = await http.post(
        "/admin/v1/auth/invite/complete",
        json={"token": token, "password": ADMIN_PASSWORD, "code": clock.code(secret)},
    )
    assert done.status_code == 200
    codes = done.json()["recovery_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    me = (await http.get("/admin/v1/auth/me")).json()
    assert me["email"] == "yeni@example.com" and me["roles"] == ["support"]
    # Davet bağlantısı tek kullanımlık.
    assert (
        await http.post("/admin/v1/auth/invite/start", json={"token": token})
    ).status_code == 400
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT status::text, totp_secret_enc IS NOT NULL, position(%s in encode(totp_secret_enc, 'escape')) "
            "FROM admin_users WHERE id = %s",
            (start["secret"], admin_id),
        ).fetchone()
    assert row == ("active", True, 0)  # TOTP sırrı şifreli
    cookie = done.headers["set-cookie"]
    assert "ati_admin=" in cookie and "HttpOnly" in cookie and "Path=/admin" in cookie
    assert "SameSite=strict" in cookie
    await http.aclose()


async def test_login_requires_password_then_totp_and_rejects_reuse(
    app: Any,
    clock: Clock,
    root: AdminClient,
) -> None:
    http = client_for(app)
    wrong = await login(http, root.email, "yanlis-parola-yanlis")
    unknown = await login(http, "yok@example.com")
    assert wrong.status_code == unknown.status_code == 401 and wrong.json() == unknown.json()
    first = await login(http, root.email)
    assert first.json()["status"] == "totp_required"
    assert (await http.get("/admin/v1/auth/me")).status_code == 401  # parola tek başına yetmez
    code = clock.code(root.secret)
    ok = await http.post(
        "/admin/v1/auth/verify", json={"challenge": first.json()["challenge"], "code": code}
    )
    assert ok.status_code == 200
    assert (await http.get("/admin/v1/auth/me")).status_code == 200
    # Aynı kod ikinci kez kullanılamaz; doğrulama adımı belirteci de tek kullanımlık.
    second = await login(http, root.email)
    replay = await http.post(
        "/admin/v1/auth/verify", json={"challenge": second.json()["challenge"], "code": code}
    )
    assert replay.status_code == 401
    again = await http.post(
        "/admin/v1/auth/verify",
        json={"challenge": first.json()["challenge"], "code": clock.code(root.secret)},
    )
    assert again.status_code == 401
    await http.aclose()


async def test_recovery_code_is_single_use(app: Any, clock: Clock, root: AdminClient) -> None:
    http = client_for(app)
    challenge = (await login(http, root.email)).json()["challenge"]
    used = root.recovery_codes[0]
    ok = await http.post(
        "/admin/v1/auth/verify", json={"challenge": challenge, "recovery_code": used.lower()}
    )
    assert ok.status_code == 200
    assert (await http.get("/admin/v1/auth/me")).json()["recovery_codes_left"] == 9
    challenge = (await login(http, root.email)).json()["challenge"]
    reuse = await http.post(
        "/admin/v1/auth/verify", json={"challenge": challenge, "recovery_code": used}
    )
    assert reuse.status_code == 401
    await http.aclose()


async def test_lockout_after_failures(app: Any, clock: Clock, root: AdminClient, dsn: str) -> None:
    http = client_for(app)
    for _ in range(5):
        assert (await login(http, root.email, "yanlis-parola-yanlis")).status_code == 401
    locked = await login(http, root.email)  # doğru parola da reddedilir
    assert locked.status_code == 401
    with psycopg.connect(dsn) as conn:
        assert conn.execute(
            "SELECT locked_until > now() FROM admin_users WHERE id = %s", (root.id,)
        ).fetchone() == (True,)
        conn.execute(
            "UPDATE admin_users SET locked_until = now() - interval '1 second' WHERE id = %s",
            (root.id,),
        )
        conn.commit()
    challenge = (await login(http, root.email)).json()["challenge"]
    # Doğrulama adımında 5 hatalı kod: belirteç geçersizleşir.
    codes = [
        (
            await http.post(
                "/admin/v1/auth/verify", json={"challenge": challenge, "code": "000000"}
            )
        ).status_code
        for _ in range(6)
    ]
    assert set(codes) == {401}
    assert "admin.login_failed" in audit_actions(dsn) and "admin.verify_failed" in audit_actions(
        dsn
    )
    await http.aclose()


async def test_customer_session_cannot_reach_admin(app: Any, root: AdminClient) -> None:
    http = client_for(app)
    http.cookies.set("ati_session", "musteri-oturumu-" + "x" * 30)
    assert (await http.get("/admin/v1/stats")).status_code == 401
    await http.aclose()


async def test_logout_revokes_session(app: Any, root: AdminClient) -> None:
    assert (await root.http.post("/admin/v1/auth/logout")).status_code == 200
    assert (await root.http.get("/admin/v1/auth/me")).status_code == 401


# --- Paketler ---------------------------------------------------------------------------------


async def test_plans_price_and_activation(app: Any, root: AdminClient, dsn: str) -> None:
    http = root.http
    plans = (await http.get("/admin/v1/plans")).json()
    assert len(plans) == 16 and all(not p["is_active"] for p in plans)
    blocked = await http.patch("/admin/v1/plans/d30_1dev", json={"is_active": True})
    assert blocked.status_code == 409 and "Fiyatı" in blocked.json()["detail"]
    updated = await http.patch(
        "/admin/v1/plans/d30_1dev",
        json={"price_minor": 149900, "currency": "TRY", "is_active": True},
    )
    assert updated.status_code == 200 and updated.json()["is_active"] is True
    public = await http.get("/v1/plans")
    assert [(p["code"], p["price_minor"], p["currency"]) for p in public.json()] == [
        ("d30_1dev", 149900, "TRY")
    ]
    assert (await http.patch("/admin/v1/plans/yok", json={"price_minor": 1})).status_code == 404
    assert (
        await http.patch("/admin/v1/plans/d30_1dev", json={"currency": "tl"})
    ).status_code == 422
    with psycopg.connect(dsn) as conn:
        details = conn.execute(
            "SELECT details FROM audit_log WHERE action = 'admin.plan_updated' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert details and details[0]["before"]["price_minor"] is None
    assert details[0]["changes"] == {"price_minor": 149900, "currency": "TRY", "is_active": True}


# --- Lisanslar --------------------------------------------------------------------------------


async def test_license_lifecycle(
    app: Any, clock: Clock, root: AdminClient, dsn: str, factory: Any
) -> None:
    http = root.http
    customer = factory.customer("musteri@example.com")
    single = await http.post(
        "/admin/v1/licenses",
        json={"plan_code": "d30_1dev", "customer_email": "musteri@example.com"},
    )
    assert single.status_code == 200, single.text
    key, license_id = single.json()["key"], single.json()["id"]
    normalize(key)
    batch = await http.post(
        "/admin/v1/licenses/batch",
        json={"plan_code": "d90_2dev", "quantity": 5, "purpose": "sale_pool"},
    )
    assert batch.status_code == 200 and len(batch.json()["licenses"]) == 5
    with psycopg.connect(dsn) as conn:
        assert conn.execute(
            "SELECT count(*) FROM licenses WHERE status = 'ready_for_sale' AND batch_id IS NOT NULL"
        ).fetchone() == (5,)
        assert conn.execute(
            "SELECT customer_id FROM licenses WHERE id = %s", (license_id,)
        ).fetchone() == (customer,)

    found = (await http.get("/admin/v1/licenses", params={"q": key})).json()
    assert found["total"] == 1 and found["items"][0]["id"] == license_id
    by_email = (await http.get("/admin/v1/licenses", params={"q": "musteri@"})).json()
    assert by_email["total"] == 1
    assert (await http.get("/admin/v1/licenses", params={"status": "ready_for_sale"})).json()[
        "total"
    ] == 5

    frozen = await http.post(
        f"/admin/v1/licenses/{license_id}/freeze", json={"reason": "ödeme incelemesi"}
    )
    assert frozen.json()["status"] == "frozen"
    assert (
        await http.post(
            f"/admin/v1/licenses/{license_id}/extend", json={"days": 10, "reason": "jest"}
        )
    ).status_code == 409
    assert (await http.post(f"/admin/v1/licenses/{license_id}/unfreeze")).json()["status"] == "sold"
    extended = await http.post(
        f"/admin/v1/licenses/{license_id}/extend", json={"days": 10, "reason": "jest"}
    )
    assert extended.status_code == 200
    with psycopg.connect(dsn) as conn:
        assert conn.execute(
            "SELECT duration_days FROM licenses WHERE id = %s", (license_id,)
        ).fetchone() == (40,)
        conn.execute(
            "UPDATE licenses SET status = 'active', activated_at = now() - interval '50 days', "
            "expires_at = now() - interval '1 day', status_before_freeze = NULL WHERE id = %s",
            (license_id,),
        )
        conn.execute("UPDATE licenses SET status = 'expired' WHERE id = %s", (license_id,))
        conn.commit()
    revived = await http.post(
        f"/admin/v1/licenses/{license_id}/extend", json={"days": 30, "reason": "yenileme"}
    )
    assert revived.json()["status"] == "active"

    # Tam anahtar: güncel TOTP kodu gerekir.
    assert (
        await http.post(f"/admin/v1/licenses/{license_id}/reveal", json={"code": "000000"})
    ).status_code == 400
    shown = await http.post(
        f"/admin/v1/licenses/{license_id}/reveal", json={"code": clock.code(root.secret)}
    )
    assert shown.json() == {"key": key}

    cancelled = await http.post(f"/admin/v1/licenses/{license_id}/cancel", json={"reason": "iade"})
    assert cancelled.json()["status"] == "cancelled"
    assert (
        await http.post(f"/admin/v1/licenses/{license_id}/cancel", json={"reason": "iade"})
    ).status_code == 409
    detail = (await http.get(f"/admin/v1/licenses/{license_id}")).json()
    assert detail["status"] == "cancelled"
    admin_events = [e for e in detail["events"] if e["actor_type"] == "admin"]
    assert {e["to_status"] for e in admin_events} >= {"frozen", "cancelled"}
    lifetime = (await http.post("/admin/v1/licenses", json={"plan_code": "lifetime_1dev"})).json()[
        "id"
    ]
    assert (
        await http.post(
            f"/admin/v1/licenses/{lifetime}/extend", json={"days": 1, "reason": "x" * 3}
        )
    ).status_code == 409
    actions = audit_actions(dsn)
    for action in (
        "admin.license_generated",
        "admin.license_batch_generated",
        "admin.license_frozen",
        "admin.license_unfrozen",
        "admin.license_extended",
        "admin.license_key_revealed",
        "admin.license_cancelled",
    ):
        assert action in actions
    with psycopg.connect(dsn) as conn:
        dump = str(conn.execute("SELECT details FROM audit_log").fetchall())
    assert key not in dump  # anahtar denetim kaydına yazılmaz


async def test_pool_license_is_assigned_to_customer(
    root: AdminClient, dsn: str, factory: Any
) -> None:
    """E-postasız üretilen (satış havuzu) lisans sonradan müşteriye atanır ve etkinleşebilir olur."""
    http = root.http
    customer = factory.customer("havuz@example.com")
    pool = (await http.post("/admin/v1/licenses", json={"plan_code": "d30_1dev"})).json()["id"]
    path = f"/admin/v1/licenses/{pool}/assign"
    missing = await http.post(path, json={"customer_email": "yok@example.com"})
    assert missing.status_code == 404
    with psycopg.connect(dsn) as conn:
        conn.execute("UPDATE license_plans SET device_limit = 3 WHERE code = 'd30_1dev'")
        conn.commit()
    assigned = await http.post(path, json={"customer_email": "HAVUZ@example.com"})
    assert assigned.status_code == 200, assigned.text
    assert assigned.json() == {"id": pool, "status": "sold"}
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT customer_id, sold_at IS NOT NULL, device_limit FROM licenses WHERE id = %s",
            (pool,),
        ).fetchone()
    assert row == (customer, True, 3)  # paket koşulları satış anında güncellenir
    again = await http.post(path, json={"customer_email": "havuz@example.com"})
    assert again.status_code == 409  # yalnızca kimseye ait olmayan lisans atanır
    detail = (await http.get(f"/admin/v1/licenses/{pool}")).json()
    assert detail["customer_email"] == "havuz@example.com"
    assert any(e["to_status"] == "sold" and e["actor_type"] == "admin" for e in detail["events"])
    assert "admin.license_assigned" in audit_actions(dsn)


# --- Müşteriler ve cihazlar --------------------------------------------------------------------


async def test_block_customer_revokes_sessions_and_device_revoke(
    app: Any,
    root: AdminClient,
    dsn: str,
    factory: Any,
) -> None:
    http = root.http
    customer = factory.customer("engel@example.com")
    license_id = factory.license()
    _, item = factory.order(customer)
    factory.sell(license_id, customer, item)
    device = factory.device(customer)
    factory.activate(license_id, device)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO customer_sessions (customer_id, refresh_token_hash, client_kind, expires_at) "
            "VALUES (%s, %s, 'web', now() + interval '1 day')",
            (customer, b"s" * 32),
        )
        conn.commit()
    listed = (await http.get("/admin/v1/customers", params={"q": "engel"})).json()
    assert listed["total"] == 1 and listed["items"][0]["licenses"] == 1
    blocked = await http.post(
        f"/admin/v1/customers/{customer}/block", json={"reason": "dolandırıcılık şüphesi"}
    )
    assert blocked.status_code == 200
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT revoked_at IS NOT NULL FROM customer_sessions").fetchone() == (
            True,
        )
    assert (
        await http.post(f"/admin/v1/customers/{customer}/block", json={"reason": "tekrar"})
    ).status_code == 409
    assert (await http.post(f"/admin/v1/customers/{customer}/unblock")).status_code == 200
    detail = (await http.get(f"/admin/v1/customers/{customer}")).json()
    assert detail["status"] == "active" and len(detail["devices"]) == 1

    devices = (await http.get("/admin/v1/devices", params={"q": "engel"})).json()
    assert devices[0]["active_licenses"] == 1
    revoked = await http.post(
        f"/admin/v1/devices/{device}/revoke", json={"reason": "çalıntı bilgisayar"}
    )
    assert revoked.json() == {"revoked": True, "released_activations": 1}
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT deactivated_by::text FROM license_activations").fetchone() == (
            "admin",
        )


# --- Yönetici hesapları -----------------------------------------------------------------------


async def test_admin_management_and_self_protection(
    app: Any, clock: Clock, root: AdminClient
) -> None:
    http = root.http
    created = await http.post(
        "/admin/v1/admins",
        json={"email": "destek@example.com", "full_name": "Destek", "roles": ["support"]},
    )
    assert created.status_code == 200
    url = created.json()["invite_url"]
    assert url.startswith("http://localhost:3000/yonetim/davet?token=")
    duplicate = await http.post(
        "/admin/v1/admins",
        json={"email": "destek@example.com", "full_name": "Destek", "roles": ["support"]},
    )
    assert duplicate.status_code == 409
    bad_role = await http.post(
        "/admin/v1/admins", json={"email": "x@example.com", "full_name": "X", "roles": ["tanri"]}
    )
    assert bad_role.status_code == 422
    # Kendini kilitleme önlemleri.
    assert (await http.post(f"/admin/v1/admins/{root.id}/block")).status_code == 409
    assert (
        await http.put(f"/admin/v1/admins/{root.id}/roles", json={"roles": ["auditor"]})
    ).status_code == 409
    assert (await http.post(f"/admin/v1/admins/{root.id}/reset-2fa")).status_code == 409
    # Davet bağlantısıyla etkinleştirme, rol değiştirme, engelleme.
    token = parse_qs(urlparse(url).query)["token"][0]
    other = client_for(app)
    start = (await other.post("/admin/v1/auth/invite/start", json={"token": token})).json()
    secret = base64.b32decode(start["secret"] + "=" * (-len(start["secret"]) % 8))
    assert (
        await other.post(
            "/admin/v1/auth/invite/complete",
            json={"token": token, "password": ADMIN_PASSWORD, "code": clock.code(secret)},
        )
    ).status_code == 200
    admins = {a["email"]: a for a in (await http.get("/admin/v1/admins")).json()}
    target = admins["destek@example.com"]
    assert target["two_factor"] and target["roles"] == ["support"]
    assert (await other.get("/admin/v1/plans")).status_code == 403
    assert (
        await http.put(
            f"/admin/v1/admins/{target['id']}/roles", json={"roles": ["license_manager"]}
        )
    ).status_code == 200
    assert (
        await other.get("/admin/v1/licenses")
    ).status_code == 200  # yeni rolün yetkisi hemen geçerli
    assert (await http.post(f"/admin/v1/admins/{target['id']}/block")).status_code == 200
    assert (await other.get("/admin/v1/auth/me")).status_code == 401  # oturumu kapatıldı
    assert (await http.post(f"/admin/v1/admins/{target['id']}/unblock")).json()[
        "status"
    ] == "active"
    reset = await http.post(f"/admin/v1/admins/{target['id']}/reset-2fa")
    assert reset.status_code == 200 and "/yonetim/davet?token=" in reset.json()["invite_url"]
    roles = (await http.get("/admin/v1/roles")).json()
    assert {r["code"] for r in roles} == {
        "super_admin",
        "license_manager",
        "support",
        "finance",
        "auditor",
    }
    await other.aclose()


# --- Ayarlar ----------------------------------------------------------------------------------


async def test_payment_settings_secrets_are_write_only(
    app: Any, clock: Clock, root: AdminClient
) -> None:
    http = root.http
    initial = (await http.get("/admin/v1/settings/payment")).json()
    assert initial["provider"] == "none" and initial["live_allowed"] is False
    body = {
        "provider": "iyzico",
        "mode": "test",
        "secrets": {"api_key": "sandbox-api-1234", "secret_key": "sandbox-secret-9876"},
    }
    assert (
        await http.put("/admin/v1/settings/payment", json=body)
    ).status_code == 400  # TOTP gerekir
    saved = await http.put(
        "/admin/v1/settings/payment", json={**body, "code": clock.code(root.secret)}
    )
    assert saved.status_code == 200
    view = (await http.get("/admin/v1/settings/payment")).json()
    assert view["secrets"]["api_key"] == {
        "configured": True,
        "hint": "…1234",
        "updated_at": view["secrets"]["api_key"]["updated_at"],
    }
    assert "sandbox-api-1234" not in str(view)
    wrong_field = await http.put(
        "/admin/v1/settings/payment", json={"provider": "iyzico", "public": {"merchant_id": "1"}}
    )
    assert wrong_field.status_code == 422
    # Canlı mod bu dağıtımda kapalı (G3).
    live = await http.put(
        "/admin/v1/settings/payment",
        json={
            "provider": "iyzico",
            "mode": "live",
            "code": clock.code(root.secret),
            "confirm": "CANLI ÖDEMEYİ AÇ",
        },
    )
    assert live.status_code == 409 and "G3" in live.json()["detail"]
    async with app.state.db.connection() as conn:
        plain = await load_payment_secrets(conn, app.state.admin.box)
    assert plain["secrets"] == {"api_key": "sandbox-api-1234", "secret_key": "sandbox-secret-9876"}


async def test_live_payments_need_deployment_flag_phrase_and_keys(dsn: str, clock: Clock) -> None:
    application = create_app(admin_settings(dsn, payments_live_allowed=True))
    try:
        root = await activate_admin(application, clock, "kok@example.com", ["super_admin"])
        http = root.http
        no_phrase = await http.put(
            "/admin/v1/settings/payment",
            json={"provider": "paytr", "mode": "live", "code": clock.code(root.secret)},
        )
        assert no_phrase.status_code == 400
        missing = await http.put(
            "/admin/v1/settings/payment",
            json={
                "provider": "paytr",
                "mode": "live",
                "code": clock.code(root.secret),
                "confirm": "CANLI ÖDEMEYİ AÇ",
                "secrets": {"merchant_key": "live-key-xxxxxxxx"},
            },
        )
        assert missing.status_code == 409 and "merchant_salt" in missing.json()["detail"]
        live = await http.put(
            "/admin/v1/settings/payment",
            json={
                "provider": "paytr",
                "mode": "live",
                "code": clock.code(root.secret),
                "confirm": "CANLI ÖDEMEYİ AÇ",
                "public": {"merchant_id": "123456"},
                "secrets": {
                    "merchant_key": "live-key-xxxxxxxx",
                    "merchant_salt": "live-salt-xxxxxxx",
                },
            },
        )
        assert live.status_code == 200 and live.json()["mode"] == "live"
        assert "admin.payments_live_enabled" in audit_actions(dsn)
        await http.aclose()
    finally:
        await application.state.db.close()


async def test_company_settings(app: Any, root: AdminClient) -> None:
    http = root.http
    assert (await http.get("/admin/v1/settings/company")).json()["legal_name"] == ""
    bad = await http.put("/admin/v1/settings/company", json={"tax_number": "12ab"})
    assert bad.status_code == 422
    body = {
        "legal_name": "Örnek Yazılım A.Ş.",
        "tax_office": "Kadıköy",
        "tax_number": "1234567890",
        "address": "İstanbul",
        "email": "destek@canarslan.net.tr",
    }
    assert (await http.put("/admin/v1/settings/company", json=body)).status_code == 200
    assert (await http.get("/admin/v1/settings/company")).json()[
        "legal_name"
    ] == "Örnek Yazılım A.Ş."


# --- Denetim, raporlar, mesajlar ---------------------------------------------------------------


async def test_audit_reports_and_messages(app: Any, root: AdminClient, dsn: str) -> None:
    http = root.http
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO contact_messages (name, email, topic, message) "
            "VALUES ('Ayşe', 'ayse@example.com', 'support', 'Kurulumda yardım lazım lütfen')"
        )
        conn.commit()
    stats = (await http.get("/admin/v1/stats")).json()
    assert stats["new_messages"] == 1 and stats["customers"]["total"] == 0
    (message,) = (await http.get("/admin/v1/messages", params={"status": "new"})).json()
    assert (
        await http.post(f"/admin/v1/messages/{message['id']}/status", json={"status": "closed"})
    ).status_code == 200
    assert (await http.get("/admin/v1/messages", params={"status": "new"})).json() == []
    assert (await http.get("/admin/v1/reports/sales")).json() == []
    assert (await http.get("/admin/v1/reports/payments")).json() == []
    assert "licenses" in (await http.get("/admin/v1/reports/usage")).json()
    log = (await http.get("/admin/v1/audit", params={"action": "admin."})).json()
    assert {"admin.activated", "admin.message_status"} <= {e["action"] for e in log}
    verified = (await http.get("/admin/v1/audit/verify")).json()
    assert verified["intact"] is True and verified["entries"] >= 2


async def test_server_reset_recovers_forgotten_password_of_last_super_admin(
    app: Any,
    clock: Clock,
    dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Tek süper yönetici parolasını unuttu: sunucudaki ``ati-cloud-admin reset`` yeni davet
    bağlantısı verir; eski parola ve oturum geçersizleşir, yeni parola + doğrulama kurulur."""
    from admin_support import activate_admin
    from ati_cloud.admin import cli as admin_cli

    root = await activate_admin(app, clock, "kok@example.com", ["super_admin"])
    assert (await root.http.get("/admin/v1/auth/me")).status_code == 200
    monkeypatch.setenv("ATI_DATABASE_URL", dsn)
    monkeypatch.setenv("ATI_ADMIN_PUBLIC_URL", "https://admin.example.test")
    assert await admin_cli._reset("yok@example.com") == 1
    assert await admin_cli._reset("KOK@example.com") == 0
    link = capsys.readouterr().out.strip().splitlines()[-1]
    assert link.startswith("https://admin.example.test/yonetim/davet?token=")
    token = link.split("token=", 1)[1]

    assert (await root.http.get("/admin/v1/auth/me")).status_code == 401  # oturum kapandı
    fresh = client_for(app)
    old = await fresh.post(
        "/admin/v1/auth/login", json={"email": "kok@example.com", "password": ADMIN_PASSWORD}
    )
    assert old.status_code in (401, 403)  # davet tamamlanmadan giriş yok
    start = (await fresh.post("/admin/v1/auth/invite/start", json={"token": token})).json()
    secret = base64.b32decode(start["secret"] + "=" * (-len(start["secret"]) % 8))
    new_password = "Yepyeni-Yonetici-Parolasi-2026!"
    done = await fresh.post(
        "/admin/v1/auth/invite/complete",
        json={"token": token, "password": new_password, "code": clock.code(secret)},
    )
    assert done.status_code == 200, done.text
    me = (await fresh.get("/admin/v1/auth/me")).json()
    assert me["email"] == "kok@example.com" and "super_admin" in me["roles"]
    with psycopg.connect(dsn) as conn:
        actions = [r[0] for r in conn.execute("SELECT action FROM audit_log").fetchall()]
    assert "admin.admin_reset_from_server" in actions
    for client in (root.http, fresh):
        await client.aclose()
