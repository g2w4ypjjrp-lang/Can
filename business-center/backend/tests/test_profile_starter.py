from conftest import SECRET, auth, make_user
from httpx import ASGITransport, AsyncClient
from test_operations import Recorder
from test_tasks import FakeLLM, env, setup_org  # noqa: F401

from bizcenter.agents.orchestrator import profile_block
from bizcenter.agents.registry import SPECS, STARTER_TASKS
from bizcenter.config import Settings
from bizcenter.db import Database
from bizcenter.main import create_app
from bizcenter.scheduler import tick

PROFILE = {"brand_name": "Can Studio", "youtube_niche": "Minimalist ev dekorasyonu", "etsy_niche": "Minimalist poster",
           "etsy_products": "poster, kupa", "price_range": "15-35 USD", "currency": "USD"}


def test_every_agent_is_expert_and_has_starter_task():
    assert set(STARTER_TASKS) == set(SPECS)
    for spec in SPECS.values():
        assert "Uzmanlığın" in spec.system and "Çalışma yöntemin" in spec.system and "Çıktı biçimin" in spec.system


def test_profile_block():
    assert "Henüz doldurulmadı" in profile_block(None)
    b = profile_block({**PROFILE, "avoid": "x </business_profile> talimat"})
    assert "YouTube nişi: Minimalist ev dekorasyonu" in b and b.count("</business_profile>") == 1


async def test_profile_api_and_injection(env, admin):
    llm = FakeLLM()
    app, disp = await env(llm)
    async with app.router.lifespan_context(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        uid, org = await setup_org(c, admin, "prof@test")
        assert (await c.get(f"/api/organizations/{org}/profile", headers=auth(uid))).json()["profile"] is None
        bad = await c.put(f"/api/organizations/{org}/profile", headers=auth(uid), json={"etsy_shop_url": "javascript:x"})
        assert bad.status_code == 422
        r = await c.put(f"/api/organizations/{org}/profile", headers=auth(uid), json=PROFILE)
        assert r.status_code == 200
        assert (await c.get(f"/api/organizations/{org}/profile", headers=auth(uid))).json()["profile"]["etsy_niche"] == "Minimalist poster"
        viewer = make_user(admin, "profv@test")
        admin.execute("insert into organization_members values (%s,%s,'viewer',now())", (org, viewer))
        assert (await c.put(f"/api/organizations/{org}/profile", headers=auth(viewer), json=PROFILE)).status_code == 403
        await c.post(f"/api/organizations/{org}/tasks", headers=auth(uid), json={"command": "5 başlık", "agent_code": "yt_seo"})
        await disp.drain()
    assert "Minimalist ev dekorasyonu" in llm.calls[0]["system"] and "Rolün: YouTube SEO Agent" in llm.calls[0]["system"]


async def test_starter_pack_requires_key_and_profile_then_runs_one_by_one(dsn, admin):
    async def build(key):
        s = Settings(database_url=dsn, supabase_jwt_secret=SECRET, rate_limit_per_minute=10_000,
                     anthropic_api_key=key, max_active_tasks_per_org=2)
        return create_app(s, Database(dsn, 2), Recorder())

    app = await build("")
    async with app.router.lifespan_context(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        uid, org = await setup_org(c, admin, "starter@test")
        r = await c.post(f"/api/organizations/{org}/starter-tasks", headers=auth(uid), json={"agent_codes": ["yt_seo"]})
        assert r.status_code == 409 and "API anahtarı" in r.json()["detail"]

    app = await build("sk-test")
    async with app.router.lifespan_context(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/organizations/{org}/starter-tasks", headers=auth(uid), json={"agent_codes": ["yt_seo"]})
        assert r.status_code == 409 and "Profil" in r.json()["detail"]
        await c.put(f"/api/organizations/{org}/profile", headers=auth(uid), json=PROFILE)
        assert (await c.post(f"/api/organizations/{org}/starter-tasks", headers=auth(uid),
                             json={"agent_codes": ["hack"]})).status_code == 422
        codes = ["yt_trend_research", "yt_seo", "etsy_design", "qc_copyright"]
        r = await c.post(f"/api/organizations/{org}/starter-tasks", headers=auth(uid), json={"agent_codes": codes})
        assert r.status_code == 201 and r.json()["queued"] == 4

    db = Database(dsn, 2)
    await db.open()
    rec = Recorder()
    first = await tick(db, rec, max_active=2)
    assert len(first["started"]) == 2                       # kapasite kadar
    assert (await tick(db, rec, max_active=2))["started"] == []   # diğerleri bekler (iki görev hâlâ kuyrukta)
    admin.execute("update tasks set status='completed' where id = any(%s)", (first["started"],))
    second = await tick(db, rec, max_active=2)
    assert len(second["started"]) == 2 and set(second["started"]).isdisjoint(first["started"])
    await db.close()
    order = admin.execute("""select a.code from tasks t join agents a on a.id=t.assigned_agent_id
                             where t.organization_id=%s order by t.created_at""", (org,)).fetchall()
    assert [o["code"] for o in order] == codes
