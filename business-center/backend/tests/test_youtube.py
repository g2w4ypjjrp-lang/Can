from urllib.parse import parse_qs, urlparse

import httpx
from conftest import SECRET, auth, make_user
from httpx import ASGITransport, AsyncClient

from bizcenter.config import Settings
from bizcenter.db import Database
from bizcenter.integrations.crypto import new_key
from bizcenter.main import create_app

KEY = new_key()


class FakeGoogle:
    def __init__(self, monetized=True):
        self.monetized = monetized
        self.token_calls = []
        self.access = "ya29.a"

    def handler(self, req: httpx.Request) -> httpx.Response:
        if req.url.host == "oauth2.googleapis.com":
            form = parse_qs(req.content.decode())
            self.token_calls.append(form)
            assert form["client_secret"] == ["gsecret"]
            self.access = f"ya29.{len(self.token_calls)}"
            body = {"access_token": self.access, "expires_in": 3599, "token_type": "Bearer",
                    "scope": "https://www.googleapis.com/auth/youtube.readonly"}
            if form["grant_type"] == ["authorization_code"]:
                body["refresh_token"] = "1//refresh"
            return httpx.Response(200, json=body)
        if req.headers.get("authorization") != f"Bearer {self.access}":
            return httpx.Response(401)
        p = req.url.path
        if p == "/youtube/v3/channels":
            return httpx.Response(200, json={"items": [{"id": "UC123", "snippet": {"title": "Can TV"},
                "statistics": {"subscriberCount": "1520", "viewCount": "98000", "videoCount": "42", "hiddenSubscriberCount": False},
                "contentDetails": {"relatedPlaylists": {"uploads": "UU123"}}}]})
        if p == "/youtube/v3/playlistItems":
            return httpx.Response(200, json={"items": [{"contentDetails": {"videoId": "v1"}}, {"contentDetails": {"videoId": "v2"}}]})
        if p == "/youtube/v3/videos":
            return httpx.Response(200, json={"items": [
                {"id": v, "snippet": {"title": f"Video {v}", "tags": ["a"], "publishedAt": "2026-10-01T10:00:00Z"},
                 "status": {"privacyStatus": "public"}, "statistics": {"viewCount": "10"}} for v in ("v1", "v2")]})
        if p == "/v2/reports":
            metrics = req.url.params["metrics"]
            if "estimatedRevenue" in metrics and not self.monetized:
                return httpx.Response(403, json={"error": {"errors": [{"reason": "forbidden"}]}})
            cols = metrics.split(",")
            rows = [["2026-11-01", 120, 300.5, 4, 1] + ([2.35] if "estimatedRevenue" in cols else []),
                    ["2026-11-02", 80, 210.0, 2, 0] + ([1.10] if "estimatedRevenue" in cols else [])]
            return httpx.Response(200, json={"columnHeaders": [{"name": "day"}] + [{"name": c} for c in cols], "rows": rows})
        return httpx.Response(404)


async def make(dsn, fake):
    s = Settings(database_url=dsn, supabase_jwt_secret=SECRET, rate_limit_per_minute=10_000, token_encryption_key=KEY,
                 google_client_id="gid", google_client_secret="gsecret",
                 youtube_redirect_uri="https://panel.test/integrations/youtube/callback")
    app = create_app(s, Database(dsn, 2))
    app.state.http_transport = httpx.MockTransport(fake.handler)
    return app


async def connect(c, uid, org):
    base = f"/api/organizations/{org}/integrations/youtube"
    url = (await c.post(base + "/start", headers=auth(uid))).json()["url"]
    q = parse_qs(urlparse(url).query)
    assert q["access_type"] == ["offline"] and q["code_challenge_method"] == ["S256"] and "yt-analytics" in q["scope"][0]
    r = await c.post(base + "/callback", headers=auth(uid), json={"code": "4/abc", "state": q["state"][0]})
    assert r.status_code == 200, r.text
    return base


async def test_youtube_connect_sync_dashboard(dsn, admin):
    fake = FakeGoogle()
    app = await make(dsn, fake)
    async with app.router.lifespan_context(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        uid = make_user(admin, "yt@test")
        org = (await c.post("/api/organizations", json={"name": "Y"}, headers=auth(uid))).json()["id"]
        base = await connect(c, uid, org)
        s = (await c.post(base + "/sync", headers=auth(uid))).json()
        assert s == {"videos": 2, "days": 2, "note": None}
        assert (await c.post(base + "/sync", headers=auth(uid))).status_code == 200   # tekrar: çoğaltma yok
        assert admin.execute("select count(*) n from youtube_analytics where organization_id=%s", (org,)).fetchone()["n"] == 2
        assert admin.execute("select count(*) n from revenue_records where organization_id=%s and department='youtube'",
                             (org,)).fetchone()["n"] == 2
        d = (await c.get(f"/api/organizations/{org}/dashboard", headers=auth(uid))).json()
        assert d["youtube"]["subscribers"]["value"] == 1520 and d["youtube"]["total_views"]["value"] == 98000

        admin.execute("update oauth_tokens set expires_at = now() - interval '1 minute' where integration_id in"
                      " (select id from integrations where organization_id=%s)", (org,))
        assert (await c.post(base + "/sync", headers=auth(uid))).status_code == 200
        assert fake.token_calls[-1]["grant_type"] == ["refresh_token"]
        # yenilemede yeni refresh token gelmese de eskisi korunur
        assert admin.execute("""select refresh_token_enc is not null as ok from oauth_tokens t join integrations i
                                on i.id=t.integration_id where i.organization_id=%s""", (org,)).fetchone()["ok"]
        assert (await c.delete(base, headers=auth(uid))).status_code == 204


async def test_youtube_without_monetization_still_syncs(dsn, admin):
    app = await make(dsn, FakeGoogle(monetized=False))
    async with app.router.lifespan_context(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        uid = make_user(admin, "yt2@test")
        org = (await c.post("/api/organizations", json={"name": "Y2"}, headers=auth(uid))).json()["id"]
        base = await connect(c, uid, org)
        s = (await c.post(base + "/sync", headers=auth(uid))).json()
        assert s["days"] == 2 and "Gelir verisi alınamadı" in s["note"]
        assert admin.execute("select count(*) n from revenue_records where organization_id=%s", (org,)).fetchone()["n"] == 0
        d = (await c.get(f"/api/organizations/{org}/dashboard", headers=auth(uid))).json()
        assert d["youtube"]["estimated_revenue_30d"]["status"] == "no_data"   # uydurma gelir yok
