import json

import httpx
from conftest import SECRET, auth, make_user
from httpx import ASGITransport, AsyncClient

from bizcenter.config import Settings
from bizcenter.db import Database
from bizcenter.integrations.crypto import TokenCipher, new_key
from bizcenter.main import create_app

TOKEN = "pf_" + "a" * 40
KEY = new_key()


class FakePrintify:
    def __init__(self, shops=None):
        self.shops = shops if shops is not None else [{"id": 111, "title": "Can Posters", "sales_channel": "etsy"}]
        self.auth_seen = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.auth_seen.append(req.headers.get("authorization"))
        if req.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"error": "unauthorized"})
        if req.url.path == "/v1/shops.json":
            return httpx.Response(200, json=self.shops)
        if req.url.path == "/v1/shops/111/products.json":
            page = int(req.url.params.get("page", 1))
            items = [{"id": f"p{page}{i}", "title": f"Poster {page}-{i}", "blueprint_id": 282, "print_provider_id": 99,
                      "variants": [{"id": 1, "title": "A4", "price": 2499, "cost": 1100, "is_enabled": True},
                                   {"id": 2, "title": "A3", "price": 2999, "cost": 1400, "is_enabled": False}]}
                     for i in range(2)]
            return httpx.Response(200, json={"data": items, "last_page": 2})
        return httpx.Response(404)


async def make(dsn, fake, key=KEY):
    s = Settings(database_url=dsn, supabase_jwt_secret=SECRET, rate_limit_per_minute=10_000, token_encryption_key=key)
    app = create_app(s, Database(dsn, 2))
    app.state.http_transport = httpx.MockTransport(fake.handler)
    return app


async def test_printify_connect_sync_disconnect(dsn, admin):
    fake = FakePrintify()
    app = await make(dsn, fake)
    async with app.router.lifespan_context(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        uid = make_user(admin, "pf@test")
        org = (await c.post("/api/organizations", json={"name": "P"}, headers=auth(uid))).json()["id"]
        url = f"/api/organizations/{org}/integrations/printify"

        bad = await c.post(url, headers=auth(uid), json={"token": "x" * 30})
        assert bad.status_code == 400 and "geçersiz" in bad.json()["detail"]

        r = await c.post(url, headers=auth(uid), json={"token": TOKEN})
        assert r.status_code == 200 and r.json()["shop"]["title"] == "Can Posters"
        assert TOKEN not in json.dumps(r.json())

        stored = admin.execute("""select t.access_token_enc from oauth_tokens t join integrations i on i.id=t.integration_id
                                where i.organization_id=%s""", (org,)).fetchall()
        assert len(stored) == 1 and TOKEN.encode() not in bytes(stored[0]["access_token_enc"])
        assert TokenCipher(KEY).decrypt(stored[0]["access_token_enc"]) == TOKEN

        s = await c.post(url + "/sync", headers=auth(uid))
        assert s.json() == {"synced": 4}
        again = await c.post(url + "/sync", headers=auth(uid))
        assert again.json() == {"synced": 4}  # tekrar senkronda çoğaltma yok
        prods = (await c.get(f"/api/organizations/{org}/printify/products", headers=auth(uid))).json()
        assert len(prods) == 4 and prods[0]["variants"] == [
            {"id": 1, "title": "A4", "price_cents": 2499, "cost_cents": 1100, "is_enabled": True}]
        st = (await c.get(f"/api/organizations/{org}/integrations", headers=auth(uid))).json()
        assert st["printify"]["status"] == "connected" and st["printify"]["product_count"] == 4
        assert st["youtube"]["status"] == "disconnected"
        assert "access_token" not in json.dumps(st)

        viewer = make_user(admin, "pfv@test")
        admin.execute("insert into organization_members values (%s,%s,'viewer',now())", (org, viewer))
        assert (await c.post(url + "/sync", headers=auth(viewer))).status_code == 403
        assert (await c.post(url, headers=auth(viewer), json={"token": TOKEN})).status_code == 403

        assert (await c.delete(url, headers=auth(uid))).status_code == 204
        assert admin.execute("select count(*) n from oauth_tokens t join integrations i on i.id=t.integration_id"
                             " where i.organization_id=%s", (org,)).fetchone()["n"] == 0
        assert (await c.post(url + "/sync", headers=auth(uid))).status_code == 409


async def test_printify_multiple_shops_and_missing_key(dsn, admin):
    fake = FakePrintify(shops=[{"id": 111, "title": "A"}, {"id": 222, "title": "B"}])
    app = await make(dsn, fake)
    async with app.router.lifespan_context(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        uid = make_user(admin, "pf2@test")
        org = (await c.post("/api/organizations", json={"name": "P2"}, headers=auth(uid))).json()["id"]
        r = await c.post(f"/api/organizations/{org}/integrations/printify", headers=auth(uid), json={"token": TOKEN})
        assert r.status_code == 409 and len(r.json()["detail"]["shops"]) == 2
        r = await c.post(f"/api/organizations/{org}/integrations/printify", headers=auth(uid), json={"token": TOKEN, "shop_id": 222})
        assert r.json()["shop"]["title"] == "B"

    app = await make(dsn, fake, key="")
    async with app.router.lifespan_context(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/organizations/{org}/integrations/printify", headers=auth(uid), json={"token": TOKEN})
        assert r.status_code == 503
