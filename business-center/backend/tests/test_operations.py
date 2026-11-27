from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from conftest import auth, make_user
from test_tasks import FakeLLM, _run_one, env  # noqa: F401

from bizcenter.db import Database
from bizcenter.finance import compute_pnl, missing_data
from bizcenter.scheduler import next_run, tick


def R(dep, amt, cur="USD", cat="sales"):
    return {"department": dep, "category": cat, "amount": Decimal(amt), "currency": cur}


def F(dep, kind, amt, cur="USD"):
    return {"department": dep, "kind": kind, "amount": Decimal(amt), "currency": cur}


# ---- finans motoru ------------------------------------------------------------------

def test_pnl_formula():
    rev = [R("etsy", "100"), R("youtube", "40")]
    rec = [F("etsy", "fee", "10"), F("etsy", "refund", "5"), F("etsy", "tax", "8")]
    exp = [R("etsy", "30", cat="printify_production"), R("etsy", "5", cat="etsy_ads"), R("shared", "12", cat="ai")]
    etsy = compute_pnl("etsy", rev, rec, exp)["USD"]
    assert etsy["collected_revenue"] == "95" and etsy["net_profit"] == "50"
    assert etsy["tax_reported_separately"] == "8" and etsy["margin_pct"] == "52.63"
    combined = compute_pnl("combined", rev, rec, exp)["USD"]
    assert combined["net_profit"] == str(Decimal(135) - 10 - 30 - 5 - 12)
    assert compute_pnl("youtube", rev, rec, exp)["USD"]["net_profit"] == "40"


def test_pnl_never_mixes_currencies():
    out = compute_pnl("etsy", [R("etsy", "100", "USD"), R("etsy", "500", "TRY")], [], [])
    assert out["USD"]["net_profit"] == "100" and out["TRY"]["net_profit"] == "500"
    miss = missing_data("etsy", [R("etsy", "100", "USD"), R("etsy", "500", "TRY")], [], [])
    assert any("ücret" in m for m in miss) and any("Printify" in m for m in miss)
    assert any("kur" in m for m in miss)


async def test_finance_api_and_verified_report(client, admin):
    uid = make_user(admin, "fin@test")
    org = (await client.post("/api/organizations", json={"name": "F"}, headers=auth(uid))).json()["id"]
    d = str(date.today())
    for e in [{"kind": "revenue", "department": "etsy", "category": "sales", "amount": "100.00"},
              {"kind": "fee", "department": "etsy", "category": "etsy_fees", "amount": "10.00"},
              {"kind": "expense", "department": "etsy", "category": "printify_production", "amount": "30.00"}]:
        r = await client.post(f"/api/organizations/{org}/finance/entries", headers=auth(uid),
                              json={**e, "currency": "USD", "occurred_on": d})
        assert r.status_code == 201, r.text
    s = (await client.get(f"/api/organizations/{org}/finance/summary?start={d}&end={d}", headers=auth(uid))).json()
    assert s["scopes"]["etsy"]["by_currency"]["USD"]["net_profit"] == "60.00"
    assert s["scopes"]["etsy"]["missing_data"] == []
    assert s["scopes"]["youtube"]["missing_data"] == ["Dönem için gelir kaydı yok"]
    assert (await client.post(f"/api/organizations/{org}/finance/reports?start={d}&end={d}",
                              headers=auth(uid))).json()["saved"] == 2  # YouTube verisi yok: rapor üretilmez
    dash = (await client.get(f"/api/organizations/{org}/dashboard", headers=auth(uid))).json()
    assert dash["etsy"]["net_profit"]["status"] == "ok" and dash["etsy"]["net_profit"]["value"]["amount"] == "60.00"
    assert admin.execute("select count(*) n from audit_logs where organization_id=%s and action='finance.manual_entry'",
                         (org,)).fetchone()["n"] == 3

    viewer = make_user(admin, "finv@test")
    admin.execute("insert into organization_members values (%s,%s,'viewer',now())", (org, viewer))
    r = await client.post(f"/api/organizations/{org}/finance/entries", headers=auth(viewer),
                          json={"kind": "expense", "department": "etsy", "category": "x", "amount": "1",
                                "currency": "USD", "occurred_on": d})
    assert r.status_code == 403
    bad = await client.post(f"/api/organizations/{org}/finance/entries", headers=auth(uid),
                            json={"kind": "expense", "department": "etsy", "category": "x", "amount": "-5",
                                  "currency": "usd", "occurred_on": d})
    assert bad.status_code == 422


# ---- otomasyon ----------------------------------------------------------------------

class Recorder:
    def __init__(self):
        self.ids = []

    def enqueue(self, task_id):
        self.ids.append(task_id)


async def test_automation_rules_and_scheduler(client, admin, dsn):
    uid = make_user(admin, "auto@test")
    org = (await client.post("/api/organizations", json={"name": "A"}, headers=auth(uid))).json()["id"]
    assert len((await client.get("/api/automation/templates", headers=auth(uid))).json()) == 10
    assert (await client.post(f"/api/organizations/{org}/automation", headers=auth(uid),
                              json={"name": "x", "schedule_cron": "her gün", "command": "rapor hazırla"})).status_code == 422
    r = await client.post(f"/api/organizations/{org}/automation", headers=auth(uid),
                          json={"name": "Günlük", "schedule_cron": "0 8 * * *", "command": "rapor hazırla"})
    assert r.status_code == 201 and r.json()["next_run_at"] is None  # varsayılan kapalı
    rid = r.json()["id"]
    r = await client.patch(f"/api/automation/{rid}", headers=auth(uid), json={"enabled": True})
    assert r.json()["enabled"] is True and r.json()["next_run_at"] is not None

    # vadesi gelmiş gibi göster ve bir de süresi dolmuş onay ekle
    admin.execute("update automation_rules set next_run_at = now() - interval '1 minute' where id=%s", (rid,))
    admin.execute("""insert into approvals(organization_id, platform, action, reason, expected_outcome, risk_level,
                     after_state, payload, payload_hash, created_at, expires_at)
                     values (%s,'etsy','x','r','o','low','{}','{}','h', now()-interval '2 hour', now()-interval '1 hour')""", (org,))
    db = Database(dsn, 2)
    await db.open()
    rec = Recorder()
    out = await tick(db, rec, max_active=3)
    assert out["expired_approvals"] >= 1 and len(out["started"]) == 1 and rec.ids == out["started"]
    task = admin.execute("select title, created_by, status from tasks where id=%s", (out["started"][0],)).fetchone()
    assert task["title"] == "[Otomatik] Günlük" and str(task["created_by"]) == uid and task["status"] == "queued"
    nxt = admin.execute("select next_run_at from automation_rules where id=%s", (rid,)).fetchone()["next_run_at"]
    assert nxt > datetime.now(UTC)
    # sınır doluysa atlanır ve bildirilir
    admin.execute("update automation_rules set next_run_at = now() - interval '1 minute' where id=%s", (rid,))
    out = await tick(db, rec, max_active=1)
    assert out["started"] == [] and out["skipped"] == 1
    await db.close()
    n = (await client.get(f"/api/organizations/{org}/notifications", headers=auth(uid))).json()
    assert any(i["kind"] == "automation_skipped" for i in n["items"])

    outsider = make_user(admin, "auto-o@test")
    assert (await client.patch(f"/api/automation/{rid}", headers=auth(outsider), json={"enabled": False})).status_code == 404
    assert (await client.delete(f"/api/automation/{rid}", headers=auth(outsider))).status_code == 404
    assert (await client.delete(f"/api/automation/{rid}", headers=auth(uid))).status_code == 204


def test_next_run_respects_timezone():
    after = datetime(2026, 1, 1, 4, 0, tzinfo=UTC)  # İstanbul 07:00
    assert next_run("0 8 * * *", "Europe/Istanbul", after) == datetime(2026, 1, 1, 5, 0, tzinfo=UTC)
    assert next_run("0 8 * * *", "UTC", after) - after == timedelta(hours=4)


async def test_task_completion_notifies_and_mark_read(env, admin, client):
    t = await _run_one(env, admin, "notif@test", FakeLLM())
    uid = admin.execute("select id from auth.users where email='notif@test'").fetchone()["id"]
    n = (await client.get(f"/api/organizations/{t['organization_id']}/notifications", headers=auth(str(uid)))).json()
    assert n["unread"] == 1 and n["items"][0]["kind"] == "task_completed"
    assert n["items"][0]["link"] == f"/tasks/{t['id']}"
    r = await client.post(f"/api/organizations/{t['organization_id']}/notifications/read", headers=auth(str(uid)))
    assert r.json() == {"marked": 1}
