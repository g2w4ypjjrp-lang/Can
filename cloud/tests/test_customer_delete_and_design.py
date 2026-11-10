"""Müşteri silme (KVKK: anonimleştirme) ve site tasarım modu. Gerçek PostgreSQL."""

from __future__ import annotations

from typing import Any

import httpx
import psycopg
import pytest

from admin_support import AdminClient, Clock, activate_admin


@pytest.fixture
async def root(app: Any, clock: Clock) -> AdminClient:
    return await activate_admin(app, clock, "kok@example.com", ["super_admin"])


@pytest.fixture
def public(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


async def test_delete_customer_anonymizes_and_cancels_licenses(
    root: AdminClient, clock: Clock, dsn: str, factory: Any
) -> None:
    customer = factory.customer("silinecek@example.com")
    license_id = factory.license()
    order_id, item = factory.order(customer)
    factory.sell(license_id, customer, item)
    device = factory.device(customer)
    factory.activate(license_id, device)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO customer_sessions (customer_id, refresh_token_hash, client_kind, "
            "expires_at) VALUES (%s, %s, 'web', now() + interval '1 day')",
            (customer, b"s" * 32),
        )
        conn.execute(
            "INSERT INTO email_outbox (dedupe_key, to_email, template, payload) "
            "VALUES ('d1', 'silinecek@example.com', 'account_exists', '{}')"
        )
    url = f"/admin/v1/customers/{customer}/delete"
    body = {"confirm_email": "silinecek@example.com", "reason": "KVKK silme talebi"}

    wrong_code = await root.http.post(url, json={**body, "code": "000000"})
    assert wrong_code.status_code == 400
    wrong_email = await root.http.post(
        url, json={**body, "confirm_email": "baska@example.com", "code": clock.code(root.secret)}
    )
    assert wrong_email.status_code == 422 and "eşleşmiyor" in wrong_email.json()["detail"]

    deleted = await root.http.post(url, json={**body, "code": clock.code(root.secret)})
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"status": "deleted", "licenses_cancelled": 1, "devices_revoked": 1}

    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT email::text, full_name, password_hash, status::text, deleted_at IS NOT NULL "
            "FROM customers WHERE id = %s",
            (customer,),
        ).fetchone()
        assert row is not None
        assert row[0] == f"silindi-{customer}@silindi.invalid"
        assert row[1:4] == (None, None, "deleted") and row[4]
        assert conn.execute(
            "SELECT status::text FROM licenses WHERE id = %s", (license_id,)
        ).fetchone() == ("cancelled",)
        assert conn.execute("SELECT revoked_at IS NOT NULL FROM devices").fetchone() == (True,)
        assert conn.execute("SELECT revoked_at IS NOT NULL FROM customer_sessions").fetchone() == (
            True,
        )
        assert conn.execute("SELECT count(*) FROM email_outbox").fetchone() == (0,)
        # Sipariş yasal saklama için kalır; kişisel veri yoktur.
        assert conn.execute(
            "SELECT count(*) FROM orders WHERE id = %s", (order_id,)
        ).fetchone() == (1,)
        audit = conn.execute(
            "SELECT details::text FROM audit_log WHERE action = 'admin.customer_deleted'"
        ).fetchone()
        assert audit is not None and "silinecek@example.com" not in audit[0]

    # Listeden kalkar, ikinci silme bulunamaz, aynı e-postayla yeniden kayıt mümkündür.
    listed = (await root.http.get("/admin/v1/customers", params={"q": "silin"})).json()
    assert listed["total"] == 0
    again = await root.http.post(url, json={**body, "code": clock.code(root.secret)})
    assert again.status_code == 404
    assert factory.customer("silinecek@example.com")


async def test_only_super_admin_can_delete_customers(app: Any, clock: Clock, factory: Any) -> None:
    support = await activate_admin(app, clock, "destek@example.com", ["support"])
    customer = factory.customer("korunan@example.com")
    response = await support.http.post(
        f"/admin/v1/customers/{customer}/delete",
        json={
            "confirm_email": "korunan@example.com",
            "reason": "deneme",
            "code": clock.code(support.secret),
        },
    )
    assert response.status_code == 403


async def test_site_design_is_chosen_by_admin(
    root: AdminClient, public: httpx.AsyncClient, dsn: str
) -> None:
    first = await public.get("/v1/site/appearance")
    assert first.json() == {"design": "okyanus"}
    assert first.headers["cache-control"] == "public, max-age=30"

    current = (await root.http.get("/admin/v1/settings/appearance")).json()
    codes = [d["code"] for d in current["designs"]]
    assert current["design"] == "okyanus"
    assert codes == ["okyanus", "zumrut", "gunbatimi", "altin", "grafit"]

    changed = await root.http.put("/admin/v1/settings/appearance", json={"design": "zumrut"})
    assert changed.status_code == 200 and changed.json()["design"] == "zumrut"
    assert (await public.get("/v1/site/appearance")).json() == {"design": "zumrut"}
    bad = await root.http.put("/admin/v1/settings/appearance", json={"design": "yok"})
    assert bad.status_code == 422

    # Veritabanında bozuk değer olsa bile site varsayılanla açılır.
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            'UPDATE system_settings SET value = \'{"design": "bilinmeyen"}\' '
            "WHERE key = 'appearance'"
        )
    assert (await public.get("/v1/site/appearance")).json() == {"design": "okyanus"}


async def test_design_change_requires_settings_permission(app: Any, clock: Clock) -> None:
    support = await activate_admin(app, clock, "destek2@example.com", ["support"])
    response = await support.http.put("/admin/v1/settings/appearance", json={"design": "altin"})
    assert response.status_code == 403
