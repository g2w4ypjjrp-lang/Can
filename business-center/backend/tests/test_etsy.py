import json
from urllib.parse import parse_qs, urlparse

import httpx
from conftest import SECRET, auth, make_user
from httpx import ASGITransport, AsyncClient

from bizcenter.config import Settings
from bizcenter.db import Database
from bizcenter.integrations.crypto import new_key
from bizcenter.main import create_app

KEY = new_key()


class FakeEtsy:
    def __init__(self):
        self.token_calls = []
        self.access = "123.access-1"

    def handler(self, req: httpx.Request) -> httpx.Response:
        assert req.headers["x-api-key"] == "kstr"
        if req.url.path == "/v3/public/oauth/token":
            form = parse_qs(req.content.decode())
            self.token_calls.append(form)
            if form["grant_type"] == ["authorization_code"] and form["code"] != ["good"]:
                return httpx.Response(401, json={"error": "invalid_grant"})
            self.access = "123.access-" + str(len(self.token_calls))
            return httpx.Response(200, json={"access_token": self.access, "refresh_token": "123.refresh",
                                             "expires_in": 3600, "token_type": "Bearer"})
        if req.headers.get("authorization") != f"Bearer {self.access}":
            return httpx.Response(401)
        if req.url.path == "/v3/application/users/me":
            return httpx.Response(200, json={"user_id": 123, "shop_id": 555})
        if req.url.path == "/v3/application/shops/555":
            return httpx.Response(200, json={"shop_id": 555, "shop_name": "CanPosters", "currency_code": "USD"})
        if req.url.path == "/v3/application/shops/555/listings":
            return httpx.Response(200, json={"count": 1, "results": [{
                "listing_id": 9001, "title": "Minimalist Dağ Posteri", "description": "d", "tags": ["poster", "dağ"],
                "price": {"amount": 2490, "divisor": 100, "currency_code": "USD"}, "quantity": 10, "state": "active"}]})
        if req.url.path == "/v3/application/shops/555/receipts":
            return httpx.Response(200, json={"count": 2, "results": [
                {"receipt_id": 1, "status": "paid", "is_paid": True, "is_shipped": True, "created_timestamp": 1790000000,
                 "grandtotal": {"amount": 3490, "divisor": 100, "currency_code": "USD"}},
                {"receipt_id": 2, "status": "open", "is_paid": False, "is_shipped": False, "created_timestamp": 1790000500,
                 "grandtotal": {"amount": 2490, "divisor": 100, "currency_code": "USD"}}]})
        return httpx.Response(404)


async def make(dsn, fake):
    s = Settings(database_url=dsn, supabase_jwt_secret=SECRET, rate_limit_per_minute=10_000, token_encryption_key=KEY,
                 etsy_keystring="kstr", etsy_redirect_uri="https://panel.test/integrations/etsy/callback")
    app = create_app(s, Database(dsn, 2))
    app.state.http_transport = httpx.MockTransport(fake.handler)
    return app


async def test_etsy_oauth_sync_refresh_disconnect(dsn, admin):
    fake = FakeEtsy()
    app = await make(dsn, fake)
    async with app.router.lifespan_context(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        uid = make_user(admin, "etsy@test")
        org = (await c.post("/api/organizations", json={"name": "E"}, headers=auth(uid))).json()["id"]
        base = f"/api/organizations/{org}/integrations/etsy"

        url = (await c.post(base + "/start", headers=auth(uid))).json()["url"]
        q = parse_qs(urlparse(url).query)
        assert url.startswith("https://www.etsy.com/oauth/connect?") and q["code_challenge_method"] == ["S256"]
        assert q["scope"] == ["shops_r listings_r transactions_r"] and q["client_id"] == ["kstr"]
        state = q["state"][0]

        # yanlış state reddedilir ve bekleyen istek tüketilir
        assert (await c.post(base + "/callback", headers=auth(uid), json={"code": "good", "state": "x" * 20})).status_code == 400
        assert (await c.post(base + "/callback", headers=auth(uid), json={"code": "good", "state": state})).status_code == 400

        state = parse_qs(urlparse((await c.post(base + "/start", headers=auth(uid))).json()["url"]).query)["state"][0]
        r = await c.post(base + "/callback", headers=auth(uid), json={"code": "good", "state": state})
        assert r.status_code == 200 and r.json()["shop"]["name"] == "CanPosters"
        verifier = fake.token_calls[-1]["code_verifier"][0]
        assert len(verifier) >= 43
        enc = admin.execute("""select t.access_token_enc, t.refresh_token_enc from oauth_tokens t join integrations i
                               on i.id=t.integration_id where i.organization_id=%s""", (org,)).fetchone()
        assert b"access" not in bytes(enc["access_token_enc"]) and b"refresh" not in bytes(enc["refresh_token_enc"])

        s = (await c.post(base + "/sync", headers=auth(uid))).json()
        assert s == {"listings": 1, "orders": 2, "revenue_records": 1}
        assert (await c.post(base + "/sync", headers=auth(uid))).json()["revenue_records"] == 1
        assert admin.execute("select count(*) n from revenue_records where organization_id=%s", (org,)).fetchone()["n"] == 1
        li = admin.execute("select title, price_amount, currency, tags from etsy_listings").fetchone()
        assert str(li["price_amount"]) == "24.90" and li["currency"] == "USD" and li["tags"] == ["poster", "dağ"]

        d = (await c.get(f"/api/organizations/{org}/dashboard", headers=auth(uid))).json()
        assert d["etsy"]["orders_30d"]["status"] in ("ok", "no_data")
        assert "access" not in json.dumps((await c.get(f"/api/organizations/{org}/integrations", headers=auth(uid))).json())

        # süresi dolmuş token otomatik yenilenir
        admin.execute("update oauth_tokens set expires_at = now() - interval '1 minute' where integration_id in"
                      " (select id from integrations where organization_id=%s)", (org,))
        calls = len(fake.token_calls)
        assert (await c.post(base + "/sync", headers=auth(uid))).status_code == 200
        assert fake.token_calls[-1]["grant_type"] == ["refresh_token"] and len(fake.token_calls) == calls + 1

        assert (await c.delete(base, headers=auth(uid))).status_code == 204
        assert admin.execute("select count(*) n from oauth_tokens t join integrations i on i.id=t.integration_id"
                             " where i.organization_id=%s", (org,)).fetchone()["n"] == 0


async def test_etsy_requires_server_config(dsn, admin, client):
    uid = make_user(admin, "etsy2@test")
    org = (await client.post("/api/organizations", json={"name": "E2"}, headers=auth(uid))).json()["id"]
    r = await client.post(f"/api/organizations/{org}/integrations/etsy/start", headers=auth(uid))
    assert r.status_code == 503 and "BC_ETSY_KEYSTRING" in r.json()["detail"]
