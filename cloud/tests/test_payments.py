"""Aşama 17: ödeme → lisans teslimi.

Kabul kriterleri (docs/05):

* Sahte (imzasız/yanlış imzalı) bildirim hiçbir şeyi değiştirmez; kaydı tutulur.
* Aynı bildirim tekrar gelirse ikinci lisans üretilmez (idempotent).
* Eşzamanlı teslimler aynı havuz lisansını alamaz.
* Tutar uyuşmazlığında otomatik teslim yapılmaz; sipariş incelemeye düşer.
* İade (yönetici, TOTP) lisansı iptal eder.
* Üretimde test modu ve simülatör kapalı; canlı mod dağıtım kilidi (G3) olmadan açılmaz.

PayTR ve iyzico istek/imza biçimleri sahte HTTP katmanıyla (``httpx.MockTransport``) doğrulanır;
gerçek sağlayıcı test ortamıyla deneme, test hesabı bilgileri girildiğinde yapılır.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlencode

import httpx
import psycopg
import pytest
from psycopg.types.json import Jsonb

from admin_support import Clock, activate_admin
from ati_cloud.accounts import token_digest
from ati_cloud.licensing.service import Licensing
from ati_cloud.payments.providers import (
    Buyer,
    CheckoutRequest,
    InvalidSignature,
    IyzicoProvider,
    PaytrProvider,
    ProviderError,
)
from ati_cloud.payments.service import Payments

ORIGIN = "http://localhost:3000"
ARGON2_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNoaGFzaA"
BILLING = {
    "full_name": "Ayşe Yılmaz",
    "phone": "+90 532 000 00 00",
    "address": "Örnek Mah. Deneme Sok. No: 1 Kadıköy",
    "city": "İstanbul",
}


def checkout_body(plan: str = "d30_1dev", **extra: Any) -> dict[str, Any]:
    return {
        "plan_code": plan,
        "billing": BILLING,
        "accept_preinfo": True,
        "accept_contract": True,
        "accept_immediate_delivery": True,
        **extra,
    }


# --- Kurulum -----------------------------------------------------------------------------------


@pytest.fixture
def db(dsn: str) -> psycopg.Connection[Any]:
    conn = psycopg.connect(dsn, autocommit=True)
    yield conn  # type: ignore[misc]
    conn.close()


@pytest.fixture
async def shopper(app: Any, db: psycopg.Connection[Any]) -> AsyncIterator[Callable[..., Any]]:
    """Oturum açmış müşteri istemcisi üretir (kayıt akışı test_accounts'ta sınanır)."""
    clients: list[httpx.AsyncClient] = []

    async def make(email: str | None = None, verified: bool = True) -> Any:
        email = email or f"musteri-{uuid.uuid4().hex[:8]}@example.com"
        row = db.execute(
            "INSERT INTO customers (email, password_hash, full_name, email_verified_at) "
            "VALUES (%s, %s, 'Ayşe Yılmaz', CASE WHEN %s THEN now() END) RETURNING id",
            (email, ARGON2_HASH, verified),
        ).fetchone()
        assert row
        token = secrets.token_urlsafe(32)
        db.execute(
            "INSERT INTO customer_sessions (customer_id, refresh_token_hash, client_kind, "
            "expires_at) VALUES (%s, %s, 'web', now() + interval '1 day')",
            (row[0], token_digest(token)),
        )
        http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Origin": ORIGIN},
            cookies={"ati_session": token},
        )
        http.customer_id = row[0]  # type: ignore[attr-defined]
        http.email = email  # type: ignore[attr-defined]
        clients.append(http)
        return http

    yield make
    for client in clients:
        await client.aclose()


def set_payment(
    app: Any,
    db: psycopg.Connection[Any],
    provider: str,
    *,
    mode: str = "test",
    public: dict[str, str] | None = None,
    secret: dict[str, str] | None = None,
) -> None:
    box = app.state.admin.box
    sealed = {
        name: {
            "enc": base64.b64encode(
                box.seal(value.encode(), f"payment|{provider}|{name}")
            ).decode(),
            "hint": f"…{value[-4:]}",
            "updated_at": datetime.now(UTC).isoformat(),
        }
        for name, value in (secret or {}).items()
    }
    value = {"provider": provider, "mode": mode, "public": public or {}, "secrets": sealed}
    db.execute(
        "INSERT INTO system_settings (key, value) VALUES ('payment', %s) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (Jsonb(value),),
    )


def price(db: psycopg.Connection[Any], plan: str, minor: int, currency: str = "TRY") -> None:
    db.execute(
        "UPDATE license_plans SET price_minor = %s, currency = %s, is_active = true "
        "WHERE code = %s",
        (minor, currency, plan),
    )


def one(db: psycopg.Connection[Any], sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = db.execute(sql, params).fetchone()
    return None if row is None else row[0]


def audit_actions(db: psycopg.Connection[Any]) -> list[str]:
    return [r[0] for r in db.execute("SELECT action FROM audit_log ORDER BY id").fetchall()]


def order_licenses(db: psycopg.Connection[Any], order_no: int) -> list[tuple[Any, ...]]:
    return db.execute(
        "SELECT l.id, l.status::text, l.customer_id, l.serial FROM licenses l "
        "JOIN order_items i ON i.id = l.order_item_id JOIN orders o ON o.id = i.order_id "
        "WHERE o.order_no = %s ORDER BY l.serial",
        (order_no,),
    ).fetchall()


async def simulated_order(http: httpx.AsyncClient, plan: str = "d30_1dev") -> tuple[int, str]:
    response = await http.post("/v1/checkout", json=checkout_body(plan))
    assert response.status_code == 200, response.text
    url = response.json()["redirect_url"]
    assert "/odeme/test?oturum=" in url
    return response.json()["order_no"], parse_qs(url.split("?", 1)[1])["oturum"][0]


async def pay(http: httpx.AsyncClient, token: str, outcome: str = "success") -> dict[str, Any]:
    response = await http.post(
        "/v1/payments/simulator/complete", json={"token": token, "outcome": outcome}
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def signed_sim(app: Any, order_id: Any, amount: int, currency: str = "TRY") -> tuple[bytes, str]:
    payments: Payments = app.state.payments
    body = payments.simulator.build_webhook(
        order_id=str(order_id), outcome="success", amount_minor=amount, currency=currency
    )
    return body, payments.simulator.sign(body)


# --- Satışın açılması --------------------------------------------------------------------------


async def test_sales_closed_until_provider_is_configured(
    app: Any, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    price(db, "d30_1dev", 19990)
    http = await shopper()
    status = (await http.get("/v1/payments/status")).json()
    assert status["open"] is False and status["provider"] is None
    closed = await http.post("/v1/checkout", json=checkout_body())
    assert closed.status_code == 503 and closed.json()["detail"]["code"] == "payments_closed"
    # Anahtarları eksik PayTR de satışı açmaz.
    set_payment(app, db, "paytr", public={"merchant_id": "1"})
    assert (await http.get("/v1/payments/status")).json()["open"] is False
    set_payment(app, db, "simulator")
    status = (await http.get("/v1/payments/status")).json()
    assert status["open"] is True and status["test_mode"] is True
    assert status["provider"] == "Test simülatörü"


async def test_checkout_requires_verified_email_legal_consent_and_active_plan(
    app: Any, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    set_payment(app, db, "simulator")
    price(db, "d30_1dev", 19990)
    unverified = await shopper(verified=False)
    response = await unverified.post("/v1/checkout", json=checkout_body())
    assert response.status_code == 403 and response.json()["detail"]["code"] == "email_unverified"

    http = await shopper()
    for field in ("accept_preinfo", "accept_contract", "accept_immediate_delivery"):
        response = await http.post("/v1/checkout", json=checkout_body(**{field: False}))
        assert response.status_code == 422, field
        assert response.json()["detail"]["code"] == "legal_required"
    inactive = await http.post("/v1/checkout", json=checkout_body("d90_1dev"))
    assert inactive.status_code == 404
    foreign = await http.post(
        "/v1/checkout", json=checkout_body(), headers={"Origin": "https://kotu.example"}
    )
    assert foreign.status_code == 403
    anonymous = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": ORIGIN},
    )
    assert (await anonymous.post("/v1/checkout", json=checkout_body())).status_code == 401
    await anonymous.aclose()
    assert one(db, "SELECT count(*) FROM orders") == 0


# --- Başarılı satın alma -------------------------------------------------------------------------


async def test_simulated_purchase_delivers_exactly_one_license(
    app: Any, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    set_payment(app, db, "simulator")
    price(db, "d30_1dev", 19990)
    http = await shopper()
    order_no, token = await simulated_order(http)
    pending = (await http.get(f"/v1/me/orders/{order_no}")).json()
    assert pending["status"] == "pending" and pending["checkout_url"]
    session = (await http.get("/v1/payments/simulator/session", params={"token": token})).json()
    assert session["order_no"] == order_no and session["total_minor"] == 19990
    assert session["plan_name"] == "30 Gün - 1 Cihaz"

    done = await pay(http, token)
    assert done["redirect_url"].endswith(f"/odeme/sonuc?siparis={order_no}")
    order = (await http.get(f"/v1/me/orders/{order_no}")).json()
    assert order["status"] == "fulfilled" and order["under_review"] is False
    assert len(order["licenses"]) == 1 and order["licenses"][0].startswith("ATI-****")
    assert order["invoice_no"] == f"ATI{datetime.now(UTC).year}{order_no:09d}"
    assert order["checkout_url"] is None
    me = (await http.get("/v1/me")).json()
    assert [lic["status"] for lic in me["licenses"]] == ["sold"]
    licenses = order_licenses(db, order_no)
    assert len(licenses) == 1 and licenses[0][2] == http.customer_id  # type: ignore[attr-defined]

    # E-posta kuyruğunda yalnızca lisans kimliği var; anahtar yok.
    payload = one(db, "SELECT payload FROM email_outbox WHERE template = 'license_delivery'")
    assert payload["license_ids"] == [str(licenses[0][0])] and "ATI-" not in json.dumps(payload)
    snapshot = one(db, "SELECT billing_snapshot FROM orders WHERE order_no = %s", (order_no,))
    assert snapshot["legal"]["contract_accepted"] is True and snapshot["legal"]["version"]
    assert snapshot["billing"]["city"] == "İstanbul"
    actions = audit_actions(db)
    for action in ("order.created", "payment.succeeded", "order.fulfilled"):
        assert action in actions
    actors = {r[0] for r in db.execute("SELECT actor_type::text FROM license_events").fetchall()}
    assert actors == {"payment_webhook"}

    # Aynı bildirim (aynı olay kimliği) tekrar gelir → ikinci lisans yok.
    event = db.execute(
        "SELECT provider_event_id, payload FROM payment_webhook_events WHERE signature_valid"
    ).fetchone()
    assert event
    body = json.dumps(
        {
            "id": event[0],
            "type": "payment_succeeded",
            "order_id": event[1]["order_id"],
            "payment_id": event[1]["payment_id"],
            "amount_minor": 19990,
            "currency": "TRY",
        },
        separators=(",", ":"),
    ).encode()
    signature = app.state.payments.simulator.sign(body)
    for _ in range(3):
        again = await http.post(
            "/v1/payments/webhooks/simulator",
            content=body,
            headers={"x-simulator-signature": signature},
        )
        assert again.status_code == 200 and again.text == "OK"
    assert len(order_licenses(db, order_no)) == 1
    assert one(db, "SELECT attempts FROM payment_webhook_events WHERE signature_valid") == 3
    assert one(db, "SELECT count(*) FROM payments") == 1


async def test_failed_payment_marks_order_failed_without_license(
    app: Any, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    set_payment(app, db, "simulator")
    price(db, "d30_1dev", 19990)
    http = await shopper()
    order_no, token = await simulated_order(http)
    await pay(http, token, "failure")
    order = (await http.get(f"/v1/me/orders/{order_no}")).json()
    assert order["status"] == "failed" and order["licenses"] == []
    assert "payment.failed" in audit_actions(db)
    assert one(db, "SELECT count(*) FROM email_outbox WHERE template = 'license_delivery'") == 0


async def test_simulator_session_belongs_to_its_customer(
    app: Any, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    set_payment(app, db, "simulator")
    price(db, "d30_1dev", 19990)
    owner, other = await shopper(), await shopper()
    _, token = await simulated_order(owner)
    stolen = await other.post(
        "/v1/payments/simulator/complete", json={"token": token, "outcome": "success"}
    )
    assert stolen.status_code == 404
    forged = token.split(".")[0] + ".0123456789abcdef0123456789abcdef"
    response = await owner.get("/v1/payments/simulator/session", params={"token": forged})
    assert response.status_code == 400


# --- Sahte bildirim ------------------------------------------------------------------------------


async def test_forged_webhooks_change_nothing_and_are_recorded(
    app: Any, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    set_payment(app, db, "simulator")
    price(db, "d30_1dev", 19990)
    http = await shopper()
    order_no, _ = await simulated_order(http)
    order_id = one(db, "SELECT id FROM orders WHERE order_no = %s", (order_no,))
    body, _ = signed_sim(app, order_id, 19990)
    for headers in ({}, {"x-simulator-signature": "0" * 64}, {"x-simulator-signature": "zz"}):
        response = await http.post("/v1/payments/webhooks/simulator", content=body, headers=headers)
        assert response.status_code == 400
    # Geçerli imza başka bir gövdeye taşınamaz.
    _, good_sig = signed_sim(app, order_id, 19990)
    tampered = body.replace(b"19990", b"1")
    response = await http.post(
        "/v1/payments/webhooks/simulator",
        content=tampered,
        headers={"x-simulator-signature": good_sig},
    )
    assert response.status_code == 400
    assert one(db, "SELECT status::text FROM orders WHERE id = %s", (order_id,)) == "pending"
    assert order_licenses(db, order_no) == []
    assert one(db, "SELECT count(*) FROM payments") == 0
    rows = db.execute("SELECT signature_valid, processed_at FROM payment_webhook_events").fetchall()
    assert rows and all(valid is False and done is None for valid, done in rows)
    assert "payment.webhook_rejected" in audit_actions(db)
    # Bilinmeyen sağlayıcı yolu yok.
    unknown = await http.post("/v1/payments/webhooks/stripe", content=b"{}")
    assert unknown.status_code == 404
    # Yapılandırılmamış sağlayıcının bildirimi doğrulanamaz.
    paytr = await http.post(
        "/v1/payments/webhooks/paytr",
        content=b"merchant_oid=ATI100001&status=success&total_amount=19990&hash=x",
    )
    assert paytr.status_code == 400


async def test_valid_signature_for_unknown_order_is_logged_only(
    app: Any, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    set_payment(app, db, "simulator")
    http = await shopper()
    body, signature = signed_sim(app, uuid.uuid4(), 100)
    response = await http.post(
        "/v1/payments/webhooks/simulator",
        content=body,
        headers={"x-simulator-signature": signature},
    )
    assert response.status_code == 200
    assert "payment.unknown_order" in audit_actions(db)
    assert one(db, "SELECT count(*) FROM payments") == 0


# --- Tutar uyuşmazlığı ve inceleme ------------------------------------------------------------------


async def test_amount_or_currency_mismatch_goes_to_review_without_license(
    app: Any, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    set_payment(app, db, "simulator")
    price(db, "d30_1dev", 19990)
    http = await shopper()
    for amount, currency in ((100, "TRY"), (19990, "USD")):
        order_no, _ = await simulated_order(http)
        order_id = one(db, "SELECT id FROM orders WHERE order_no = %s", (order_no,))
        body, signature = signed_sim(app, order_id, amount, currency)
        response = await http.post(
            "/v1/payments/webhooks/simulator",
            content=body,
            headers={"x-simulator-signature": signature},
        )
        assert response.status_code == 200
        row = db.execute(
            "SELECT status::text, review_reason FROM orders WHERE id = %s", (order_id,)
        ).fetchone()
        assert row == ("paid", "amount_mismatch"), (amount, currency)
        assert order_licenses(db, order_no) == []
        order = (await http.get(f"/v1/me/orders/{order_no}")).json()
        assert order["under_review"] is True
    assert audit_actions(db).count("payment.needs_review") == 2


async def test_second_successful_payment_for_same_order_is_flagged(
    app: Any, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    set_payment(app, db, "simulator")
    price(db, "d30_1dev", 19990)
    http = await shopper()
    order_no, token = await simulated_order(http)
    await pay(http, token)
    order_id = one(db, "SELECT id FROM orders WHERE order_no = %s", (order_no,))
    # Siparişin teslim edilmiş olması tekrar ödemede ikinci lisansı zaten engeller; teslim
    # öncesi ikinci tahsilat ise incelemeye düşer.
    db.execute("UPDATE orders SET status = 'paid' WHERE id = %s", (order_id,))
    body, signature = signed_sim(app, order_id, 19990)
    response = await http.post(
        "/v1/payments/webhooks/simulator",
        content=body,
        headers={"x-simulator-signature": signature},
    )
    assert response.status_code == 200
    assert one(db, "SELECT review_reason FROM orders WHERE id = %s", (order_id,)) == (
        "duplicate_payment"
    )
    assert len(order_licenses(db, order_no)) == 1


# --- Havuz ve eşzamanlılık ------------------------------------------------------------------------


async def _pool(app: Any, dsn: str, plan: str, count: int) -> list[str]:
    licensing: Licensing = app.state.licensing
    ids = []
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        conn.row_factory = psycopg.rows.dict_row  # type: ignore[assignment]
        for _ in range(count):
            license_id, _ = await licensing.issue(conn, plan_code=plan)  # type: ignore[arg-type]
            ids.append(license_id)
    return ids


async def test_pool_licenses_are_sold_first_and_never_twice(
    app: Any, dsn: str, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    set_payment(app, db, "simulator")
    price(db, "d30_1dev", 19990)
    pool = await _pool(app, dsn, "d30_1dev", 3)
    customers = [await shopper() for _ in range(5)]
    orders = [await simulated_order(c) for c in customers]
    payments: Payments = app.state.payments
    events = []
    for order_no, _ in orders:
        order_id = one(db, "SELECT id FROM orders WHERE order_no = %s", (order_no,))
        body, signature = signed_sim(app, order_id, 19990)
        events.append(
            payments.handle_webhook(
                "simulator", {"x-simulator-signature": signature}, body, "127.0.0.1"
            )
        )
    replies = await asyncio.gather(*events)
    assert all(r.status == 200 for r in replies)
    sold = [order_licenses(db, order_no) for order_no, _ in orders]
    assert all(len(rows) == 1 for rows in sold)
    ids = [str(rows[0][0]) for rows in sold]
    assert len(set(ids)) == 5
    assert set(pool) <= set(ids)  # önce havuz tükendi, kalan 2 lisans yeni üretildi
    assert one(db, "SELECT count(*) FROM licenses WHERE status = 'ready_for_sale'") == 0


async def test_same_event_delivered_concurrently_yields_one_license(
    app: Any, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    set_payment(app, db, "simulator")
    price(db, "d30_1dev", 19990)
    http = await shopper()
    order_no, _ = await simulated_order(http)
    order_id = one(db, "SELECT id FROM orders WHERE order_no = %s", (order_no,))
    body, signature = signed_sim(app, order_id, 19990)
    payments: Payments = app.state.payments
    replies = await asyncio.gather(
        *[
            payments.handle_webhook(
                "simulator", {"x-simulator-signature": signature}, body, "127.0.0.1"
            )
            for _ in range(6)
        ]
    )
    assert all(r.status == 200 for r in replies)
    assert len(order_licenses(db, order_no)) == 1
    assert one(db, "SELECT count(*) FROM email_outbox WHERE template = 'license_delivery'") == 1
    assert one(db, "SELECT count(*) FROM invoices") == 1


# --- Deneme paketi ------------------------------------------------------------------------------


async def test_free_trial_skips_provider_and_is_once_per_customer(
    app: Any, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    price(db, "trial_7d", 0)  # sağlayıcı yokken de ücretsiz deneme alınabilir
    http = await shopper()
    first = await http.post("/v1/checkout", json=checkout_body("trial_7d"))
    assert first.status_code == 200, first.text
    order_no = first.json()["order_no"]
    assert first.json()["redirect_url"].endswith(f"/odeme/sonuc?siparis={order_no}")
    order = (await http.get(f"/v1/me/orders/{order_no}")).json()
    assert order["status"] == "fulfilled" and len(order["licenses"]) == 1
    assert one(db, "SELECT payment_provider FROM orders WHERE order_no = %s", (order_no,)) == (
        "free"
    )
    again = await http.post("/v1/checkout", json=checkout_body("trial_7d"))
    assert again.status_code == 409 and again.json()["detail"]["code"] == "trial_used"
    other = await shopper()
    assert (await other.post("/v1/checkout", json=checkout_body("trial_7d"))).status_code == 200


# --- İade ----------------------------------------------------------------------------------------


async def test_refund_requires_permission_and_totp_and_cancels_licenses(
    app: Any, clock: Clock, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    set_payment(app, db, "simulator")
    price(db, "d30_1dev", 19990)
    http = await shopper()
    order_no, token = await simulated_order(http)
    await pay(http, token)
    order_id = one(db, "SELECT id FROM orders WHERE order_no = %s", (order_no,))
    support = await activate_admin(app, clock, "destek@example.com", ["support"])
    finance = await activate_admin(app, clock, "finans@example.com", ["finance"])
    url = f"/admin/v1/orders/{order_id}/refund"
    body = {"reason": "Müşteri talebi", "license_action": "cancel"}
    assert (await support.http.post(url, json=body)).status_code == 403
    assert (await finance.http.post(url, json=body)).status_code == 400  # TOTP yok
    detail = (await support.http.get(f"/admin/v1/orders/{order_id}")).json()
    assert detail["status"] == "fulfilled" and len(detail["licenses"]) == 1

    partial = await finance.http.post(
        url,
        json={**body, "amount_minor": 5000, "license_action": "keep",
              "code": clock.code(finance.secret)},
    )  # fmt: skip
    assert partial.status_code == 200, partial.text
    assert partial.json()["payment_status"] == "partially_refunded"
    assert order_licenses(db, order_no)[0][1] == "sold"
    too_much = await finance.http.post(
        url, json={**body, "amount_minor": 15000, "code": clock.code(finance.secret)}
    )
    assert too_much.status_code == 409
    rest = await finance.http.post(url, json={**body, "code": clock.code(finance.secret)})
    assert rest.status_code == 200, rest.text
    assert rest.json()["amount_minor"] == 14990 and rest.json()["payment_status"] == "refunded"
    assert order_licenses(db, order_no)[0][1] == "cancelled"
    assert one(db, "SELECT status::text FROM orders WHERE id = %s", (order_id,)) == "refunded"
    detail = (await finance.http.get(f"/admin/v1/orders/{order_id}")).json()
    assert [r["status"] for r in detail["refunds"]] == ["succeeded", "succeeded"]
    assert detail["refunds"][0]["requested_by"] == "finans@example.com"
    none_left = await finance.http.post(url, json={**body, "code": clock.code(finance.secret)})
    assert none_left.status_code == 409
    actions = audit_actions(db)
    assert actions.count("payment.refunded") == 2 and "payment.refund_requested" in actions
    cancel_actor = one(
        db,
        "SELECT actor_type::text FROM license_events WHERE to_status = 'cancelled'",
    )
    assert cancel_actor == "admin"
    for client in (support, finance):
        await client.http.aclose()


# --- PayTR ----------------------------------------------------------------------------------------

PAYTR = {
    "merchant_id": "123456",
    "merchant_key": "paytr-key-abcdefgh",
    "merchant_salt": "salt-1234",
}


def paytr_hash(text: str) -> str:
    digest = hmac.new(PAYTR["merchant_key"].encode(), text.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def test_paytr_token_and_callback_signature() -> None:
    provider = PaytrProvider(
        merchant_id=PAYTR["merchant_id"],
        merchant_key=PAYTR["merchant_key"],
        merchant_salt=PAYTR["merchant_salt"],
        test_mode=True,
    )
    request = CheckoutRequest(
        order_id=str(uuid.uuid4()), order_no=100042, amount_minor=19990, currency="TRY",
        item_name="30 Gün - 1 Cihaz", plan_code="d30_1dev",
        buyer=Buyer(customer_id="c", email="a@example.com", full_name="Ayşe Yılmaz",
                    phone="5320000000", address="Adres 1", city="İstanbul", country="Türkiye",
                    ip="203.0.113.5"),
        success_url="https://canarslan.net.tr/odeme/sonuc?siparis=100042",
        fail_url="https://canarslan.net.tr/odeme/sonuc?siparis=100042",
        callback_url="https://api.canarslan.net.tr/v1/payments/return/paytr",
    )  # fmt: skip
    fields = provider.token_fields(request)
    assert fields["merchant_oid"] == "ATI100042" and fields["payment_amount"] == "19990"
    assert fields["currency"] == "TL" and fields["test_mode"] == "1"
    basket = json.loads(base64.b64decode(fields["user_basket"]))
    assert basket == [["30 Gün - 1 Cihaz", "199.90", 1]]
    expected = paytr_hash(
        "123456" + "203.0.113.5" + "ATI100042" + "a@example.com" + "19990"
        + fields["user_basket"] + "1" + "0" + "TL" + "1" + PAYTR["merchant_salt"]
    )  # fmt: skip
    assert fields["paytr_token"] == expected

    form = {
        "merchant_oid": "ATI100042",
        "status": "success",
        "total_amount": "19990",
        "payment_amount": "19990",
        "currency": "TL",
    }
    form["hash"] = paytr_hash("ATI100042" + PAYTR["merchant_salt"] + "success" + "19990")
    event = provider.parse_webhook({}, urlencode(form).encode())
    assert event.event_type == "payment_succeeded" and event.order_ref == "ATI100042"
    assert event.amount_minor == 19990 and event.currency == "TRY"
    for key, value in (("status", "failed"), ("total_amount", "1"), ("hash", "AAAA")):
        with pytest.raises(InvalidSignature):
            provider.parse_webhook({}, urlencode({**form, key: value}).encode())


async def test_paytr_checkout_and_callback_through_api(
    app: Any, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    set_payment(
        app, db, "paytr", public={"merchant_id": PAYTR["merchant_id"]},
        secret={"merchant_key": PAYTR["merchant_key"], "merchant_salt": PAYTR["merchant_salt"]},
    )  # fmt: skip
    price(db, "d30_1dev", 19990)
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/odeme/api/get-token"
        seen.append({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
        return httpx.Response(200, json={"status": "success", "token": "ifr-token-1"})

    payments: Payments = app.state.payments
    payments.transports["paytr"] = httpx.MockTransport(handler)
    http = await shopper()
    response = await http.post("/v1/checkout", json=checkout_body())
    assert response.status_code == 200, response.text
    order_no = response.json()["order_no"]
    assert response.json()["redirect_url"] == "https://www.paytr.com/odeme/guvenli/ifr-token-1"
    sent = seen[0]
    assert sent["merchant_oid"] == f"ATI{order_no}" and sent["test_mode"] == "1"
    assert sent["merchant_ok_url"].endswith(f"/odeme/sonuc?siparis={order_no}")
    assert sent["email"] == http.email  # type: ignore[attr-defined]

    oid = f"ATI{order_no}"
    form = {"merchant_oid": oid, "status": "success", "total_amount": "19990",
            "payment_amount": "19990", "currency": "TL", "test_mode": "1"}  # fmt: skip
    bad = await http.post(
        "/v1/payments/webhooks/paytr", content=urlencode({**form, "hash": "AAAA"}).encode()
    )
    assert bad.status_code == 400
    form["hash"] = paytr_hash(oid + PAYTR["merchant_salt"] + "success" + "19990")
    for _ in range(2):  # PayTR "OK" alana kadar yeniden dener
        ok = await http.post("/v1/payments/webhooks/paytr", content=urlencode(form).encode())
        assert ok.status_code == 200 and ok.text == "OK"
    assert len(order_licenses(db, order_no)) == 1
    assert (await http.get(f"/v1/me/orders/{order_no}")).json()["status"] == "fulfilled"

    # PayTR ulaşılamazsa sipariş başarısız, müşteriye anlaşılır hata.
    payments.transports["paytr"] = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"status": "failed", "reason": "hata"})
    )
    failed = await http.post("/v1/checkout", json=checkout_body())
    assert failed.status_code == 502 and failed.json()["detail"]["code"] == "provider_error"
    assert "payment.checkout_failed" in audit_actions(db)


# --- iyzico ----------------------------------------------------------------------------------------

IYZICO = {"api_key": "sandbox-api-key-1", "secret_key": "sandbox-secret-key-1"}


def iyzico_signature_ok(request: httpx.Request) -> bool:
    auth = request.headers["authorization"]
    assert auth.startswith("IYZWSv2 ")
    decoded = base64.b64decode(auth.removeprefix("IYZWSv2 ")).decode()
    parts = dict(p.split(":", 1) for p in decoded.split("&"))
    expected = hmac.new(
        IYZICO["secret_key"].encode(),
        (parts["randomKey"] + request.url.path + request.content.decode()).encode(),
        hashlib.sha256,
    ).hexdigest()
    return parts["apiKey"] == IYZICO["api_key"] and hmac.compare_digest(
        parts["signature"], expected
    )


async def test_iyzico_checkout_return_and_reconcile(
    app: Any, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    set_payment(app, db, "iyzico", secret=IYZICO)
    price(db, "d30_1dev", 19990)
    state: dict[str, Any] = {"basket": None, "status": "SUCCESS", "price": "199.90"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "sandbox-api.iyzipay.com"
        assert iyzico_signature_ok(request)
        body = json.loads(request.content)
        if request.url.path == IyzicoProvider.INIT:
            state["basket"] = body["basketId"]
            assert body["price"] == "199.90" and body["currency"] == "TRY"
            assert body["callbackUrl"].endswith("/v1/payments/return/iyzico")
            return httpx.Response(
                200,
                json={"status": "success", "token": f"tok-{body['basketId'][:8]}",
                      "paymentPageUrl": "https://sandbox-cpp.iyzipay.com/?token=x"},
            )  # fmt: skip
        assert request.url.path == IyzicoProvider.DETAIL
        return httpx.Response(
            200,
            json={"status": "success", "paymentStatus": state["status"],
                  "paidPrice": state["price"], "currency": "TRY", "basketId": state["basket"],
                  "paymentId": f"pay-{body['token']}"},
        )  # fmt: skip

    payments: Payments = app.state.payments
    payments.transports["iyzico"] = httpx.MockTransport(handler)
    http = await shopper()
    response = await http.post("/v1/checkout", json=checkout_body())
    assert response.status_code == 200, response.text
    assert response.json()["redirect_url"] == "https://sandbox-cpp.iyzipay.com/?token=x"
    order_no = response.json()["order_no"]
    token = one(db, "SELECT provider_checkout_id FROM orders WHERE order_no = %s", (order_no,))

    back = await http.post(
        "/v1/payments/return/iyzico",
        content=urlencode({"token": token}).encode(),
        headers={"content-type": "application/x-www-form-urlencoded", "Origin": "null"},
    )
    assert back.status_code == 303
    assert back.headers["location"].endswith(f"/odeme/sonuc?siparis={order_no}")
    assert len(order_licenses(db, order_no)) == 1
    # Tarayıcı geri dönmese de mutabakat sonucu alır; tekrar sorgu ikinci lisans üretmez.
    order_id = one(db, "SELECT id FROM orders WHERE order_no = %s", (order_no,))
    assert (await payments.reconcile(order_id))["result"] == "settled"

    # Sağlayıcının bildirdiği tutar farklıysa teslim yok.
    second = await http.post("/v1/checkout", json=checkout_body())
    second_no = second.json()["order_no"]
    state["price"] = "1.00"
    second_id = one(db, "SELECT id FROM orders WHERE order_no = %s", (second_no,))
    assert (await payments.reconcile(second_id))["result"] == "needs_review"
    assert order_licenses(db, second_no) == []
    # Bilinmeyen belirteç: siparişsiz sonuç sayfası, hiçbir şey değişmez.
    lost = await http.post("/v1/payments/return/iyzico", content=b"token=bilinmeyen-belirtec-123")
    assert lost.status_code == 303 and lost.headers["location"].endswith("/odeme/sonuc")


async def test_iyzico_provider_errors_are_reported() -> None:
    provider = IyzicoProvider(
        api_key="k", secret_key="s", test_mode=False,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"status": "failure", "errorMessage": "x"})
        ),
    )  # fmt: skip
    assert provider.base_url == IyzicoProvider.LIVE
    with pytest.raises(ProviderError):
        await provider.refund(
            provider_payment_id="1", amount_minor=100, currency="TRY", order_ref="o"
        )
    with pytest.raises(InvalidSignature):
        await provider.retrieve("tok")


# --- Üretim ve canlı mod kilitleri -------------------------------------------------------------------


async def test_production_closes_test_mode_and_simulator_and_live_needs_g3(
    app: Any, db: psycopg.Connection[Any], shopper: Callable[..., Any], clock: Clock
) -> None:
    price(db, "d30_1dev", 19990)
    payments: Payments = app.state.payments
    http = await shopper()
    set_payment(app, db, "simulator")
    assert (await http.get("/v1/payments/status")).json()["open"] is True

    payments.settings = payments.settings.model_copy(update={"environment": "production"})
    assert (await http.get("/v1/payments/status")).json()["open"] is False
    assert (await http.post("/v1/checkout", json=checkout_body())).status_code == 503
    body, signature = signed_sim(app, uuid.uuid4(), 100)
    sim = await http.post(
        "/v1/payments/webhooks/simulator",
        content=body,
        headers={"x-simulator-signature": signature},
    )
    assert sim.status_code == 404
    session = await http.get("/v1/payments/simulator/session", params={"token": "x" * 40})
    assert session.status_code == 404

    paytr_secrets = {"merchant_key": PAYTR["merchant_key"], "merchant_salt": PAYTR["merchant_salt"]}
    set_payment(app, db, "paytr", public={"merchant_id": "1"}, secret=paytr_secrets)
    assert (await http.get("/v1/payments/status")).json()["open"] is False  # üretimde test modu
    set_payment(app, db, "paytr", mode="live", public={"merchant_id": "1"}, secret=paytr_secrets)
    assert (await http.get("/v1/payments/status")).json()["open"] is False  # G3 kilidi kapalı
    payments.settings = payments.settings.model_copy(update={"payments_live_allowed": True})
    status = (await http.get("/v1/payments/status")).json()
    assert status["open"] is True and status["test_mode"] is False

    # Panel de simülatörü üretimde reddeder.
    admin = await activate_admin(app, clock, "kok@example.com", ["super_admin"])
    app.state.admin.settings = app.state.admin.settings.model_copy(
        update={"environment": "production"}
    )
    rejected = await admin.http.put(
        "/admin/v1/settings/payment", json={"provider": "simulator", "mode": "test"}
    )
    assert rejected.status_code == 409
    view = (await admin.http.get("/admin/v1/settings/payment")).json()
    assert "simulator" not in view["providers"]
    await admin.http.aclose()


async def test_admin_order_list_filters(
    app: Any, clock: Clock, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    set_payment(app, db, "simulator")
    price(db, "d30_1dev", 19990)
    http = await shopper("filtre@example.com")
    paid_no, token = await simulated_order(http)
    await pay(http, token)
    pending_no, _ = await simulated_order(http)
    admin = await activate_admin(app, clock, "denetci@example.com", ["auditor"])
    rows = (await admin.http.get("/admin/v1/orders", params={"status": "pending"})).json()
    assert [r["order_no"] for r in rows] == [pending_no]
    rows = (await admin.http.get("/admin/v1/orders", params={"q": str(paid_no)})).json()
    assert [r["order_no"] for r in rows] == [paid_no] and rows[0]["plan_name"]
    rows = (await admin.http.get("/admin/v1/orders", params={"q": "filtre@"})).json()
    assert {r["order_no"] for r in rows} == {paid_no, pending_no}
    assert (await admin.http.get("/admin/v1/orders", params={"review": "true"})).json() == []
    seller = (await http.get("/v1/legal/seller")).json()
    assert set(seller) >= {"legal_name", "mersis", "address"}
    await admin.http.aclose()
