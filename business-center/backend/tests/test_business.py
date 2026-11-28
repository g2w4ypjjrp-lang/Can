from datetime import date

from conftest import auth, make_user


async def test_business_views_empty_and_with_data(client, admin):
    uid = make_user(admin, "biz@test")
    org = (await client.post("/api/organizations", json={"name": "B"}, headers=auth(uid))).json()["id"]
    h = auth(uid)
    y = (await client.get(f"/api/organizations/{org}/youtube", headers=h)).json()
    assert y["channel"] is None and y["videos"] == []
    a = (await client.get(f"/api/organizations/{org}/analytics?days=7", headers=h)).json()
    assert a["youtube"] is None and a["etsy"] is None            # bağlı değilken sıfır uydurulmaz
    assert (await client.get(f"/api/organizations/{org}/analytics?days=13", headers=h)).status_code == 422

    admin.execute("insert into integrations(organization_id, provider, status) values (%s,'youtube','connected')", (org,))
    ch = admin.execute("""insert into youtube_channels(organization_id, youtube_channel_id, title, subscriber_count, view_count,
                          stats_fetched_at) values (%s,'UC1','Kanal',10,100,now()) returning id""", (org,)).fetchone()["id"]
    admin.execute("""insert into youtube_analytics(organization_id, channel_id, day, views, watch_time_minutes,
                     subscribers_gained, subscribers_lost) values (%s,%s,current_date - 2, 50, 120, 3, 1)""", (org, ch))
    admin.execute("""insert into youtube_videos(organization_id, channel_id, youtube_video_id, title, lifecycle, published_at)
                     values (%s,%s,'v1','İlk video','published', now())""", (org, ch))
    a = (await client.get(f"/api/organizations/{org}/analytics?days=7", headers=h)).json()
    assert len(a["youtube"]) == 7 and sum(r["views"] for r in a["youtube"]) == 50
    assert sum(r["has_data"] for r in a["youtube"]) == 1
    y = (await client.get(f"/api/organizations/{org}/youtube", headers=h)).json()
    assert y["channel"]["title"] == "Kanal" and y["last30"]["views"] == 50 and y["last30"]["net_subs"] == 2
    cal = (await client.get(f"/api/organizations/{org}/calendar?month={date.today():%Y-%m}", headers=h)).json()
    assert any(e["kind"] == "video" and e["title"] == "İlk video" for e in cal)
    assert (await client.get(f"/api/organizations/{org}/calendar?month=bozuk", headers=h)).status_code == 422
    for path in ("etsy", "research", "production"):
        assert (await client.get(f"/api/organizations/{org}/{path}", headers=h)).status_code == 200

    outsider = make_user(admin, "biz-o@test")
    y = (await client.get(f"/api/organizations/{org}/youtube", headers=auth(outsider))).json()
    assert y["channel"] is None and y["videos"] == []                # RLS: başka işletme göremez
