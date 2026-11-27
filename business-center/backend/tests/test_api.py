import time

import psycopg
import pytest
from conftest import SECRET, auth, make_user, token
from httpx import ASGITransport, AsyncClient

from bizcenter.config import Settings
from bizcenter.main import create_app


async def new_org(client, admin, email="owner@test"):
    uid = make_user(admin, email)
    r = await client.post("/api/organizations", json={"name": "Can Store"}, headers=auth(uid))
    assert r.status_code == 201, r.text
    return uid, r.json()["id"]


def add_approval(admin, org, minutes=60, **kw):
    row = admin.execute(
        """insert into approvals(organization_id, platform, action, reason, expected_outcome,
               risk_level, after_state, payload, payload_hash, expires_at)
           values (%s,'etsy','listing.price_update','Rakip fiyatları düştü','Dönüşüm artışı',
                   'medium','{"price":"19.90"}','{"listing_id":1}','h', now() + %s * interval '1 minute')
           returning id""", (org, minutes)).fetchone()
    return str(row["id"])


# ---- kimlik doğrulama ---------------------------------------------------------------

async def test_health(client):
    r = await client.get("/health")
    assert r.json() == {"status": "ok"}
    assert r.headers["x-content-type-options"] == "nosniff"
    assert (await client.get("/health/ready")).status_code == 200


@pytest.mark.parametrize("header", [
    None, "Bearer bozuk", "Basic abc",
    "Bearer " + token("00000000-0000-0000-0000-000000000001", exp=int(time.time()) - 10),
    "Bearer " + token("00000000-0000-0000-0000-000000000001", secret="baska-anahtar-" + "y" * 32),
    "Bearer " + token("00000000-0000-0000-0000-000000000001", role="anon"),
])
async def test_rejects_bad_tokens(client, header):
    h = {"authorization": header} if header else {}
    assert (await client.get("/api/me", headers=h)).status_code == 401


# ---- organizasyon ve ajanlar --------------------------------------------------------

async def test_create_org_bootstraps_team(client, admin):
    uid, org = await new_org(client, admin)
    me = (await client.get("/api/me", headers=auth(uid))).json()
    assert me["organizations"][0]["role"] == "owner"
    agents = (await client.get(f"/api/organizations/{org}/agents", headers=auth(uid))).json()
    assert len(agents) == 21
    depts = {a["department"] for a in agents}
    assert depts == {"executive", "youtube", "etsy", "quality"}
    assert any(a["code"] == "ceo" for a in agents)
    assert admin.execute("select count(*) n from audit_logs where target_id=%s", (org,)).fetchone()["n"] == 1


async def test_tenant_isolation(client, admin):
    _, org = await new_org(client, admin, "a@test")
    other = make_user(admin, "b@test")
    add_approval(admin, org)
    assert (await client.get(f"/api/organizations/{org}/dashboard", headers=auth(other))).status_code == 404
    assert (await client.get(f"/api/organizations/{org}/agents", headers=auth(other))).json() == []
    assert (await client.get(f"/api/organizations/{org}/approvals", headers=auth(other))).json() == []


# ---- dashboard: sahte sayı yok -------------------------------------------------------

async def test_dashboard_never_invents_numbers(client, admin):
    uid, org = await new_org(client, admin, "d@test")
    d = (await client.get(f"/api/organizations/{org}/dashboard", headers=auth(uid))).json()
    for m in (*d["youtube"].values(), *d["etsy"].values()):
        assert m["value"] is None and m["status"] == "not_connected"
    assert d["expenses_30d"]["status"] == "no_data"
    assert d["operations"]["agents"] == 21
    assert d["operations"]["pending_approvals"] == 0

    admin.execute("insert into integrations(organization_id, provider, status) values (%s,'etsy','connected')", (org,))
    d = (await client.get(f"/api/organizations/{org}/dashboard", headers=auth(uid))).json()
    assert d["etsy"]["orders_30d"] == {"value": None, "status": "no_data", "as_of": None}

    shop = admin.execute("insert into etsy_shops(organization_id, etsy_shop_id, name) values (%s, 1, 'S') returning id",
                         (org,)).fetchone()["id"]
    for i, (amt, cur) in enumerate([("20.00", "USD"), ("15.50", "USD"), ("100.00", "TRY")]):
        admin.execute("""insert into etsy_orders(organization_id, shop_id, etsy_receipt_id, status,
                         grandtotal_amount, currency, ordered_at) values (%s,%s,%s,'paid',%s,%s, now())""",
                      (org, shop, i, amt, cur))
    d = (await client.get(f"/api/organizations/{org}/dashboard", headers=auth(uid))).json()
    assert d["etsy"]["orders_30d"]["value"] == 3
    rev = {x["currency"]: x["amount"] for x in d["etsy"]["sales_revenue_30d"]["value"]}
    assert rev == {"USD": "35.50", "TRY": "100.00"}  # kur dönüşümü uydurulmaz
    assert d["etsy"]["net_profit"]["status"] == "no_data"  # doğrulanmış rapor yok


# ---- onay sistemi --------------------------------------------------------------------

async def test_approve_flow_and_history(client, admin):
    uid, org = await new_org(client, admin, "ap@test")
    aid = add_approval(admin, org)
    d = (await client.get(f"/api/organizations/{org}/dashboard", headers=auth(uid))).json()
    assert d["operations"]["pending_approvals"] == 1
    r = await client.post(f"/api/approvals/{aid}/decision", json={"approve": True}, headers=auth(uid))
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert r.json()["decided_by"] == uid
    again = await client.post(f"/api/approvals/{aid}/decision", json={"approve": False, "note": "x"},
                              headers=auth(uid))
    assert again.status_code == 409
    hist = admin.execute("select from_status, to_status from approval_history where approval_id=%s order by id",
                         (aid,)).fetchall()
    assert [(h["from_status"], h["to_status"]) for h in hist] == [(None, "pending"), ("pending", "approved")]
    assert admin.execute("select count(*) n from audit_logs where target_id=%s", (aid,)).fetchone()["n"] == 1


async def test_reject_requires_reason(client, admin):
    uid, org = await new_org(client, admin, "rj@test")
    aid = add_approval(admin, org)
    r = await client.post(f"/api/approvals/{aid}/decision", json={"approve": False}, headers=auth(uid))
    assert r.status_code == 409
    r = await client.post(f"/api/approvals/{aid}/decision", json={"approve": False, "note": "Fiyat çok düşük"},
                          headers=auth(uid))
    assert r.json()["status"] == "rejected" and r.json()["decision_note"] == "Fiyat çok düşük"


async def test_expired_approval_cannot_be_approved(client, admin):
    uid, org = await new_org(client, admin, "ex@test")
    aid = add_approval(admin, org, minutes=60)
    admin.execute("alter table approvals disable trigger approvals_validate")
    admin.execute("update approvals set created_at = now() - interval '2 hour', expires_at = now() - interval '1 minute' where id=%s", (aid,))
    admin.execute("alter table approvals enable trigger approvals_validate")
    r = await client.post(f"/api/approvals/{aid}/decision", json={"approve": True}, headers=auth(uid))
    assert r.json()["status"] == "expired"

    aid2 = add_approval(admin, org, minutes=60)
    admin.execute("alter table approvals disable trigger approvals_validate")
    admin.execute("update approvals set created_at = now() - interval '2 hour', expires_at = now() - interval '1 minute' where id=%s", (aid2,))
    admin.execute("alter table approvals enable trigger approvals_validate")
    assert admin.execute("select app.expire_approvals() n").fetchone()["n"] >= 1
    assert admin.execute("select status from approvals where id=%s", (aid2,)).fetchone()["status"] == "expired"


async def test_viewer_and_outsider_cannot_decide(client, admin):
    _, org = await new_org(client, admin, "own@test")
    viewer = make_user(admin, "v@test")
    admin.execute("insert into organization_members values (%s,%s,'viewer',now())", (org, viewer))
    outsider = make_user(admin, "o@test")
    aid = add_approval(admin, org)
    assert (await client.post(f"/api/approvals/{aid}/decision", json={"approve": True},
                              headers=auth(viewer))).status_code == 403
    assert (await client.post(f"/api/approvals/{aid}/decision", json={"approve": True},
                              headers=auth(outsider))).status_code == 403
    assert admin.execute("select status from approvals where id=%s", (aid,)).fetchone()["status"] == "pending"


def test_client_role_cannot_bypass_approval_function(dsn, admin):
    uid = make_user(admin, "byp@test")
    with psycopg.connect(dsn) as c:
        c.execute("select set_config('request.jwt.claims', %s, true)", ('{"sub":"%s"}' % uid,))
        org = c.execute("select app.create_organization('X')").fetchone()[0]
        c.commit()
    aid = add_approval(admin, org)
    with psycopg.connect(dsn) as c:
        c.execute("select set_config('request.jwt.claims', %s, true)", ('{"sub":"%s"}' % uid,))
        c.execute("set local role authenticated")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("update approvals set status='approved' where id=%s", (aid,))
    with psycopg.connect(dsn) as c:
        c.execute("set role authenticated")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("select * from oauth_tokens")


def test_approval_transitions_and_payload_immutable(admin):
    uid = make_user(admin, "tr@test")
    admin.execute("select set_config('request.jwt.claims', %s, false)", ('{"sub":"%s"}' % uid,))
    org = admin.execute("select app.create_organization('T') id").fetchone()["id"]
    admin.execute("select set_config('request.jwt.claims', '', false)")
    aid = add_approval(admin, org)
    with pytest.raises(psycopg.errors.RaiseException):
        admin.execute("update approvals set payload='{\"listing_id\":2}' where id=%s", (aid,))
    with pytest.raises(psycopg.errors.RaiseException):
        admin.execute("update approvals set status='executed' where id=%s", (aid,))


def test_audit_log_append_only(admin):
    admin.execute("insert into audit_logs(action) values ('test')")
    with pytest.raises(psycopg.errors.RaiseException):
        admin.execute("update audit_logs set action='x'")
    with pytest.raises(psycopg.errors.RaiseException):
        admin.execute("delete from audit_logs")


async def test_rate_limit(dsn):
    app = create_app(Settings(database_url=dsn, supabase_jwt_secret=SECRET, rate_limit_per_minute=3))
    async with app.router.lifespan_context(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t") as c:
        codes = [(await c.get("/api/me")).status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]
