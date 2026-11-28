import json

import httpx
from conftest import SECRET, auth, make_user
from httpx import ASGITransport, AsyncClient

from bizcenter.config import Settings
from bizcenter.db import Database
from bizcenter.integrations.crypto import TokenCipher, new_key
from bizcenter.main import create_app

KEY = new_key()


class FakeApis:
    def __init__(self):
        self.writes = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        if req.method in ("PATCH", "PUT"):
            self.writes.append((req.method, req.url.path, req.content.decode()))
        if req.url.path == "/v3/application/shops/555/listings/9001" and req.method == "PATCH":
            return httpx.Response(200, json={"listing_id": 9001, "title": "Yeni Başlık"})
        if req.url.path == "/v3/application/shops/555/listings" and req.method == "POST":
            self.writes.append(("POST", req.url.path, req.content.decode()))
            return httpx.Response(201, json={"listing_id": 777, "state": "draft"})
        if req.url.path == "/youtube/v3/videos" and req.method == "GET":
            return httpx.Response(200, json={"items": [{"id": "v1", "snippet": {"title": "Eski", "description": "d",
                                                                                  "tags": ["a"], "categoryId": "22"}}]})
        if req.url.path == "/youtube/v3/videos" and req.method == "PUT":
            return httpx.Response(200, json={"id": "v1", "snippet": json.loads(req.content)["snippet"]})
        return httpx.Response(404)


async def setup(c, admin, email, scopes_etsy, scopes_yt):
    uid = make_user(admin, email)
    org = (await c.post("/api/organizations", json={"name": "X"}, headers=auth(uid))).json()["id"]
    enc = TokenCipher(KEY).encrypt("tok")
    for prov, acc, scopes in (("etsy", "555", scopes_etsy), ("youtube", "UC1", scopes_yt)):
        iid = admin.execute("insert into integrations(organization_id, provider, status, external_account_id, scopes)"
                            " values (%s,%s,'connected',%s,%s) returning id", (org, prov, acc, scopes)).fetchone()["id"]
        admin.execute("insert into oauth_tokens(integration_id, access_token_enc) values (%s,%s)", (iid, enc))
    shop = admin.execute("insert into etsy_shops(organization_id, etsy_shop_id, name) values (%s,555,'S') returning id",
                         (org,)).fetchone()["id"]
    admin.execute("insert into etsy_listings(organization_id, shop_id, etsy_listing_id, title, tags) values (%s,%s,9001,'Eski Başlık',%s)",
                  (org, shop, ["a"]))
    ch = admin.execute("insert into youtube_channels(organization_id, youtube_channel_id, title) values (%s,'UC1','K') returning id",
                       (org,)).fetchone()["id"]
    admin.execute("insert into youtube_videos(organization_id, channel_id, youtube_video_id, title) values (%s,%s,'v1','Eski')", (org, ch))
    return uid, org


async def make(dsn, fake):
    s = Settings(database_url=dsn, supabase_jwt_secret=SECRET, rate_limit_per_minute=10_000, token_encryption_key=KEY,
                 etsy_keystring="k", etsy_redirect_uri="https://x/cb")
    app = create_app(s, Database(dsn, 2))
    app.state.http_transport = httpx.MockTransport(fake.handler)
    return app


def body(action, target, changes):
    return {"action": action, "target_id": target, "changes": changes, "reason": "SEO iyileştirme", "expected_outcome": "Daha fazla görüntülenme"}


async def test_approved_changes_are_executed_with_all_checks(dsn, admin):
    fake = FakeApis()
    app = await make(dsn, fake)
    async with app.router.lifespan_context(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        uid, org = await setup(c, admin, "ex1@test", ["listings_r", "listings_w"], ["https://www.googleapis.com/auth/youtube.force-ssl"])
        r = await c.post(f"/api/organizations/{org}/approvals", headers=auth(uid),
                         json=body("etsy.listing.update", "9001", {"title": "Yeni Başlık", "tags": ["poster", "dağ"]}))
        assert r.status_code == 201
        aid = r.json()["id"]
        assert fake.writes == []                                   # onaysız hiçbir yazma yok
        a = (await c.get(f"/api/organizations/{org}/approvals?status=pending", headers=auth(uid))).json()[0]
        assert a["before_state"] == {"title": "Eski Başlık", "tags": ["a"]} and a["after_state"]["title"] == "Yeni Başlık"
        d = await c.post(f"/api/approvals/{aid}/decision", headers=auth(uid), json={"approve": True})
        assert d.json()["status"] == "executed"
        assert fake.writes[0][0] == "PATCH" and "Yeni" in fake.writes[0][2]
        assert admin.execute("select title from etsy_listings where etsy_listing_id=9001 and organization_id=%s",
                             (org,)).fetchone()["title"] == "Yeni Başlık"
        hist = [h["to_status"] for h in admin.execute("select to_status from approval_history where approval_id=%s order by id",
                                                       (aid,)).fetchall()]
        assert hist == ["pending", "approved", "executed"]

        r = await c.post(f"/api/organizations/{org}/approvals", headers=auth(uid),
                         json=body("youtube.video.update_metadata", "v1", {"title": "Daha iyi başlık"}))
        d = await c.post(f"/api/approvals/{r.json()['id']}/decision", headers=auth(uid), json={"approve": True})
        assert d.json()["status"] == "executed"
        put = json.loads(fake.writes[-1][2])
        assert put["snippet"]["title"] == "Daha iyi başlık" and put["snippet"]["categoryId"] == "22" and put["snippet"]["tags"] == ["a"]


async def test_rejected_tampered_or_unauthorized_never_execute(dsn, admin):
    fake = FakeApis()
    app = await make(dsn, fake)
    async with app.router.lifespan_context(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        uid, org = await setup(c, admin, "ex2@test", ["listings_r"], [])     # yazma izni YOK
        mk = lambda ch: c.post(f"/api/organizations/{org}/approvals", headers=auth(uid), json=body("etsy.listing.update", "9001", ch))  # noqa: E731

        # 1) reddedilen
        aid = (await mk({"title": "A"})).json()["id"]
        await c.post(f"/api/approvals/{aid}/decision", headers=auth(uid), json={"approve": False, "note": "Hayır"})
        # 2) yazma izni olmayan
        aid2 = (await mk({"title": "B"})).json()["id"]
        d = (await c.post(f"/api/approvals/{aid2}/decision", headers=auth(uid), json={"approve": True})).json()
        assert d["status"] == "failed"
        assert "yazma izni" in admin.execute("select decision_note from approvals where id=%s", (aid2,)).fetchone()["decision_note"]
        # 3) onaydan önce içeriği değiştirilmiş (hash uyuşmazlığı) — tetikleyiciyi geçici kapatıp kurcalıyoruz
        admin.execute("update integrations set scopes=%s where organization_id=%s and provider='etsy'", (["listings_w"], org))
        aid3 = (await mk({"title": "C"})).json()["id"]
        admin.execute("alter table approvals disable trigger approvals_validate")
        admin.execute("""update approvals set payload = jsonb_set(payload, '{changes,title}', '"KÖTÜ"') where id=%s""", (aid3,))
        admin.execute("alter table approvals enable trigger approvals_validate")
        d = (await c.post(f"/api/approvals/{aid3}/decision", headers=auth(uid), json={"approve": True})).json()
        assert d["status"] == "failed"
        assert "Bütünlük" in admin.execute("select decision_note from approvals where id=%s", (aid3,)).fetchone()["decision_note"]
        assert fake.writes == []                                   # hiçbirinde API'ye yazılmadı

        # Geçersiz öneriler ve yetkisiz kullanıcı
        assert (await mk({"tags": [f"t{i}" for i in range(14)]})).status_code == 422
        assert (await mk({"price": "1"})).status_code == 422
        assert (await c.post(f"/api/organizations/{org}/approvals", headers=auth(uid),
                             json=body("etsy.listing.delete", "9001", {"title": "x"}))).status_code == 422
        assert (await c.post(f"/api/organizations/{org}/approvals", headers=auth(uid),
                             json=body("etsy.listing.update", "1234", {"title": "x"}))).status_code == 404
        viewer = make_user(admin, "ex2v@test")
        admin.execute("insert into organization_members values (%s,%s,'viewer',now())", (org, viewer))
        assert (await c.post(f"/api/organizations/{org}/approvals", headers=auth(viewer),
                             json=body("etsy.listing.update", "9001", {"title": "x"}))).status_code == 403


async def test_etsy_draft_listing_is_created_only_as_draft_after_approval(dsn, admin):
    from urllib.parse import parse_qs
    fake = FakeApis()
    app = await make(dsn, fake)
    async with app.router.lifespan_context(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        uid, org = await setup(c, admin, "ex3@test", ["listings_w"], [])
        draft = {"title": "Minimalist Dağ Posteri", "description": "A4 / A3 baskı", "price": 24.9, "quantity": 50,
                 "taxonomy_id": 1027, "tags": ["poster", "dağ"]}
        bad = await c.post(f"/api/organizations/{org}/approvals/etsy-draft", headers=auth(uid), json={**draft, "tags": ["x" * 21]})
        assert bad.status_code == 422
        r = await c.post(f"/api/organizations/{org}/approvals/etsy-draft", headers=auth(uid), json=draft)
        assert r.status_code == 201 and fake.writes == []
        d = (await c.post(f"/api/approvals/{r.json()['id']}/decision", headers=auth(uid), json={"approve": True})).json()
        assert d["status"] == "executed"
        form = parse_qs(fake.writes[-1][2])
        assert form["state"] == ["draft"] and form["title"] == ["Minimalist Dağ Posteri"] and form["when_made"] == ["made_to_order"]
        row = admin.execute("select state, title from etsy_listings where etsy_listing_id=777 and organization_id=%s", (org,)).fetchone()
        assert row["state"] == "draft"
