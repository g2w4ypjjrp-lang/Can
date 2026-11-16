"""Lemon Squeezy (satıcı adına satış): ödeme oturumu, imzalı bildirim → lisans, sahte ve test
bildirimlerinin reddi, iade isteği. Sağlayıcı HTTP istekleri ``httpx.MockTransport`` ile yakalanır.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import psycopg
import pytest

from ati_cloud.payments.providers import (
    Buyer,
    CheckoutRequest,
    InvalidSignature,
    LemonSqueezyProvider,
    ProviderError,
)
from ati_cloud.payments.service import Payments
from test_payments import (  # noqa: F401 - pytest fikstürleri
    audit_actions,
    checkout_body,
    db,
    order_licenses,
    price,
    set_payment,
    shopper,
)

LS = {"api_key": "ls-api-key-test-123456", "signing_secret": "ls-signing-secret-1"}
PUBLIC = {"store_id": "12345", "variant_id": "67890"}


def provider(test_mode: bool = True, transport: Any = None) -> LemonSqueezyProvider:
    return LemonSqueezyProvider(
        api_key=LS["api_key"], signing_secret=LS["signing_secret"], store_id=PUBLIC["store_id"],
        variant_id=PUBLIC["variant_id"], test_mode=test_mode, transport=transport,
    )  # fmt: skip


def webhook(
    order_id: str, *, event: str = "order_created", status: str = "paid", total: int = 19990,
    currency: str = "TRY", test_mode: bool = True, ls_id: str = "4321",
) -> tuple[dict[str, str], bytes]:  # fmt: skip
    body = json.dumps(
        {
            "meta": {"event_name": event, "custom_data": {"order_id": order_id}},
            "data": {
                "type": "orders",
                "id": ls_id,
                "attributes": {
                    "status": status, "total": total, "currency": currency,
                    "test_mode": test_mode, "identifier": str(uuid.uuid4()),
                },
            },
        }
    ).encode()  # fmt: skip
    signature = hmac.new(LS["signing_secret"].encode(), body, hashlib.sha256).hexdigest()
    return {"x-signature": signature, "x-event-name": event}, body


def request(order_id: str) -> CheckoutRequest:
    return CheckoutRequest(
        order_id=order_id, order_no=100077, amount_minor=19990, currency="TRY",
        item_name="30 Gün - 1 Cihaz", plan_code="d30_1dev",
        buyer=Buyer(customer_id="c", email="a@example.com", full_name="Ayşe Yılmaz",
                    phone="5320000000", address="Adres 1", city="İstanbul", country="Türkiye",
                    ip="203.0.113.5"),
        success_url="https://canarslan.net.tr/odeme/sonuc?siparis=100077",
        fail_url="https://canarslan.net.tr/odeme/sonuc?siparis=100077",
        callback_url="https://api.canarslan.net.tr/v1/payments/webhooks/lemonsqueezy",
    )  # fmt: skip


async def test_checkout_request_and_webhook_signature() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(
            201, json={"data": {"type": "checkouts", "id": "chk-1",
                                "attributes": {"url": "https://shop.lemonsqueezy.com/checkout/c/chk-1"}}},
        )  # fmt: skip

    order_id = str(uuid.uuid4())
    session = await provider(transport=httpx.MockTransport(handler)).create_checkout(
        request(order_id)
    )
    assert session.redirect_url == "https://shop.lemonsqueezy.com/checkout/c/chk-1"
    sent = seen[0]
    assert sent.url.path == "/v1/checkouts"
    assert sent.headers["authorization"] == f"Bearer {LS['api_key']}"
    assert sent.headers["content-type"] == "application/vnd.api+json"
    attrs = json.loads(sent.content)["data"]["attributes"]
    assert attrs["custom_price"] == 19990 and attrs["test_mode"] is True
    assert attrs["checkout_data"]["custom"]["order_id"] == order_id
    assert attrs["product_options"]["redirect_url"].endswith("siparis=100077")
    rel = json.loads(sent.content)["data"]["relationships"]
    assert rel["store"]["data"]["id"] == "12345" and rel["variant"]["data"]["id"] == "67890"

    headers, body = webhook(order_id)
    event = provider().parse_webhook(headers, body)
    assert event.event_type == "payment_succeeded" and event.order_ref == order_id
    assert event.amount_minor == 19990 and event.currency == "TRY"
    # İmza yanlış ya da gövde değiştirilmişse reddedilir.
    with pytest.raises(InvalidSignature):
        provider().parse_webhook({"x-signature": "0" * 64}, body)
    with pytest.raises(InvalidSignature):
        provider().parse_webhook(headers, body.replace(b"19990", b"1"))
    # Canlı modda test ödemesi asla kabul edilmez.
    with pytest.raises(InvalidSignature):
        provider(test_mode=False).parse_webhook(headers, body)
    # Başka olaylar ve bekleyen ödeme yok sayılır.
    h2, b2 = webhook(order_id, event="subscription_created")
    assert provider().parse_webhook(h2, b2).event_type == "ignored"
    h3, b3 = webhook(order_id, status="pending")
    assert provider().parse_webhook(h3, b3).event_type == "ignored"
    h4, b4 = webhook(order_id, status="failed")
    assert provider().parse_webhook(h4, b4).event_type == "payment_failed"


async def test_refund_request_and_errors() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/orders/4321/refund"
        assert json.loads(req.content)["data"]["attributes"]["amount"] == 5000
        return httpx.Response(200, json={"data": {"type": "orders", "id": "4321",
                                                  "attributes": {"status": "partial_refund"}}})  # fmt: skip

    ref = await provider(transport=httpx.MockTransport(handler)).refund(
        provider_payment_id="4321", amount_minor=5000, currency="TRY", order_ref="x"
    )
    assert ref.startswith("4321:refund:5000")
    failing = provider(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(422, json={"errors": [{"detail": "Already refunded"}]})
        )
    )
    with pytest.raises(ProviderError, match="Already refunded"):
        await failing.refund(
            provider_payment_id="4321", amount_minor=1, currency="TRY", order_ref="x"
        )


async def test_lemonsqueezy_checkout_and_webhook_through_api(
    app: Any,
    db: psycopg.Connection[Any],  # noqa: F811
    shopper: Callable[..., Any],  # noqa: F811
) -> None:
    # Eksik/yanlış yapılandırmada satış kapalı (varyant numarası rakam olmalı).
    set_payment(
        app, db, "lemonsqueezy", public={"store_id": "12345", "variant_id": "abc"}, secret=LS
    )
    price(db, "d30_1dev", 19990)
    http = await shopper()
    assert (await http.get("/v1/payments/status")).json()["open"] is False

    set_payment(app, db, "lemonsqueezy", public=PUBLIC, secret=LS)
    seen: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        chk = f"chk-{len(seen)}"
        return httpx.Response(201, json={"data": {"type": "checkouts", "id": chk,
                                                  "attributes": {"url": f"https://x.lemonsqueezy.com/c/{chk}"}}})  # fmt: skip

    payments: Payments = app.state.payments
    payments.transports["lemonsqueezy"] = httpx.MockTransport(handler)
    response = await http.post("/v1/checkout", json=checkout_body())
    assert response.status_code == 200, response.text
    assert response.json()["redirect_url"] == "https://x.lemonsqueezy.com/c/chk-1"
    order_no = response.json()["order_no"]
    order_id = seen[0]["data"]["attributes"]["checkout_data"]["custom"]["order_id"]

    headers, body = webhook(order_id)
    bad = await http.post("/v1/payments/webhooks/lemonsqueezy", content=body,
                          headers={"x-signature": "f" * 64})  # fmt: skip
    assert bad.status_code == 400
    assert order_licenses(db, order_no) == []
    for _ in range(2):  # yeniden gönderim ikinci lisans üretmez
        ok = await http.post("/v1/payments/webhooks/lemonsqueezy", content=body, headers=headers)
        assert ok.status_code == 200
    assert len(order_licenses(db, order_no)) == 1
    assert (await http.get(f"/v1/me/orders/{order_no}")).json()["status"] == "fulfilled"
    # İlgisiz olay 200 ile karşılanır, hiçbir şey değişmez.
    h2, b2 = webhook(order_id, event="subscription_created", ls_id="99")
    assert (
        await http.post("/v1/payments/webhooks/lemonsqueezy", content=b2, headers=h2)
    ).status_code == 200
    assert len(order_licenses(db, order_no)) == 1

    # Mağaza para birimi farklıysa (ör. USD) otomatik teslim yapılmaz; sipariş incelemeye düşer.
    second = await http.post("/v1/checkout", json=checkout_body())
    second_no = second.json()["order_no"]
    second_id = seen[1]["data"]["attributes"]["checkout_data"]["custom"]["order_id"]
    h3, b3 = webhook(second_id, currency="USD", total=599, ls_id="5555")
    assert (
        await http.post("/v1/payments/webhooks/lemonsqueezy", content=b3, headers=h3)
    ).status_code == 200
    assert order_licenses(db, second_no) == []
    assert "payment.needs_review" in audit_actions(db)
