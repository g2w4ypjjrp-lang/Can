# ruff: noqa: F811 - db ve shopper fikstürleri test_payments'tan alınır
"""Forum (müşteri konuları yönetici onayıyla) ve coin haberleri (açık kaynaklardan, paylaş).

* Müşteri konusu ve yanıtı onaya düşer; onaylanmadan herkese açık listede görünmez.
* Reddedilen gönderinin nedeni müşteriye görünür; kazanç vaadi / bağlantı otomatik işaretlenir.
* Haberler sahte kaynaklardan çekilir (ağ yok): Binance duyurusu, yeni işlem çifti, RSS.
  Paylaşılan haber yayımlanmış ekip konusu olur; aynı haber ikinci kez paylaşılamaz.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import httpx
import psycopg
import pytest

from admin_support import Clock, activate_admin
from ati_cloud import news
from test_payments import audit_actions, db, shopper  # noqa: F401

TOPIC = {
    "author_name": "Kripto Ayşe",
    "category": "strateji",
    "title": "RSI ile kısa vade denemelerim",
    "body": "Merhaba,\n\n15 dakikalık grafikte RSI 30 altına inince deneme yaptım.\nYorumlarınızı bekliyorum.",
    "coin_symbol": "solusdt",
}


async def test_customer_topic_needs_approval(
    app: Any, clock: Clock, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    customer = await shopper()
    anonymous = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://localhost:3000"},
    )
    admin = await activate_admin(app, clock, "kurucu@example.com", ["super_admin"])
    finance = await activate_admin(app, clock, "finans@example.com", ["finance"])

    # Oturumsuz konu açılamaz; e-postası doğrulanmamış müşteri de açamaz.
    assert (await anonymous.post("/v1/forum/me/topics", json=TOPIC)).status_code == 401
    unverified = await shopper(verified=False)
    assert (await unverified.post("/v1/forum/me/topics", json=TOPIC)).status_code == 403
    # Doğrulama: kategori, kısa başlık, geçersiz ad.
    for bad in (
        {**TOPIC, "category": "haber"},
        {**TOPIC, "title": "abc"},
        {**TOPIC, "author_name": "<script>"},
        {**TOPIC, "coin_symbol": "B!"},
    ):
        assert (await customer.post("/v1/forum/me/topics", json=bad)).status_code == 422

    created = await customer.post("/v1/forum/me/topics", json=TOPIC)
    assert created.status_code == 202, created.text
    number = created.json()["number"]
    spam = await customer.post(
        "/v1/forum/me/topics",
        json={
            **TOPIC,
            "title": "Garantili kazanç grubu",
            "body": "Garanti kâr! Katılmak için t.me/sahte-grup adresine yazın.",
        },
    )
    assert spam.status_code == 202
    spam_number = spam.json()["number"]

    # Onaylanmadan herkese görünmez.
    listing = (await anonymous.get("/v1/forum/topics")).json()
    assert listing["total"] == 0
    assert (await anonymous.get(f"/v1/forum/topics/{number}")).status_code == 404

    # Yönetici kuyruğu; yetkisi olmayan rol göremez.
    assert (await finance.http.get("/admin/v1/forum/queue")).status_code == 403
    queue = (await admin.http.get("/admin/v1/forum/queue")).json()
    by_number = {t["number"]: t for t in queue["topics"]}
    assert by_number[number]["coin_symbol"] == "SOL"
    assert by_number[number]["flags"] == []
    assert set(by_number[spam_number]["flags"]) >= {"kazanç vaadi", "iletişim / reklam"}
    assert by_number[number]["customer_email"] == customer.email

    topic_id = by_number[number]["id"]
    spam_id = by_number[spam_number]["id"]
    no_reason = await admin.http.post(
        f"/admin/v1/forum/topics/{spam_id}/moderate", json={"action": "reject"}
    )
    assert no_reason.status_code == 422
    rejected = await admin.http.post(
        f"/admin/v1/forum/topics/{spam_id}/moderate",
        json={"action": "reject", "note": "Kazanç vaadi ve reklam içeriyor"},
    )
    assert rejected.json()["status"] == "rejected"
    approved = await admin.http.post(
        f"/admin/v1/forum/topics/{topic_id}/moderate", json={"action": "approve"}
    )
    assert approved.json()["status"] == "approved"
    again = await admin.http.post(
        f"/admin/v1/forum/topics/{topic_id}/moderate", json={"action": "reject", "note": "x" * 5}
    )
    assert again.status_code == 409

    # Herkese açık liste ve ayrıntı.
    listing = (await anonymous.get("/v1/forum/topics")).json()
    assert listing["total"] == 1
    item = listing["items"][0]
    assert item["number"] == number and item["reply_count"] == 0
    assert item["author_posts"] == 1
    assert item["excerpt"].startswith("Merhaba, 15 dakikalık")
    assert {c["code"]: c["count"] for c in listing["categories"]}["strateji"] == 1
    detail = (await anonymous.get(f"/v1/forum/topics/{number}")).json()
    assert detail["body"] == TOPIC["body"] and detail["view_count"] == 1
    assert "customer_id" not in detail and "email" not in json.dumps(detail)
    filtered = (await anonymous.get("/v1/forum/topics", params={"category": "soru"})).json()
    assert filtered["total"] == 0
    searched = (await anonymous.get("/v1/forum/topics", params={"q": "rsi"})).json()
    assert searched["total"] == 1

    overview = (await anonymous.get("/v1/forum/overview")).json()
    assert overview["totals"] == {"topics": 1, "posts": 1, "members": 1}
    strateji = next(c for c in overview["categories"] if c["code"] == "strateji")
    assert strateji["topics"] == 1 and strateji["last"]["number"] == number
    assert overview["trending"] == [{"symbol": "SOL", "topics": 1}]
    assert detail["author_posts"] == 1

    # Yanıt: onaya düşer, onaylanınca görünür; kilitli konuya yanıt yazılamaz.
    reply = await customer.post(
        f"/v1/forum/me/topics/{number}/replies",
        json={"author_name": "Kripto Ayşe", "body": "Güncelleme: stop seviyesini değiştirdim."},
    )
    assert reply.status_code == 202
    assert (await anonymous.get(f"/v1/forum/topics/{number}")).json()["replies"] == []
    reply_id = (await admin.http.get("/admin/v1/forum/queue")).json()["replies"][0]["id"]
    await admin.http.post(
        f"/admin/v1/forum/replies/{reply_id}/moderate", json={"action": "approve"}
    )
    detail = (await anonymous.get(f"/v1/forum/topics/{number}")).json()
    assert [r["body"] for r in detail["replies"]] == ["Güncelleme: stop seviyesini değiştirdim."]
    assert detail["reply_count"] == 1 and detail["last_reply_author"] == "Kripto Ayşe"
    assert detail["replies"][0]["author_posts"] == 2 and detail["author_posts"] == 2
    overview = (await anonymous.get("/v1/forum/overview")).json()
    assert overview["totals"]["posts"] == 2
    await admin.http.post(f"/admin/v1/forum/topics/{topic_id}/moderate", json={"action": "lock"})
    locked = await customer.post(
        f"/v1/forum/me/topics/{number}/replies", json={"author_name": "Ayşe", "body": "ek"}
    )
    assert locked.status_code == 409
    rejected_reply = await customer.post(
        f"/v1/forum/me/topics/{spam_number}/replies", json={"author_name": "Ayşe", "body": "ek"}
    )
    assert rejected_reply.status_code == 404  # yayımlanmamış konuya yanıt yok

    # Müşteri kendi gönderilerini ve red nedenini görür.
    mine = (await customer.get("/v1/forum/me")).json()
    statuses = {t["number"]: (t["status"], t["moderation_note"]) for t in mine["topics"]}
    assert statuses[number] == ("approved", None)
    assert statuses[spam_number] == ("rejected", "Kazanç vaadi ve reklam içeriyor")
    assert mine["replies"][0]["status"] == "approved"

    # Gizle → listeden kalkar; sil → tamamen gider.
    await admin.http.post(f"/admin/v1/forum/topics/{topic_id}/moderate", json={"action": "hide"})
    assert (await anonymous.get("/v1/forum/topics")).json()["total"] == 0
    deleted = await admin.http.post(
        f"/admin/v1/forum/topics/{topic_id}/moderate", json={"action": "delete"}
    )
    assert deleted.json()["status"] == "deleted"
    assert db.execute("SELECT count(*) FROM forum_replies").fetchone()[0] == 0  # type: ignore[index]
    actions = audit_actions(db)
    assert {"admin.forum_topic_approve", "admin.forum_topic_reject", "admin.forum_reply_approve",
            "admin.forum_topic_delete"} <= set(actions)  # fmt: skip
    await anonymous.aclose()


async def test_pending_limit_and_customer_delete_removes_posts(
    app: Any, clock: Clock, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    customer = await shopper()
    for i in range(5):
        response = await customer.post(
            "/v1/forum/me/topics", json={**TOPIC, "title": f"Deneme konusu {i}"}
        )
        assert response.status_code == 202
    over = await customer.post("/v1/forum/me/topics", json={**TOPIC, "title": "Altıncı konu"})
    assert over.status_code == 429
    admin = await activate_admin(app, clock, "kurucu@example.com", ["super_admin"])
    removed = await admin.http.post(
        f"/admin/v1/customers/{customer.customer_id}/delete",
        json={"confirm_email": customer.email, "reason": "KVKK talebi",
              "code": clock.code(admin.secret)},
    )  # fmt: skip
    assert removed.status_code == 200, removed.text
    assert db.execute("SELECT count(*) FROM forum_topics").fetchone()[0] == 0  # type: ignore[index]


# --- Coin haberleri -------------------------------------------------------------------------------

BINANCE = {
    "code": "000000",
    "data": {
        "catalogs": [
            {
                "catalogId": 48,
                "articles": [
                    {
                        "id": 1,
                        "code": "a259777ee4104befa3daba5c1eadc7b5",
                        "title": "Binance Will List Predict (PREDICT) with Seed Tag Applied",
                        "releaseDate": 1793274532329,
                    },
                    {"id": 2, "code": "../../etc", "title": "Bozuk kod", "releaseDate": 1},
                ],
            }
        ]
    },
}

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>BTCHaber</title>
<item><title>XYZ token Binance&#8217;te listelenecek</title>
<link>https://www.btchaber.com/xyz-token-listeleniyor/</link>
<pubDate>Fri, 13 Nov 2026 09:07:41 +0000</pubDate>
<guid>https://www.btchaber.com/?p=1</guid>
<description><![CDATA[<p>Yeni proje <b>XYZ</b> ($XYZ) yarın işlem görmeye başlıyor.</p>]]></description></item>
<item><title>Bitcoin haftaya düşüşle başladı</title>
<link>https://www.btchaber.com/bitcoin-dusus/</link>
<pubDate>Fri, 13 Nov 2026 06:59:45 +0000</pubDate></item>
<item><title>Kötü bağlantı</title><link>javascript:alert(1)</link></item>
<item><title>Başka site</title><link>https://kotu.example.com/x</link></item>
</channel></rss>""".encode()

EVIL_RSS = b"""<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]>
<rss><channel><item><title>&lol;</title><link>https://www.btchaber.com/x</link></item></channel></rss>"""


def fake_sources(pairs: list[list[str]], rss: bytes = RSS) -> Callable[[], Any]:
    """Her çağrıda sıradaki işlem çifti listesini döner (ilk çalıştırma: bilinenler)."""
    calls = {"pairs": 0}

    async def fetch(url: str) -> bytes:
        if "cms/article" in url:
            return json.dumps(BINANCE).encode()
        if "ticker/price" in url:
            index = min(calls["pairs"], len(pairs) - 1)
            calls["pairs"] += 1
            return json.dumps([{"symbol": s, "price": "1"} for s in pairs[index]]).encode()
        if "btchaber" in url:
            return rss
        if "uzmancoin" in url:
            raise httpx.ConnectError("bağlantı yok")
        request = httpx.Request("GET", url)
        raise httpx.HTTPStatusError(
            "x", request=request, response=httpx.Response(451, request=request)
        )

    @contextlib.asynccontextmanager
    async def factory() -> AsyncIterator[Any]:
        yield fetch

    return factory


def test_parsers_and_safety() -> None:
    source = news.SOURCES["btchaber"]
    items = news.parse_rss(source, RSS)
    assert [i.title for i in items] == [
        "XYZ token Binance’te listelenecek",
        "Bitcoin haftaya düşüşle başladı",
    ]
    assert items[0].kind == "listing" and items[1].kind == "news"
    assert items[0].symbols == ["XYZ"]
    assert items[0].summary == "Yeni proje XYZ ($XYZ) yarın işlem görmeye başlıyor."
    with pytest.raises(ValueError, match="DTD"):
        news.parse_rss(source, EVIL_RSS)
    cms = news.parse_binance_cms(news.SOURCES["binance"], BINANCE)
    assert len(cms) == 1 and cms[0].symbols == ["PREDICT"]
    assert cms[0].url.startswith("https://www.binance.com/en/support/announcement/detail/")
    first, known = news.new_pairs(news.SOURCES["binance_pairs"], [{"symbol": "BTCUSDT"}], set())
    assert first == [] and known == {"BTCUSDT"}
    fresh, _ = news.new_pairs(
        news.SOURCES["binance_pairs"],
        [{"symbol": "BTCUSDT"}, {"symbol": "ABCUSDT"}, {"symbol": "ABCTRY"}],
        known,
    )
    assert [i.symbols for i in fresh] == [["ABC"]]
    assert "ABCTRY" in fresh[0].title and "ABCUSDT" in fresh[0].title


async def test_news_fetch_share_and_dismiss(
    app: Any, clock: Clock, db: psycopg.Connection[Any]
) -> None:
    admin = await activate_admin(app, clock, "kurucu@example.com", ["super_admin"])
    finance = await activate_admin(app, clock, "finans@example.com", ["finance"])
    app.state.news_fetcher = fake_sources([["BTCUSDT"], ["BTCUSDT", "NEWUSDT"]])
    assert (await finance.http.get("/admin/v1/news")).status_code == 403
    # Bu test elle paylaşımı sınar; otomatik taslak ayrı testte (sonuç günün tarihine bağlı olmasın).
    off = await admin.http.put("/admin/v1/news/auto-draft", json={"enabled": False})
    assert off.json() == {"enabled": False}

    first = await admin.http.post("/admin/v1/news/refresh")
    assert first.status_code == 200, first.text
    summary = first.json()
    assert summary["added"] == 3  # Binance duyurusu + iki RSS haberi (çiftler ilk turda kaydedilir)
    assert summary["sources"]["uzmancoin"] == {
        "ok": False,
        "count": 0,
        "error": "Kaynağa bağlanılamadı",
    }
    assert "bölgesinden" in summary["sources"]["cointelegraph"]["error"]
    second = (await admin.http.post("/admin/v1/news/refresh")).json()
    assert second["added"] == 1  # yalnızca yeni işlem çifti; aynı haberler tekrar eklenmez

    listing = (await admin.http.get("/admin/v1/news", params={"kind": "listing"})).json()
    titles = [i["title"] for i in listing["items"]]
    assert "Binance'te yeni işlem çifti: NEWUSDT" in titles
    assert "Binance Will List Predict (PREDICT) with Seed Tag Applied" in titles
    assert all(i["kind"] == "listing" for i in listing["items"])
    assert listing["new_counts"] == {"listing": 3, "news": 1}
    assert {s["key"]: s["ok"] for s in listing["sources"]}["binance"] is True
    predict = next(i for i in listing["items"] if "PREDICT" in i["symbols"])

    # Paylaş → yayımlanmış ekip konusu (kaynak bağlantısıyla).
    shared = await admin.http.post(
        f"/admin/v1/news/{predict['id']}/share",
        json={
            "category": "yeni-coin",
            "title": "Binance PREDICT'i listeliyor",
            "body": "Binance, Predict (PREDICT) için yeni listeleme duyurdu. Yatırım tavsiyesi değildir.",
            "coin_symbol": "PREDICT",
            "pinned": True,
        },
    )
    assert shared.status_code == 201, shared.text
    number = shared.json()["number"]
    twice = await admin.http.post(
        f"/admin/v1/news/{predict['id']}/share",
        json={"category": "haber", "title": "Tekrar paylaşım", "body": "Aynı haber ikinci kez."},
    )
    assert twice.status_code == 409
    public = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
    topic = (await public.get(f"/v1/forum/topics/{number}")).json()
    assert topic["author_kind"] == "team" and topic["pinned"] is True
    assert topic["source_name"] == "Binance duyuruları"
    assert topic["source_url"] == predict["url"]
    await public.aclose()

    # Gizle / geri al; paylaşılmış haber gizlenemez.
    other = next(i for i in listing["items"] if i["id"] != predict["id"])
    hidden = await admin.http.post(
        f"/admin/v1/news/{other['id']}/status", json={"status": "dismissed"}
    )
    assert hidden.status_code == 200
    fresh = (await admin.http.get("/admin/v1/news", params={"kind": "listing"})).json()
    assert other["id"] not in {i["id"] for i in fresh["items"]}
    assert (
        await admin.http.post(
            f"/admin/v1/news/{predict['id']}/status", json={"status": "dismissed"}
        )
    ).status_code == 404
    shared_list = (await admin.http.get("/admin/v1/news", params={"status": "shared"})).json()
    assert [i["topic_number"] for i in shared_list["items"]] == [number]

    # Kaynaklar açılıp kapatılır; kapalı kaynak çekilmez.
    off = await admin.http.put("/admin/v1/news/sources", json={"enabled": ["binance"]})
    assert off.json() == {"enabled": ["binance"]}
    bad = await admin.http.put("/admin/v1/news/sources", json={"enabled": ["kotu"]})
    assert bad.status_code == 422
    third = (await admin.http.post("/admin/v1/news/refresh")).json()
    assert set(third["sources"]) == {"binance"}
    assert {"admin.news_shared", "admin.news_refreshed", "admin.news_sources"} <= set(
        audit_actions(db)
    )


async def test_claim_runs_once_per_interval(app: Any) -> None:
    db = app.state.db
    assert await news.claim(db, 900) is True
    assert await news.claim(db, 900) is False


def _rss(items: list[tuple[str, str, datetime]]) -> bytes:
    body = "".join(
        f"<item><title>{title}</title><link>https://www.btchaber.com/{slug}/</link>"
        f"<guid>https://www.btchaber.com/?p={slug}</guid>"
        f"<pubDate>{format_datetime(at)}</pubDate></item>"
        for title, slug, at in items
    )
    return f'<?xml version="1.0"?><rss><channel>{body}</channel></rss>'.encode()


def _sources(cms: dict[str, Any], rss: bytes, pairs: list[list[str]]) -> Callable[[], Any]:
    calls = {"pairs": 0}

    async def fetch(url: str) -> bytes:
        if "cms/article" in url:
            return json.dumps(cms).encode()
        if "ticker/price" in url:
            index = min(calls["pairs"], len(pairs) - 1)
            calls["pairs"] += 1
            return json.dumps([{"symbol": s} for s in pairs[index]]).encode()
        if "btchaber" in url:
            return rss
        raise httpx.ConnectError("kapalı")

    @contextlib.asynccontextmanager
    async def factory() -> AsyncIterator[Any]:
        yield fetch

    return factory


async def test_new_coin_news_creates_draft_for_approval(
    app: Any, clock: Clock, db: psycopg.Connection[Any], shopper: Callable[..., Any]
) -> None:
    admin = await activate_admin(app, clock, "kurucu@example.com", ["super_admin"])
    now = datetime.now(UTC)
    cms = {
        "data": {
            "catalogs": [
                {
                    "articles": [
                        {
                            "code": "c" * 32,
                            "title": "Binance Will List Testcoin (TST) with Seed Tag Applied",
                            "releaseDate": int((now - timedelta(hours=2)).timestamp() * 1000),
                        }
                    ]
                }
            ]
        }
    }
    rss = _rss(
        [
            ("ABC token yarın listelenecek ($ABC)", "abc", now - timedelta(hours=1)),
            ("ABC işlem görmeye başladı ($ABC)", "abc2", now - timedelta(minutes=30)),
            ("Eski coin OLDX listelendi ($OLDX)", "old", now - timedelta(days=5)),
            ("Bitcoin haftaya yatay başladı ($BTC)", "btc", now - timedelta(hours=1)),
        ]
    )
    app.state.news_fetcher = _sources(cms, rss, [["BTCUSDT"], ["BTCUSDT", "TSTUSDT"]])

    first = (await admin.http.post("/admin/v1/news/refresh")).json()
    # TST (Binance) ve ABC (ilk haber; aynı coinin ikincisi atlanır). Eski ve listeleme olmayan yok.
    assert first["drafted"] == 2, first
    queue = (await admin.http.get("/admin/v1/forum/queue")).json()["topics"]
    drafts = {t["coin_symbol"]: t for t in queue}
    assert set(drafts) == {"TST", "ABC"}
    tst = drafts["TST"]
    assert tst["title"] == "Binance Testcoin (TST) listeliyor"
    assert tst["author_kind"] == "team" and tst["category"] == "yeni-coin"
    assert tst["flags"] == ["otomatik taslak"]
    assert tst["source_url"].startswith("https://www.binance.com/en/support/announcement/detail/")
    assert "yatırım tavsiyesi değildir" in tst["body"]
    assert (await admin.http.get("/admin/v1/forum/pending-count")).json() == {
        "topics": 2,
        "replies": 0,
    }
    # Onaylanmadan sitede görünmez.
    public = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
    assert (await public.get("/v1/forum/topics")).json()["total"] == 0

    listed = (await admin.http.get("/admin/v1/news", params={"status": "drafted"})).json()
    assert listed["pending_drafts"] == 2 and listed["auto_draft"] is True
    assert len(listed["items"]) == 2 and all(i["topic_number"] for i in listed["items"])
    tst_news = next(i for i in listed["items"] if "TST" in i["symbols"])
    abc_news = next(i for i in listed["items"] if "ABC" in i["symbols"])
    taken = await admin.http.post(
        f"/admin/v1/news/{tst_news['id']}/share",
        json={"category": "haber", "title": "İkinci paylaşım", "body": "Aynı haber yeniden."},
    )
    assert taken.status_code == 409  # taslağı zaten onay bekliyor

    # Taslak düzenlenip onaylanır; müşteri metni düzenlenemez.
    edited = await admin.http.post(
        f"/admin/v1/forum/topics/{tst['id']}/edit",
        json={
            "category": "yeni-coin",
            "title": "Binance Testcoin (TST) listeliyor: tarih ve ayrıntılar",
            "body": "Binance, Testcoin (TST) için listeleme duyurdu. Yatırım tavsiyesi değildir.",
            "coin_symbol": "TST",
        },
    )
    assert edited.status_code == 200, edited.text
    customer = await shopper()
    own = await customer.post(
        "/v1/forum/me/topics",
        json={"author_name": "Ayşe", "category": "genel", "title": "Müşteri konusu",
              "body": "Bu metni yönetici değiştiremez."},
    )  # fmt: skip
    own_id = next(
        t["id"] for t in (await admin.http.get("/admin/v1/forum/queue")).json()["topics"]
        if t["number"] == own.json()["number"]
    )  # fmt: skip
    refused = await admin.http.post(
        f"/admin/v1/forum/topics/{own_id}/edit",
        json={"category": "genel", "title": "Değiştirildi", "body": "Değiştirilmiş metin."},
    )
    assert refused.status_code == 404

    await admin.http.post(
        f"/admin/v1/forum/topics/{tst['id']}/moderate", json={"action": "approve"}
    )
    await admin.http.post(
        f"/admin/v1/forum/topics/{drafts['ABC']['id']}/moderate",
        json={"action": "reject", "note": "Kaynak yetersiz"},
    )
    topics = (await public.get("/v1/forum/topics")).json()
    assert [t["title"] for t in topics["items"]] == [
        "Binance Testcoin (TST) listeliyor: tarih ve ayrıntılar"
    ]
    statuses = dict(
        db.execute(
            "SELECT external_id, status FROM coin_news WHERE id = ANY(%s)",
            ([tst_news["id"], abc_news["id"]],),
        ).fetchall()
    )
    assert sorted(statuses.values()) == ["dismissed", "shared"]

    # İkinci tur: aynı haberler tekrar taslak olmaz; yeni TSTUSDT çifti de (TST konusu 24 saat içinde).
    second = (await admin.http.post("/admin/v1/news/refresh")).json()
    assert second["drafted"] == 0 and second["added"] == 1

    # Kapalıyken yeni coin haberi taslak olmaz.
    await admin.http.put("/admin/v1/news/auto-draft", json={"enabled": False})
    app.state.news_fetcher = _sources(
        cms, _rss([("YENİ token listeleniyor ($YNI)", "yni", now)]), [["BTCUSDT"]]
    )
    third = (await admin.http.post("/admin/v1/news/refresh")).json()
    assert third["added"] == 1 and third["drafted"] == 0
    assert "admin.news_auto_draft" in audit_actions(db)
    await public.aclose()


class FakeTranslator:
    name = "sahte"

    def __init__(self, fail: str | None = None) -> None:
        self.calls: list[tuple[list[str], str]] = []
        self.fail = fail

    async def translate(self, texts: Any, source: str) -> list[str]:
        if self.fail:
            from ati_cloud.translate import TranslationError

            raise TranslationError(self.fail)
        self.calls.append((list(texts), source))
        return [f"[TR] {t}" for t in texts]


async def test_foreign_news_is_translated_to_turkish(
    app: Any, clock: Clock, db: psycopg.Connection[Any]
) -> None:
    admin = await activate_admin(app, clock, "kurucu@example.com", ["super_admin"])
    now = datetime.now(UTC)
    cms = {"data": {"catalogs": [{"articles": [{
        "code": "d" * 32,
        "title": "Binance Will List Testcoin (TST) with Seed Tag Applied",
        "releaseDate": int((now - timedelta(hours=1)).timestamp() * 1000),
    }]}]}}  # fmt: skip
    rss = _rss([("Bitcoin haftaya yatay başladı", "btc", now - timedelta(hours=1))])
    app.state.news_fetcher = _sources(cms, rss, [["BTCUSDT"]])
    translator = FakeTranslator()
    app.state.news_translator = translator

    summary = (await admin.http.post("/admin/v1/news/refresh")).json()
    assert summary["translated"] == 1 and summary["translation_error"] is None
    # Yalnızca İngilizce kaynak çevrilir (başlık + özet); Türkçe kaynak olduğu gibi kalır.
    assert translator.calls == [
        (
            [
                "Binance Will List Testcoin (TST) with Seed Tag Applied",
                "Binance resmî duyurusu (yeni listeleme kategorisi).",
            ],
            "en",
        )
    ]
    items = (await admin.http.get("/admin/v1/news", params={"status": None})).json()
    listing = (await admin.http.get("/admin/v1/news", params={"status": "drafted"})).json()
    tst = listing["items"][0]
    assert tst["lang"] == "en" and tst["title_tr"].startswith("[TR] Binance Will List")
    # Otomatik taslak Türkçe başlıkla, orijinal başlık metinde.
    draft = (await admin.http.get("/admin/v1/forum/queue")).json()["topics"][0]
    assert draft["title"].startswith("[TR] Binance Will List Testcoin")
    assert "Orijinal başlık: “Binance Will List Testcoin (TST)" in draft["body"]
    del items

    # Çeviri ayarları: DeepL anahtarsız seçilemez; anahtar şifreli saklanır, yalnızca ipucu döner.
    bad = await admin.http.put(
        "/admin/v1/news/translation", json={"enabled": True, "provider": "deepl"}
    )
    assert bad.status_code == 422
    saved = await admin.http.put(
        "/admin/v1/news/translation",
        json={"enabled": True, "provider": "deepl", "deepl_key": "gizli-anahtar-1234:fx"},
    )
    assert saved.json() == {"enabled": True, "provider": "deepl", "email": None,
                            "deepl_key_hint": "…4:fx"}  # fmt: skip
    stored = db.execute("SELECT value::text FROM system_settings WHERE key = 'news_translation'")
    assert "gizli-anahtar" not in stored.fetchone()[0]  # type: ignore[index]
    view = (await admin.http.get("/admin/v1/news")).json()["translation"]
    assert view["provider"] == "deepl" and view["deepl_key_hint"] == "…4:fx"

    # Tek haberi elle çevirme; servis hata verirse neden yazılır.
    row = db.execute(
        "INSERT INTO coin_news (source, external_id, kind, title, url, published_at, lang) "
        "VALUES ('cointelegraph', 'x1', 'news', 'Bitcoin rallies', "
        "'https://cointelegraph.com/news/x', now(), 'en') RETURNING id"
    ).fetchone()
    assert row
    done = await admin.http.post(f"/admin/v1/news/{row[0]}/translate")
    assert done.json()["title_tr"] == "[TR] Bitcoin rallies"
    app.state.news_translator = FakeTranslator(fail="MyMemory günlük çeviri kotası doldu")
    db.execute("UPDATE coin_news SET title_tr = NULL WHERE id = %s", (row[0],))
    failed = await admin.http.post(f"/admin/v1/news/{row[0]}/translate")
    assert failed.status_code == 502 and "kotası doldu" in failed.json()["detail"]


async def test_mymemory_client_parses_and_reports_quota() -> None:
    from ati_cloud.translate import MyMemory, TranslationError

    def handler(request: httpx.Request) -> httpx.Response:
        if "quota" in request.url.params["q"]:
            return httpx.Response(200, json={"quotaFinished": True, "responseStatus": 429})
        assert request.url.params["langpair"] == "en|tr"
        return httpx.Response(
            200,
            json={"responseStatus": 200, "responseData": {"translatedText": "Bitcoin &amp; Ether"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        mm = MyMemory(client, email=None)
        assert await mm.translate(["Bitcoin and Ether", ""], "en") == ["Bitcoin & Ether", ""]
        with pytest.raises(TranslationError, match="kotası"):
            await mm.translate(["quota"], "en")
