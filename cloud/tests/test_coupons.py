# ruff: noqa: F811 - db ve shopper fikstürleri test_payments'tan alınır
"""İndirim kuponları: yönetici oluşturur; müşteri önizler ve ödemede uygular.

* Tutar her zaman sunucuda hesaplanır; istemcinin gönderdiği tutar/indirim yok sayılır.
* Kullanım sınırı eşzamanlı başvurularda da aşılmaz; müşteri başına bir kez.
* %100 kupon sağlayıcıya gitmeden teslim edilir; deneme paketinde kupon kullanılamaz.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from admin_support import Clock, activate_admin
from test_payments import (  # noqa: F401
    audit_actions,
    checkout_body,
    db,
    one,
    order_licenses,
    pay,
    price,
    set_payment,
    shopper,
)


async def make_admin(app: Any, clock: Clock) -> Any:
    return await activate_admin(app, clock, "kurucu@example.com", ["super_admin"])


async def test_admin_creates_lists_and_updates_coupons(
    app: Any, clock: Clock, db: psycopg.Connection[Any]
) -> None:
    admin = await make_admin(app, clock)
    support = await activate_admin(app, clock, "destek@example.com", ["support"])
    body = {"code": "yeniyil-25", "percent_off": 25, "note": "Yılbaşı kampanyası"}
    assert (await support.http.post("/admin/v1/coupons", json=body)).status_code == 403
    created = await admin.http.post("/admin/v1/coupons", json=body)
    assert created.status_code == 200, created.text
    assert created.json()["code"] == "YENIYIL-25" and created.json()["redemptions"] == 0
    assert (await admin.http.post("/admin/v1/coupons", json=body)).status_code == 409
    for bad in (
        {"code": "IKISI", "percent_off": 10, "amount_off_minor": 500, "currency": "TRY"},
        {"code": "HICBIRI"},
        {"code": "TUTAR", "amount_off_minor": 500},
        {"code": "AB", "percent_off": 10},
        {"code": "YUZDE", "percent_off": 101},
        {"code": "PAKET", "percent_off": 10, "plan_codes": ["yok_boyle"]},
        {"code": "TARIH", "percent_off": 10, "valid_from": "2030-01-02T00:00:00Z",
         "valid_until": "2030-01-01T00:00:00Z"},
    ):  # fmt: skip
        response = await admin.http.post("/admin/v1/coupons", json=bad)
        assert response.status_code == 422, (bad, response.text)
    listed = (await admin.http.get("/admin/v1/coupons")).json()
    assert [c["code"] for c in listed] == ["YENIYIL-25"]
    off = await admin.http.patch("/admin/v1/coupons/yeniyil-25", json={"is_active": False})
    assert off.status_code == 200 and off.json()["is_active"] is False
    assert (await admin.http.patch("/admin/v1/coupons/YOK", json={"note": "x"})).status_code == 404
    actions = audit_actions(db)
    assert "admin.coupon_created" in actions and "admin.coupon_updated" in actions
    for client in (admin, support):
        await client.http.aclose()


async def test_percent_coupon_preview_and_purchase(
    app: Any, clock: Clock, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    set_payment(app, db, "simulator")
    price(db, "d30_1dev", 19990)
    price(db, "d90_1dev", 49990)
    admin = await make_admin(app, clock)
    await admin.http.post(
        "/admin/v1/coupons", json={"code": "DOST15", "percent_off": 15, "plan_codes": ["d30_1dev"]}
    )
    http = await shopper()
    preview = await http.post(
        "/v1/coupons/check", json={"plan_code": "d30_1dev", "code": " dost15 "}
    )
    assert preview.status_code == 200, preview.text
    assert preview.json() == {
        "code": "DOST15", "subtotal_minor": 19990, "discount_minor": 2998, "total_minor": 16992,
        "currency": "TRY",
    }  # fmt: skip
    other = await http.post("/v1/coupons/check", json={"plan_code": "d90_1dev", "code": "DOST15"})
    assert other.status_code == 409 and other.json()["detail"]["code"] == "coupon_not_applicable"
    unknown = await http.post(
        "/v1/coupons/check", json={"plan_code": "d30_1dev", "code": "YOK-BOYLE"}
    )
    assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "coupon_invalid"
    assert one(db, "SELECT count(*) FROM orders") == 0  # önizleme sipariş açmaz

    # İstemcinin gönderdiği indirim/tutar yok sayılır; sunucu hesaplar.
    response = await http.post(
        "/v1/checkout",
        json=checkout_body(coupon="dost15", discount_minor=19990, total_minor=1),
    )
    assert response.status_code == 200, response.text
    order_no = response.json()["order_no"]
    row = db.execute(
        "SELECT subtotal_minor, discount_minor, total_minor, coupon_code FROM orders "
        "WHERE order_no = %s",
        (order_no,),
    ).fetchone()
    assert row == (19990, 2998, 16992, "DOST15")
    token = response.json()["redirect_url"].split("oturum=", 1)[1]
    session = (await http.get("/v1/payments/simulator/session", params={"token": token})).json()
    assert session["total_minor"] == 16992
    await pay(http, token)
    order = (await http.get(f"/v1/me/orders/{order_no}")).json()
    assert order["status"] == "fulfilled" and order["discount_minor"] == 2998
    assert order["coupon_code"] == "DOST15"
    again = await http.post("/v1/coupons/check", json={"plan_code": "d30_1dev", "code": "DOST15"})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "coupon_used"
    listed = (await admin.http.get("/admin/v1/coupons")).json()
    assert listed[0]["redemptions"] == 1 and listed[0]["discount_total_minor"] == 2998
    await admin.http.aclose()


async def test_full_discount_delivers_without_provider_and_trial_is_excluded(
    app: Any, clock: Clock, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    set_payment(app, db, "simulator")
    price(db, "d30_1dev", 19990)
    price(db, "trial_7d", 0)
    admin = await make_admin(app, clock)
    await admin.http.post("/admin/v1/coupons", json={"code": "HEDIYE", "percent_off": 100})
    await admin.http.post(
        "/admin/v1/coupons",
        json={"code": "INDIRIM50", "amount_off_minor": 5000, "currency": "TRY"},
    )
    http = await shopper()
    trial = await http.post("/v1/coupons/check", json={"plan_code": "trial_7d", "code": "HEDIYE"})
    assert trial.status_code == 409 and trial.json()["detail"]["code"] == "coupon_not_applicable"
    amount = await http.post(
        "/v1/coupons/check", json={"plan_code": "d30_1dev", "code": "INDIRIM50"}
    )
    assert amount.json()["total_minor"] == 14990

    gift = await http.post("/v1/checkout", json=checkout_body(coupon="HEDIYE"))
    assert gift.status_code == 200, gift.text
    assert gift.json()["redirect_url"].endswith(f"/odeme/sonuc?siparis={gift.json()['order_no']}")
    order = (await http.get(f"/v1/me/orders/{gift.json()['order_no']}")).json()
    assert order["status"] == "fulfilled" and order["total_minor"] == 0
    assert len(order_licenses(db, gift.json()["order_no"])) == 1
    assert one(db, "SELECT payment_provider FROM orders WHERE order_no = %s",
               (gift.json()["order_no"],)) == "free"  # fmt: skip
    await admin.http.aclose()


async def test_expired_inactive_and_limited_coupons(
    app: Any, clock: Clock, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    set_payment(app, db, "simulator")
    price(db, "d30_1dev", 19990)
    admin = await make_admin(app, clock)
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    await admin.http.post("/admin/v1/coupons", json={"code": "ESKI", "percent_off": 10,
                                                     "valid_until": past})  # fmt: skip
    await admin.http.post("/admin/v1/coupons", json={"code": "YAKINDA", "percent_off": 10,
                                                     "valid_from": future})  # fmt: skip
    await admin.http.post("/admin/v1/coupons", json={"code": "KAPALI", "percent_off": 10})
    await admin.http.patch("/admin/v1/coupons/KAPALI", json={"is_active": False})
    await admin.http.post(
        "/admin/v1/coupons", json={"code": "IKIKISI", "percent_off": 10, "max_redemptions": 2}
    )
    http = await shopper()
    for code in ("ESKI", "YAKINDA", "KAPALI"):
        response = await http.post("/v1/checkout", json=checkout_body(coupon=code))
        assert response.status_code == 404, code
    assert one(db, "SELECT count(*) FROM orders") == 0

    # Beş müşteri aynı anda iki kullanımlık kupona başvurur: yalnızca ikisi alır.
    shoppers = [await shopper() for _ in range(5)]
    results = await asyncio.gather(
        *(s.post("/v1/checkout", json=checkout_body(coupon="IKIKISI")) for s in shoppers)
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 200, 409, 409, 409], [r.text for r in results]
    assert one(db, "SELECT count(*) FROM orders WHERE coupon_code = 'IKIKISI'") == 2
    exhausted = next(r for r in results if r.status_code == 409)
    assert exhausted.json()["detail"]["code"] == "coupon_exhausted"

    # Yarım kalan (başarısız) sipariş hakkı geri verir.
    failed_no = next(r.json()["order_no"] for r in results if r.status_code == 200)
    db.execute("UPDATE orders SET status = 'failed' WHERE order_no = %s", (failed_no,))
    retry = await http.post("/v1/checkout", json=checkout_body(coupon="IKIKISI"))
    assert retry.status_code == 200, retry.text
    await admin.http.aclose()
