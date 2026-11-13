# ruff: noqa: F811 - db ve shopper fikstürleri test_payments'tan alınır
"""Yönetim paneli: toplu lisans işlemleri ve sitenin en üstündeki duyuru şeridi.

* Toplu silme/iptal doğrulama kodu ister (bir kez); her lisans ayrı işlenir, uygun olmayan
  lisans nedeniyle raporlanır ve diğerlerini etkilemez; her biri denetim kaydına yazılır.
* Duyuru herkese açık uçtan okunur; süresi geçince ya da kapatılınca görünmez. Yürürlükteki
  kampanya aynı uçta döner (şerit geri sayım gösterir).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from admin_support import Clock, activate_admin
from ati_cloud.licensing.service import Licensing
from test_payments import audit_actions, db  # noqa: F401


async def _issue(app: Any, dsn: str, count: int) -> list[str]:
    licensing: Licensing = app.state.licensing
    ids = []
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        conn.row_factory = psycopg.rows.dict_row  # type: ignore[assignment]
        for _ in range(count):
            lic, _ = await licensing.issue(conn, plan_code="d30_1dev")  # type: ignore[arg-type]
            ids.append(str(lic))
    return ids


async def test_bulk_license_actions(
    app: Any, clock: Clock, db: psycopg.Connection[Any], dsn: str
) -> None:
    admin = await activate_admin(app, clock, "kurucu@example.com", ["super_admin"])
    support = await activate_admin(app, clock, "destek@example.com", ["support"])
    ids = await _issue(app, dsn, 4)
    cancel_url = "/admin/v1/bulk/licenses/cancel"
    freeze_url = "/admin/v1/bulk/licenses/freeze"

    # Yetki ve doğrulama kodu.
    denied = await support.http.post(
        cancel_url, json={"ids": ids, "action": "cancel", "reason": "x" * 5}
    )
    assert denied.status_code == 403
    no_code = await admin.http.post(
        cancel_url, json={"ids": ids, "action": "delete", "reason": "test"}
    )
    assert no_code.status_code == 400
    wrong = await admin.http.post(
        freeze_url, json={"ids": ids, "action": "delete", "reason": "test"}
    )
    assert wrong.status_code == 422  # silme yalnızca iptal yetkili uçtan
    short = await admin.http.post(freeze_url, json={"ids": ids, "action": "freeze", "reason": "x"})
    assert short.status_code == 422

    # Dondur → ikisini çöz.
    frozen = await admin.http.post(
        freeze_url, json={"ids": ids, "action": "freeze", "reason": "inceleme"}
    )
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["done"] == 4 and frozen.json()["failed"] == 0
    thawed = await admin.http.post(freeze_url, json={"ids": ids[:2], "action": "unfreeze"})
    assert thawed.json()["done"] == 2
    assert {r["status"] for r in thawed.json()["results"]} == {"ready_for_sale"}

    # Toplu silme: biri zaten silinmiş/yok olsa bile diğerleri silinir.
    code = clock.code(admin.secret)
    deleted = await admin.http.post(
        cancel_url,
        json={
            "ids": [*ids[:3], "00000000-0000-0000-0000-000000000000", "bozuk"],
            "action": "delete",
            "reason": "hatalı parti",
            "code": code,
        },
    )
    assert deleted.status_code == 200, deleted.text
    body = deleted.json()
    assert body["done"] == 3 and body["failed"] == 2
    assert [r["error"] for r in body["results"] if not r["ok"]] == [
        "Lisans bulunamadı",
        "Geçersiz kimlik",
    ]
    rows = db.execute(
        "SELECT count(*) FROM licenses WHERE deleted_at IS NOT NULL AND status = 'cancelled'"
    ).fetchone()
    assert rows == (3,)
    listed = (await admin.http.get("/admin/v1/licenses", params={"limit": 200})).json()
    assert {item["id"] for item in listed["items"]} == {ids[3]}

    # Aynı doğrulama kodu ikinci kez kullanılamaz.
    reuse = await admin.http.post(
        cancel_url,
        json={
            "ids": [ids[3]],
            "action": "cancel",
            "reason": "tekrar",
            "code": code,
        },
    )
    assert reuse.status_code == 400
    assert audit_actions(db).count("admin.license_deleted") == 3
    assert audit_actions(db).count("admin.license_frozen") == 4
    for client in (admin, support):
        await client.http.aclose()


async def test_announcement_bar(app: Any, clock: Clock, db: psycopg.Connection[Any]) -> None:
    admin = await activate_admin(app, clock, "kurucu@example.com", ["super_admin"])
    support = await activate_admin(app, clock, "destek@example.com", ["support"])
    public = await admin.http.get("/v1/site/announcement")
    assert public.status_code == 200
    assert public.json() == {"announcement": None, "campaign": None}
    assert public.headers["cache-control"] == "public, max-age=30"

    body = {
        "enabled": True,
        "text": " Yeni sürüm 0.14.7 yayında ",
        "link": "/indir",
        "tone": "success",
    }
    assert (await support.http.put("/admin/v1/settings/announcement", json=body)).status_code == 403
    for bad in (
        {**body, "link": "javascript:alert(1)"},
        {**body, "link": "http://example.com"},
        {**body, "tone": "kirmizi"},
        {**body, "text": "x" * 161},
    ):
        assert (
            await admin.http.put("/admin/v1/settings/announcement", json=bad)
        ).status_code == 422
    empty = await admin.http.put("/admin/v1/settings/announcement", json={**body, "text": " "})
    assert empty.status_code == 422
    saved = await admin.http.put("/admin/v1/settings/announcement", json=body)
    assert saved.status_code == 200 and saved.json()["active"] is True
    assert "admin.announcement_updated" in audit_actions(db)
    shown = (await admin.http.get("/v1/site/announcement")).json()["announcement"]
    assert shown == {
        "text": "Yeni sürüm 0.14.7 yayında",
        "link": "/indir",
        "tone": "success",
        "ends_at": None,
    }

    # Kampanya şeritte görünür; süresi geçen duyuru görünmez.
    await admin.http.put(
        "/admin/v1/campaign", json={"enabled": True, "percent": 25, "label": "Kasım"}
    )
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    await admin.http.put("/admin/v1/settings/announcement", json={**body, "ends_at": past})
    view = (await admin.http.get("/v1/site/announcement")).json()
    assert view["announcement"] is None
    assert view["campaign"] == {"percent": 25, "label": "Kasım", "ends_at": None}
    current = (await admin.http.get("/admin/v1/settings/announcement")).json()
    assert current["active"] is False and current["text"] == "Yeni sürüm 0.14.7 yayında"
    for client in (admin, support):
        await client.http.aclose()
