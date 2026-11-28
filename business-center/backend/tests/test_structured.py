from conftest import auth
from httpx import ASGITransport, AsyncClient
from test_tasks import FakeLLM, env, setup_org  # noqa: F401


async def run_direct(env, admin, email, agent, llm, seed=None):
    app, disp = await env(llm)
    async with app.router.lifespan_context(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        uid, org = await setup_org(c, admin, email)
        if seed:
            seed(org)
        tid = (await c.post(f"/api/organizations/{org}/tasks", headers=auth(uid),
                            json={"command": "işini yap", "agent_code": agent})).json()["id"]
        await disp.drain()
        t = (await c.get(f"/api/tasks/{tid}", headers=auth(uid))).json()
        approvals = (await c.get(f"/api/organizations/{org}/approvals?status=pending", headers=auth(uid))).json()
        return org, t, approvals


async def test_product_ideas_are_saved(env, admin):
    llm = FakeLLM(structured={"ideas": [{"niche": "Minimal poster", "idea": "Dağ silüeti posteri", "score": 140,
                                         "evidence": ["https://ornek.com/a"]}]})
    org, t, _ = await run_direct(env, admin, "st1@test", "etsy_product_research", llm)
    assert t["status"] == "completed" and "1 fikir kaydedildi" in t["result"]["report"]
    row = admin.execute("select idea, opportunity_score, task_id from product_research where organization_id=%s", (org,)).fetchone()
    assert row["idea"] == "Dağ silüeti posteri" and row["opportunity_score"] == 100 and str(row["task_id"]) == t["id"]


async def test_seo_agent_sees_real_listings_and_proposes_for_approval(env, admin):
    def seed(org):
        shop = admin.execute("insert into etsy_shops(organization_id, etsy_shop_id, name) values (%s,77,'S') returning id",
                             (org,)).fetchone()["id"]
        admin.execute("insert into etsy_listings(organization_id, shop_id, etsy_listing_id, title, tags, state)"
                      " values (%s,%s,501,'Poster',%s,'active')", (org, shop, ["a"]))

    good_tags = [f"etiket{i}" for i in range(13)]
    llm = FakeLLM(structured={"proposals": [
        {"listing_id": "501", "new_title": "Minimalist Dağ Posteri – İskandinav Duvar Dekoru", "new_tags": good_tags, "reason": "Uzun kuyruklu kelimeler"},
        {"listing_id": "999", "new_title": "Başkasının listelemesi", "new_tags": [], "reason": "x"},          # bize ait değil
        {"listing_id": "501", "new_title": "", "new_tags": ["çok-uzun-bir-etiket-yirmi-karakteri-aşıyor"], "reason": "x"},  # kural dışı
        {"listing_id": "501", "new_title": "", "new_tags": [], "reason": "değişiklik yok"},
    ]})
    org, t, approvals = await run_direct(env, admin, "st2@test", "etsy_seo", llm, seed)
    assert "id=501 | başlık=Poster" in llm.calls[0]["user"]                     # gerçek kayıtları gördü
    assert "<untrusted_data source=\"records\">" in llm.calls[0]["user"]
    assert len(approvals) == 1                                                 # yalnızca geçerli öneri
    a = approvals[0]
    assert a["before_state"] == {"title": "Poster", "tags": ["a"]} and a["after_state"]["tags"] == good_tags
    assert "1 değişiklik önerisi" in t["result"]["report"] and "2 öneri kurallara uymadığı" in t["result"]["report"]
    # öneri hiçbir şeyi değiştirmedi
    assert admin.execute("select title from etsy_listings where etsy_listing_id=501 and organization_id=%s",
                         (org,)).fetchone()["title"] == "Poster"
