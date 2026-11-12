# ruff: noqa: F811 - db ve shopper fikstürleri test_payments'tan alınır
"""Genel indirim kampanyası ve lisans silme (yönetim paneli).

* Kampanya bütün ücretli paketlere yüzde indirim uygular: paket listesi, kupon önizlemesi ve
  ödeme tutarı sunucuda hesaplanır; kupon kampanyalı fiyatın üzerine uygulanır.
* Deneme paketi, kapalı ya da süresi geçmiş kampanya fiyatı değiştirmez.
* Lisans silme doğrulama kodu ister; lisans iptal edilir, listelerden kalkar ve etkinleştirilemez.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from admin_support import Clock, activate_admin
from ati_cloud.licensing.service import Licensing
from ati_cloud.payments import campaign
from test_licensing import Engine
from test_payments import (  # noqa: F401
    audit_actions,
    checkout_body,
    db,
    one,
    pay,
    price,
    set_payment,
    shopper,
)


def test_campaign_rules() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    assert campaign.discounted(19990, 20) == 15992
    assert campaign.discounted(999, 15) == 850  # indirim kuruşa aşağı yuvarlanır
    assert campaign.is_active({"enabled": True, "percent": 20}, now)
    assert not campaign.is_active({"enabled": False, "percent": 20}, now)
    assert not campaign.is_active({"enabled": True, "percent": 95}, now)
    assert not campaign.is_active({"enabled": True, "percent": "20"}, now)
    assert not campaign.is_active(
        {"enabled": True, "percent": 20, "ends_at": "2029-12-31T23:59:00+00:00"}, now
    )
    assert campaign.is_active({"enabled": True, "percent": 20, "ends_at": "2030-01-02"}, now)
    assert not campaign.is_active({"enabled": True, "percent": 20, "ends_at": "yarın"}, now)
    trial = {"code": "trial_7d", "price_minor": 0, "is_trial": True}
    assert campaign.apply_to_plan(trial, {"percent": 50})["campaign_percent"] is None


async def test_admin_sets_campaign_and_prices_follow(
    app: Any, clock: Clock, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    set_payment(app, db, "simulator")
    price(db, "d30_1dev", 19990)
    price(db, "d90_1dev", 49990)
    price(db, "trial_7d", 0)
    admin = await activate_admin(app, clock, "kurucu@example.com", ["super_admin"])
    support = await activate_admin(app, clock, "destek@example.com", ["support"])

    initial = await admin.http.get("/admin/v1/campaign")
    assert initial.status_code == 200 and initial.json()["active"] is False
    body = {"enabled": True, "percent": 20, "label": " Kasım indirimi "}
    assert (await support.http.put("/admin/v1/campaign", json=body)).status_code == 403
    assert (await support.http.get("/admin/v1/campaign")).status_code == 403
    for bad in ({**body, "percent": 0}, {**body, "percent": 91}, {**body, "label": "x" * 61}):
        assert (await admin.http.put("/admin/v1/campaign", json=bad)).status_code == 422
    saved = await admin.http.put("/admin/v1/campaign", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json() == {
        "enabled": True, "percent": 20, "label": "Kasım indirimi", "ends_at": None, "active": True,
    }  # fmt: skip
    assert (await admin.http.get("/admin/v1/campaign")).json()["active"] is True
    assert "admin.campaign_updated" in audit_actions(db)

    plans = {p["code"]: p for p in (await admin.http.get("/v1/plans")).json()}
    assert plans["d30_1dev"]["price_minor"] == 15992
    assert plans["d30_1dev"]["list_price_minor"] == 19990
    assert plans["d30_1dev"]["campaign_percent"] == 20
    assert plans["d30_1dev"]["campaign_label"] == "Kasım indirimi"
    assert plans["d90_1dev"]["price_minor"] == 39992
    assert plans["trial_7d"]["price_minor"] == 0 and plans["trial_7d"]["campaign_percent"] is None

    # Kupon kampanyalı fiyatın üzerine uygulanır; tutarları sunucu hesaplar.
    await admin.http.post("/admin/v1/coupons", json={"code": "DOST10", "percent_off": 10})
    http = await shopper()
    preview = await http.post("/v1/coupons/check", json={"plan_code": "d30_1dev", "code": "DOST10"})
    assert preview.status_code == 200, preview.text
    assert preview.json() == {
        "code": "DOST10", "list_price_minor": 19990, "campaign_percent": 20,
        "subtotal_minor": 15992, "discount_minor": 1599, "total_minor": 14393, "currency": "TRY",
    }  # fmt: skip
    response = await http.post("/v1/checkout", json=checkout_body(total_minor=1))
    assert response.status_code == 200, response.text
    order_no = response.json()["order_no"]
    row = db.execute(
        "SELECT subtotal_minor, discount_minor, total_minor, campaign_percent, "
        "billing_snapshot->'campaign'->>'list_price_minor' FROM orders WHERE order_no = %s",
        (order_no,),
    ).fetchone()
    assert row == (15992, 0, 15992, 20, "19990")
    token = response.json()["redirect_url"].split("oturum=", 1)[1]
    await pay(http, token)
    assert (await http.get(f"/v1/me/orders/{order_no}")).json()["status"] == "fulfilled"

    # Süresi geçmiş ya da kapalı kampanya fiyatı değiştirmez.
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    expired = await admin.http.put("/admin/v1/campaign", json={**body, "ends_at": past})
    assert expired.json()["active"] is False
    plans = {p["code"]: p for p in (await admin.http.get("/v1/plans")).json()}
    assert plans["d30_1dev"]["price_minor"] == 19990
    assert plans["d30_1dev"]["list_price_minor"] is None
    future = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    later = await admin.http.put("/admin/v1/campaign", json={**body, "ends_at": future})
    assert later.json()["active"] is True
    await admin.http.put("/admin/v1/campaign", json={**body, "enabled": False})
    plans = {p["code"]: p for p in (await admin.http.get("/v1/plans")).json()}
    assert plans["d30_1dev"]["price_minor"] == 19990
    plain = await http.post("/v1/checkout", json=checkout_body())
    assert one(
        db, "SELECT campaign_percent FROM orders WHERE order_no = %s", (plain.json()["order_no"],)
    ) is None  # fmt: skip
    for client in (admin, support):
        await client.http.aclose()


async def test_license_delete_needs_totp_hides_and_blocks_activation(
    app: Any, clock: Clock, db: psycopg.Connection[Any], shopper: Callable[..., Any], dsn: str
) -> None:
    admin = await activate_admin(app, clock, "kurucu@example.com", ["super_admin"])
    support = await activate_admin(app, clock, "destek@example.com", ["support"])
    http = await shopper()
    licensing: Licensing = app.state.licensing
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        conn.row_factory = psycopg.rows.dict_row  # type: ignore[assignment]
        sold_id, key = await licensing.issue(
            conn, plan_code="d30_1dev", customer_id=http.customer_id
        )  # type: ignore[arg-type]
        spare_id, _ = await licensing.issue(conn, plan_code="d30_1dev", customer_id=None)  # type: ignore[arg-type]
    # Bu uygulamanın kira imza anahtarı test_licensing'inkinden farklıdır: kira doğrulanmadan
    # okunur (imza doğrulaması test_licensing'te sınanır).
    engine = Engine(http)
    first = await http.post("/v1/licenses/activate", json=engine.activation(key))
    assert first.status_code == 200, first.text
    engine.lease = json.loads(first.json()["lease"]["p"])
    assert len((await http.get("/v1/me")).json()["licenses"]) == 1

    url = f"/admin/v1/licenses/{sold_id}/delete"
    body = {"reason": "hatalı satış", "code": clock.code(admin.secret)}
    no_perm = await support.http.post(url, json={**body, "code": clock.code(support.secret)})
    assert no_perm.status_code == 403
    assert (await admin.http.post(url, json={**body, "code": "000000"})).status_code == 400
    assert one(db, "SELECT status::text FROM licenses WHERE id = %s", (sold_id,)) == "active"

    deleted = await admin.http.post(url, json=body)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"id": str(sold_id), "deleted": True}
    row = db.execute(
        "SELECT status::text, cancel_reason, deleted_at IS NOT NULL FROM licenses WHERE id = %s",
        (sold_id,),
    ).fetchone()
    assert row == ("cancelled", "silindi: hatalı satış", True)
    clock.now += 30  # aynı doğrulama kodu ikinci kez kullanılamaz
    again = await admin.http.post(url, json={**body, "code": clock.code(admin.secret)})
    assert again.status_code == 404

    listed = (await admin.http.get("/admin/v1/licenses", params={"limit": 200})).json()
    ids = {item["id"] for item in listed["items"]}
    assert str(sold_id) not in ids and str(spare_id) in ids
    assert (await http.get("/v1/me")).json()["licenses"] == []
    blocked = await http.post("/v1/licenses/activate", json=Engine(http).activation(key))
    assert blocked.status_code == 403
    renewed = await engine.renew()
    assert renewed.status_code == 403

    # Satılmamış (havuzdaki) lisans da silinebilir; silinen lisans satışa çıkmaz.
    clock.now += 30
    spare = await admin.http.post(
        f"/admin/v1/licenses/{spare_id}/delete",
        json={"reason": "test anahtarı", "code": clock.code(admin.secret)},
    )
    assert spare.status_code == 200
    assert one(db, "SELECT status::text FROM licenses WHERE id = %s", (spare_id,)) == "cancelled"
    events = db.execute(
        "SELECT to_status::text, actor_type::text FROM license_events WHERE license_id = %s "
        "ORDER BY id DESC LIMIT 1",
        (sold_id,),
    ).fetchone()
    assert events == ("cancelled", "admin")
    assert audit_actions(db).count("admin.license_deleted") == 2
    for client in (admin, support):
        await client.http.aclose()
