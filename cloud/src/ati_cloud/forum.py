"""Forum: müşteri konuları ve yanıtları, yönetici onayıyla yayımlanır.

Herkese açık (çerez gerekmez):
    GET  /v1/forum/topics               yayımlanmış konular (kategori, arama, sayfa)
    GET  /v1/forum/topics/{number}      konu ve yayımlanmış yanıtları

Müşteri (oturum çerezi, e-postası doğrulanmış; köken denetimi):
    POST /v1/forum/me/topics                    yeni konu → onay kuyruğu
    POST /v1/forum/me/topics/{number}/replies   yanıt → onay kuyruğu
    GET  /v1/forum/me                           kendi gönderileri ve durumları

Yönetici (``forum.moderate``):
    GET  /admin/v1/forum/queue                  onay bekleyen konular ve yanıtlar
    GET  /admin/v1/forum/topics                 bütün konular (durum süzgeci, arama)
    POST /admin/v1/forum/topics                 ekip konusu (doğrudan yayımlanır)
    POST /admin/v1/forum/topics/{id}/moderate   onayla, reddet, gizle, geri al, sabitle,
                                                kilitle, sil
    POST /admin/v1/forum/replies/{id}/moderate  onayla, reddet, gizle, geri al, sil

Metinler düz metin olarak saklanır ve gösterilir (HTML yorumlanmaz). Kazanç vaadi, bağlantı ve
iletişim bilgisi içeren gönderiler yöneticiye otomatik uyarıyla gelir; karar yöneticinindir.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import AfterValidator, BaseModel, Field

from ati_cloud.accounts import (
    Database,
    SlidingWindowLimiter,
    check_origin,
    customer_dependency,
    limited,
    session_customer_id,
)
from ati_cloud.admin.context import Admin, AdminContext
from ati_cloud.config import CloudSettings

CUSTOMER_CATEGORIES = ("genel", "strateji", "soru", "yeni-coin")
CATEGORIES = (*CUSTOMER_CATEGORIES, "haber")
CATEGORY_LABELS = {
    "genel": "Genel sohbet",
    "strateji": "Strateji ve analiz",
    "soru": "Soru ve yardım",
    "yeni-coin": "Yeni coinler",
    "haber": "Haberler",
}
TEAM_NAME = "AI Trading Ekibi"
PAGE_SIZE = 20
MAX_PENDING_TOPICS = 5
MAX_PENDING_REPLIES = 10

_CONTROL = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f​-‏‪-‮]")
_SPACES = re.compile(r"[ \t]+")
_BLANKS = re.compile(r"\n{3,}")
_NAME = re.compile(r"^[\w .\-]{2,40}$")

# Otomatik uyarılar: yönetici kuyruğunda rozet olarak görünür (gönderi reddedilmez).
FLAG_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "kazanç vaadi",
        re.compile(
            r"(?i)garanti\w*\s*(kazanç|kâr|kar|getiri)|kesin\s*(kazanç|kâr|kar)|risksiz|"
            r"zengin\s*ol|guaranteed\s*profit|garantili"
        ),
    ),
    ("bağlantı", re.compile(r"(?i)https?://|www\.|\b[\w-]+\.(com|net|org|io|xyz|me)\b")),
    (
        "iletişim / reklam",
        re.compile(
            r"(?i)t\.me/|telegram|whatsapp|\bdm\b|\+?\d[\d \-]{9,}\d|referans\s*kod|ref\s*link"
        ),
    ),
)


def clean_text(text: str, *, multiline: bool) -> str:
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    if not multiline:
        return _SPACES.sub(" ", text.replace("\n", " ")).strip()
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()


def flags_of(*texts: str) -> list[str]:
    joined = "\n".join(texts)
    return [name for name, rule in FLAG_RULES if rule.search(joined)]


def excerpt(body: str, limit: int = 220) -> str:
    flat = " ".join(body.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rsplit(" ", 1)[0] + "…"


def _name(value: str) -> str:
    value = clean_text(value, multiline=False)
    if not _NAME.match(value):
        raise ValueError("Ad 2-40 karakter olmalı; harf, rakam, boşluk, nokta ve tire")
    return value


def _title(value: str) -> str:
    value = clean_text(value, multiline=False)
    if len(value) < 5:
        raise ValueError("Başlık en az 5 karakter olmalı")
    return value


def _body(minimum: int) -> Any:
    def check(value: str) -> str:
        value = clean_text(value, multiline=True)
        if len(value) < minimum:
            raise ValueError(f"Metin en az {minimum} karakter olmalı")
        return value

    return check


def _symbol(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip().upper()
    if len(value) > 5 and value.endswith("USDT"):
        value = value.removesuffix("USDT")
    if not re.fullmatch(r"[A-Z0-9]{2,12}", value):
        raise ValueError("Coin sembolü 2-12 harf/rakam olmalı (ör. BTC)")
    return value


AuthorName = Annotated[str, Field(min_length=2, max_length=40), AfterValidator(_name)]
Title = Annotated[str, Field(min_length=5, max_length=120), AfterValidator(_title)]
TopicBody = Annotated[str, Field(min_length=10, max_length=5000), AfterValidator(_body(10))]
ReplyBody = Annotated[str, Field(min_length=2, max_length=3000), AfterValidator(_body(2))]
CoinSymbol = Annotated[str | None, Field(default=None, max_length=16), AfterValidator(_symbol)]


class TopicCreate(BaseModel):
    author_name: AuthorName
    category: Literal["genel", "strateji", "soru", "yeni-coin"]
    title: Title
    body: TopicBody
    coin_symbol: CoinSymbol = None


class ReplyCreate(BaseModel):
    author_name: AuthorName
    body: ReplyBody


class TeamTopic(BaseModel):
    category: Literal["genel", "strateji", "soru", "yeni-coin", "haber"]
    title: Title
    body: TopicBody
    coin_symbol: CoinSymbol = None
    pinned: bool = False


class LikeRequest(BaseModel):
    number: int = Field(ge=1)
    reply_id: str | None = Field(default=None, max_length=36)


class SentimentVote(BaseModel):
    vote: Literal["bull", "bear"]


class TopicModeration(BaseModel):
    action: Literal[
        "approve", "reject", "hide", "restore", "pin", "unpin", "lock", "unlock", "delete"
    ]
    note: str = Field(default="", max_length=300)


class ReplyModeration(BaseModel):
    action: Literal["approve", "reject", "hide", "restore", "delete"]
    note: str = Field(default="", max_length=300)


TOPIC_PUBLIC = (
    "t.number, t.title, t.category, t.coin_symbol, t.author_name, t.author_kind, t.pinned, "
    "(SELECT nickname::text FROM forum_profiles p WHERE p.customer_id = t.customer_id) "
    "AS author_nick, "
    "t.locked, t.source_name, t.source_url, t.view_count, t.published_at, "
    "(SELECT count(*) FROM forum_replies r WHERE r.topic_id = t.id AND r.status = 'approved') "
    "AS reply_count, "
    "(SELECT max(r.published_at) FROM forum_replies r WHERE r.topic_id = t.id "
    "AND r.status = 'approved') AS last_reply_at, "
    "(SELECT r.author_name FROM forum_replies r WHERE r.topic_id = t.id "
    "AND r.status = 'approved' ORDER BY r.published_at DESC LIMIT 1) AS last_reply_author"
)

# Yazarın yayımlanmış mesaj sayısı (forum rütbesi için): müşteride kendi konu + yanıtları,
# ekipte bütün ekip mesajları. Kişisel veri döndürülmez; yalnızca sayı.
AUTHOR_POSTS = (
    "CASE WHEN {a}.author_kind = 'team' THEN "
    "(SELECT count(*) FROM forum_topics x WHERE x.author_kind = 'team' AND x.status = 'approved') "
    "+ (SELECT count(*) FROM forum_replies y WHERE y.author_kind = 'team' "
    "AND y.status = 'approved') "
    "ELSE (SELECT count(*) FROM forum_topics x WHERE x.customer_id = {a}.customer_id "
    "AND x.status = 'approved') + (SELECT count(*) FROM forum_replies y "
    "WHERE y.customer_id = {a}.customer_id AND y.status = 'approved') END"
)


RESERVED_NAMES = {
    "ai trading ekibi",
    "ekip",
    "yönetici",
    "yonetici",
    "admin",
    "moderatör",
    "moderator",
}

# Profil istatistikleri (yayımlanmış mesajlar ve alınan beğeniler).
PROFILE_STATS = (
    "(SELECT count(*) FROM forum_topics x WHERE x.customer_id = p.customer_id "
    "AND x.status = 'approved') AS topics, "
    "(SELECT count(*) FROM forum_replies y WHERE y.customer_id = p.customer_id "
    "AND y.status = 'approved') AS replies, "
    "(SELECT count(*) FROM forum_likes l WHERE (l.target_type = 'topic' AND l.target_id IN "
    "(SELECT id FROM forum_topics x WHERE x.customer_id = p.customer_id "
    "AND x.status = 'approved')) "
    "OR (l.target_type = 'reply' AND l.target_id IN (SELECT id FROM forum_replies y "
    "WHERE y.customer_id = p.customer_id AND y.status = 'approved'))) AS likes"
)


async def author_name_for(conn: Any, customer_id: Any, requested: str) -> str:
    """Müşterinin forum adı kalıcıdır (profil ve rütbe): ilk gönderide seçilir, sonra değişmez.
    Ad başka bir üyedeyse ya da ayrılmış bir adsa reddedilir."""
    cur = await conn.execute(
        "SELECT nickname::text AS nickname FROM forum_profiles WHERE customer_id = %s",
        (customer_id,),
    )
    row = await cur.fetchone()
    if row is not None:
        return str(row["nickname"])
    if requested.casefold() in RESERVED_NAMES:
        raise HTTPException(status_code=422, detail="Bu ad kullanılamaz; başka bir ad seçin")
    cur = await conn.execute(
        "INSERT INTO forum_profiles (customer_id, nickname) VALUES (%s, %s) "
        "ON CONFLICT DO NOTHING RETURNING nickname::text AS nickname",
        (customer_id, requested),
    )
    created = await cur.fetchone()
    if created is None:
        raise HTTPException(
            status_code=409, detail="Bu forum adı başka bir üyede; başka bir ad seçin"
        )
    return str(created["nickname"])


async def create_team_topic(conn: Any, admin: Admin, body: TeamTopic, **source: Any) -> Any:
    """Ekip konusu: doğrudan yayımlanır (haber paylaşımı da bunu kullanır)."""
    cur = await conn.execute(
        "INSERT INTO forum_topics (author_kind, author_name, category, title, body, coin_symbol, "
        "source_name, source_url, status, moderated_by, moderated_at, published_at, pinned) "
        "VALUES ('team', %s, %s, %s, %s, %s, %s, %s, 'approved', %s, now(), now(), %s) "
        "RETURNING id, number",
        (
            TEAM_NAME,
            body.category,
            body.title,
            body.body,
            body.coin_symbol,
            source.get("source_name"),
            source.get("source_url"),
            admin.id,
            body.pinned,
        ),
    )
    return await cur.fetchone()


def create_forum_router(settings: CloudSettings, db: Database) -> APIRouter:
    router = APIRouter(prefix="/v1/forum")
    current_customer = customer_dependency(db)
    customer_dep = Depends(current_customer)
    topic_limit = SlidingWindowLimiter(5, 3600)
    reply_limit = SlidingWindowLimiter(20, 3600)
    like_limit = SlidingWindowLimiter(120, 3600)
    vote_limit = SlidingWindowLimiter(60, 3600)

    def verified(customer: dict[str, Any]) -> None:
        if customer.get("email_verified_at") is None:
            raise HTTPException(status_code=403, detail="Önce e-posta adresinizi doğrulayın")

    @router.get("/topics")
    async def list_topics(
        response: Response,
        category: Annotated[
            Literal["genel", "strateji", "soru", "yeni-coin", "haber"] | None, Query()
        ] = None,
        q: Annotated[str | None, Query(max_length=80)] = None,
        page: Annotated[int, Query(ge=1, le=500)] = 1,
    ) -> dict[str, Any]:
        params = {
            "category": category,
            "q": f"%{q.strip()}%" if q and q.strip() else None,
            "limit": PAGE_SIZE,
            "offset": (page - 1) * PAGE_SIZE,
        }
        where = (
            "t.status = 'approved' AND (%(category)s::text IS NULL OR t.category = %(category)s) "
            "AND (%(q)s::text IS NULL OR t.title ILIKE %(q)s OR t.body ILIKE %(q)s "
            "OR t.coin_symbol ILIKE %(q)s)"
        )
        async with db.connection() as conn:
            cur = await conn.execute(
                f"SELECT {TOPIC_PUBLIC}, t.body, {AUTHOR_POSTS.format(a='t')} AS author_posts "  # noqa: S608
                f"FROM forum_topics t WHERE {where} "
                "ORDER BY t.pinned DESC, t.published_at DESC LIMIT %(limit)s OFFSET %(offset)s",
                params,
            )
            rows = await cur.fetchall()
            cur = await conn.execute(
                f"SELECT count(*) AS n FROM forum_topics t WHERE {where}",  # noqa: S608
                params,
            )
            total = (await cur.fetchone() or {"n": 0})["n"]
            cur = await conn.execute(
                "SELECT category, count(*) AS n FROM forum_topics WHERE status = 'approved' "
                "GROUP BY category"
            )
            counts = {r["category"]: r["n"] for r in await cur.fetchall()}
        for row in rows:
            row["excerpt"] = excerpt(row.pop("body"))
        response.headers["Cache-Control"] = "public, max-age=15"
        return {
            "items": rows,
            "total": total,
            "page": page,
            "pages": max(1, -(-total // PAGE_SIZE)),
            "categories": [
                {"code": c, "label": CATEGORY_LABELS[c], "count": counts.get(c, 0)}
                for c in CATEGORIES
            ],
        }

    @router.get("/overview")
    async def overview(response: Response) -> dict[str, Any]:
        """Forum ana sayfası: bölümler (konu, mesaj, son mesaj), toplamlar, trend coinler."""
        async with db.connection() as conn:
            cur = await conn.execute(
                "SELECT t.category, count(*) AS topics, "
                "coalesce(sum((SELECT count(*) FROM forum_replies r WHERE r.topic_id = t.id "
                "AND r.status = 'approved')), 0) AS replies "
                "FROM forum_topics t WHERE t.status = 'approved' GROUP BY t.category"
            )
            stats = {r["category"]: r for r in await cur.fetchall()}
            # Bölümün son mesajı: en son yayımlanan konu ya da yanıt.
            cur = await conn.execute(
                "SELECT DISTINCT ON (category) category, number, title, author_name, at FROM ("
                "SELECT t.category, t.number, t.title, t.author_name, t.published_at AS at "
                "FROM forum_topics t WHERE t.status = 'approved' UNION ALL "
                "SELECT t.category, t.number, t.title, r.author_name, r.published_at AS at "
                "FROM forum_replies r JOIN forum_topics t ON t.id = r.topic_id "
                "WHERE r.status = 'approved' AND t.status = 'approved') x "
                "ORDER BY category, at DESC"
            )
            last = {r.pop("category"): r for r in await cur.fetchall()}
            cur = await conn.execute(
                "SELECT count(DISTINCT coalesce(customer_id::text, 'ekip')) AS members FROM ("
                "SELECT customer_id FROM forum_topics WHERE status = 'approved' UNION ALL "
                "SELECT customer_id FROM forum_replies WHERE status = 'approved') x"
            )
            members = (await cur.fetchone() or {"members": 0})["members"]
            cur = await conn.execute(
                "SELECT coin_symbol AS symbol, count(*) AS topics FROM forum_topics "
                "WHERE status = 'approved' AND coin_symbol IS NOT NULL "
                "AND published_at > now() - interval '30 days' "
                "GROUP BY coin_symbol ORDER BY count(*) DESC, max(published_at) DESC LIMIT 8"
            )
            trending = await cur.fetchall()
            cur = await conn.execute(
                "SELECT number, title, coin_symbol, author_name, published_at FROM forum_topics "
                "WHERE status = 'approved' AND category = 'yeni-coin' "
                "ORDER BY published_at DESC LIMIT 5"
            )
            listings = await cur.fetchall()
            cur = await conn.execute(
                "SELECT nickname::text AS nickname FROM forum_profiles "
                "ORDER BY created_at DESC LIMIT 1"
            )
            newest = await cur.fetchone()
            cur = await conn.execute(
                "SELECT (SELECT count(*) FROM forum_topics WHERE status = 'approved' "
                "AND published_at > now() - interval '24 hours') + (SELECT count(*) "
                "FROM forum_replies WHERE status = 'approved' "
                "AND published_at > now() - interval '24 hours') AS n"
            )
            posts_24h = (await cur.fetchone() or {"n": 0})["n"]
        categories = []
        for code in CATEGORIES:
            row = stats.get(code) or {"topics": 0, "replies": 0}
            categories.append(
                {
                    "code": code,
                    "label": CATEGORY_LABELS[code],
                    "topics": row["topics"],
                    "replies": int(row["replies"]),
                    "last": last.get(code),
                }
            )
        response.headers["Cache-Control"] = "public, max-age=15"
        return {
            "totals": {
                "topics": sum(c["topics"] for c in categories),
                "posts": sum(c["topics"] + c["replies"] for c in categories),
                "members": members,
            },
            "categories": categories,
            "trending": trending,
            "listings": listings,
            "newest_member": newest["nickname"] if newest else None,
            "posts_24h": posts_24h,
        }

    @router.get("/topics/{number}")
    async def topic(number: int, response: Response) -> dict[str, Any]:
        if number < 1 or number > 2**62:
            raise HTTPException(status_code=404, detail="Konu bulunamadı")
        async with db.connection() as conn:
            cur = await conn.execute(
                "UPDATE forum_topics SET view_count = view_count + 1 "
                "WHERE number = %s AND status = 'approved' RETURNING id",
                (number,),
            )
            found = await cur.fetchone()
            if found is None:
                raise HTTPException(status_code=404, detail="Konu bulunamadı")
            cur = await conn.execute(
                f"SELECT {TOPIC_PUBLIC}, t.body, {AUTHOR_POSTS.format(a='t')} AS author_posts, "  # noqa: S608
                "(SELECT nickname::text FROM forum_profiles p WHERE p.customer_id = t.customer_id) "
                "AS author_nick, (SELECT count(*) FROM forum_likes l WHERE l.target_type = 'topic' "
                "AND l.target_id = t.id) AS like_count, "
                "(SELECT count(*) FROM forum_sentiment s WHERE s.topic_id = t.id "
                "AND s.vote = 'bull') AS bull, (SELECT count(*) FROM forum_sentiment s "
                "WHERE s.topic_id = t.id AND s.vote = 'bear') AS bear "
                "FROM forum_topics t WHERE t.id = %s",
                (found["id"],),
            )
            row = await cur.fetchone()
            cur = await conn.execute(
                f"SELECT r.id::text AS id, r.author_name, r.author_kind, r.body, r.published_at, "  # noqa: S608
                f"{AUTHOR_POSTS.format(a='r')} AS author_posts, "
                "(SELECT nickname::text FROM forum_profiles p WHERE p.customer_id = r.customer_id) "
                "AS author_nick, (SELECT count(*) FROM forum_likes l WHERE l.target_type = 'reply' "
                "AND l.target_id = r.id) AS like_count FROM forum_replies r "
                "WHERE r.topic_id = %s AND r.status = 'approved' ORDER BY r.published_at LIMIT 500",
                (found["id"],),
            )
            replies = await cur.fetchall()
        response.headers["Cache-Control"] = "no-store"
        data = dict(row or {})
        bull, bear = int(data.pop("bull", 0)), int(data.pop("bear", 0))
        data["sentiment"] = {"bull": bull, "bear": bear} if data.get("coin_symbol") else None
        return {**data, "replies": replies}

    @router.get("/members/{nickname}")
    async def member(nickname: str, response: Response) -> dict[str, Any]:
        """Üye profili: rütbe için yayımlanmış mesaj sayısı, alınan beğeni ve son konular."""
        if not _NAME.match(nickname):
            raise HTTPException(status_code=404, detail="Üye bulunamadı")
        async with db.connection() as conn:
            cur = await conn.execute(
                f"SELECT p.customer_id, p.nickname::text AS nickname, p.created_at, {PROFILE_STATS} "  # noqa: S608, E501
                "FROM forum_profiles p WHERE p.nickname = %s",
                (nickname,),
            )
            row = await cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Üye bulunamadı")
            cur = await conn.execute(
                "SELECT t.number, t.title, t.category, t.coin_symbol, t.published_at, "
                "(SELECT count(*) FROM forum_replies r WHERE r.topic_id = t.id "
                "AND r.status = 'approved') AS reply_count FROM forum_topics t "
                "WHERE t.customer_id = %s AND t.status = 'approved' "
                "ORDER BY t.published_at DESC LIMIT 10",
                (row.pop("customer_id"),),
            )
            recent = await cur.fetchall()
        response.headers["Cache-Control"] = "public, max-age=30"
        return {
            "nickname": row["nickname"],
            "joined_at": row["created_at"],
            "topics": row["topics"],
            "replies": row["replies"],
            "posts": row["topics"] + row["replies"],
            "likes": row["likes"],
            "recent_topics": recent,
        }

    @router.get("/leaderboard")
    async def leaderboard(response: Response) -> list[dict[str, Any]]:
        """En aktif üyeler (yayımlanmış mesaj, eşitlikte beğeni)."""
        async with db.connection() as conn:
            cur = await conn.execute(
                f"SELECT * FROM (SELECT p.nickname::text AS nickname, p.created_at, {PROFILE_STATS} "  # noqa: S608, E501
                "FROM forum_profiles p) x WHERE x.topics + x.replies > 0 "
                "ORDER BY x.topics + x.replies DESC, x.likes DESC, x.created_at LIMIT 20"
            )
            rows = await cur.fetchall()
        response.headers["Cache-Control"] = "public, max-age=60"
        return [
            {
                "nickname": r["nickname"],
                "posts": r["topics"] + r["replies"],
                "topics": r["topics"],
                "likes": r["likes"],
            }
            for r in rows
        ]

    @router.post("/me/topics", status_code=202)
    async def create_topic(
        body: TopicCreate, request: Request, customer: dict[str, Any] = customer_dep
    ) -> dict[str, Any]:
        check_origin(settings, request)
        verified(customer)
        limited(topic_limit, str(customer["id"]))
        async with db.connection() as conn:
            cur = await conn.execute(
                "SELECT count(*) AS n FROM forum_topics WHERE customer_id = %s "
                "AND status = 'pending'",
                (customer["id"],),
            )
            if (await cur.fetchone() or {"n": 0})["n"] >= MAX_PENDING_TOPICS:
                raise HTTPException(
                    status_code=429,
                    detail="Onay bekleyen konunuz çok fazla. Önceki konular onaylanınca tekrar "
                    "deneyin.",
                )
            cur = await conn.execute(
                "INSERT INTO forum_topics (customer_id, author_kind, author_name, category, "
                "title, body, coin_symbol, flags) VALUES (%s, 'customer', %s, %s, %s, %s, %s, %s) "
                "RETURNING number",
                (
                    customer["id"],
                    await author_name_for(conn, customer["id"], body.author_name),
                    body.category,
                    body.title,
                    body.body,
                    body.coin_symbol,
                    flags_of(body.title, body.body),
                ),
            )
            row = await cur.fetchone()
        return {
            "number": row["number"] if row else None,
            "status": "pending",
            "message": "Konunuz alındı. Yönetici onayından sonra forumda yayımlanır.",
        }

    @router.post("/me/topics/{number}/replies", status_code=202)
    async def create_reply(
        number: int, body: ReplyCreate, request: Request, customer: dict[str, Any] = customer_dep
    ) -> dict[str, Any]:
        check_origin(settings, request)
        verified(customer)
        limited(reply_limit, str(customer["id"]))
        async with db.connection() as conn:
            cur = await conn.execute(
                "SELECT id, locked FROM forum_topics WHERE number = %s AND status = 'approved'",
                (number,),
            )
            topic = await cur.fetchone()
            if topic is None:
                raise HTTPException(status_code=404, detail="Konu bulunamadı")
            if topic["locked"]:
                raise HTTPException(status_code=409, detail="Bu konu yanıtlara kapatıldı")
            cur = await conn.execute(
                "SELECT count(*) AS n FROM forum_replies WHERE customer_id = %s "
                "AND status = 'pending'",
                (customer["id"],),
            )
            if (await cur.fetchone() or {"n": 0})["n"] >= MAX_PENDING_REPLIES:
                raise HTTPException(
                    status_code=429, detail="Onay bekleyen yanıtınız çok fazla. Biraz bekleyin."
                )
            await conn.execute(
                "INSERT INTO forum_replies (topic_id, customer_id, author_kind, author_name, "
                "body, flags) VALUES (%s, %s, 'customer', %s, %s, %s)",
                (
                    topic["id"],
                    customer["id"],
                    await author_name_for(conn, customer["id"], body.author_name),
                    body.body,
                    flags_of(body.body),
                ),
            )
        return {
            "status": "pending",
            "message": "Yanıtınız alındı. Yönetici onayından sonra konuda görünür.",
        }

    @router.get("/me")
    async def mine(customer: dict[str, Any] = customer_dep) -> dict[str, Any]:
        async with db.connection() as conn:
            cur = await conn.execute(
                "SELECT number, title, category, status, moderation_note, created_at, "
                "published_at FROM forum_topics WHERE customer_id = %s "
                "ORDER BY created_at DESC LIMIT 100",
                (customer["id"],),
            )
            topics = await cur.fetchall()
            cur = await conn.execute(
                "SELECT t.number, t.title, r.body, r.status, r.moderation_note, r.created_at "
                "FROM forum_replies r JOIN forum_topics t ON t.id = r.topic_id "
                "WHERE r.customer_id = %s ORDER BY r.created_at DESC LIMIT 100",
                (customer["id"],),
            )
            replies = await cur.fetchall()
            cur = await conn.execute(
                f"SELECT p.nickname::text AS nickname, p.created_at, {PROFILE_STATS} "  # noqa: S608
                "FROM forum_profiles p WHERE p.customer_id = %s",
                (customer["id"],),
            )
            profile = await cur.fetchone()
        for reply in replies:
            reply["body"] = excerpt(reply["body"], 160)
        if profile is not None:
            profile["posts"] = profile["topics"] + profile["replies"]
        return {"topics": topics, "replies": replies, "profile": profile}

    @router.get("/whoami")
    async def whoami(request: Request, response: Response) -> dict[str, Any]:
        """Forum çubuğu için: oturum açık mı, forum adı ve rütbe sayısı (ziyaretçiye de 200)."""
        response.headers["Cache-Control"] = "no-store"
        customer_id = await session_customer_id(db, request)
        if customer_id is None:
            return {"logged_in": False, "profile": None}
        async with db.connection() as conn:
            cur = await conn.execute(
                f"SELECT p.nickname::text AS nickname, {PROFILE_STATS} "  # noqa: S608
                "FROM forum_profiles p WHERE p.customer_id = %s",
                (customer_id,),
            )
            profile = await cur.fetchone()
        if profile is not None:
            profile["posts"] = profile["topics"] + profile["replies"]
        return {"logged_in": True, "profile": profile}

    @router.get("/me/topics/{number}/state")
    async def my_state(number: int, customer: dict[str, Any] = customer_dep) -> dict[str, Any]:
        """Konuda kişinin beğendikleri ve yükseliş/düşüş oyu (düğmelerin durumu)."""
        async with db.connection() as conn:
            topic = await _approved_topic(conn, number)
            cur = await conn.execute(
                "SELECT l.target_type, l.target_id::text AS target_id FROM forum_likes l "
                "WHERE l.customer_id = %s AND ((l.target_type = 'topic' AND l.target_id = %s) "
                "OR (l.target_type = 'reply' AND l.target_id IN "
                "(SELECT id FROM forum_replies WHERE topic_id = %s)))",
                (customer["id"], topic["id"], topic["id"]),
            )
            liked = [
                "topic" if r["target_type"] == "topic" else r["target_id"]
                for r in await cur.fetchall()
            ]
            cur = await conn.execute(
                "SELECT vote FROM forum_sentiment WHERE topic_id = %s AND customer_id = %s",
                (topic["id"], customer["id"]),
            )
            vote = await cur.fetchone()
        return {"liked": liked, "vote": vote["vote"] if vote else None}

    @router.post("/me/like")
    async def like(
        body: LikeRequest, request: Request, customer: dict[str, Any] = customer_dep
    ) -> dict[str, Any]:
        """Beğeni (aç/kapa). Kendi mesajınızı beğenemezsiniz."""
        check_origin(settings, request)
        verified(customer)
        limited(like_limit, str(customer["id"]))
        async with db.connection() as conn, conn.transaction():
            topic = await _approved_topic(conn, body.number)
            if body.reply_id is None:
                target_type, target_id, owner = "topic", topic["id"], topic["customer_id"]
            else:
                cur = await conn.execute(
                    "SELECT id, customer_id FROM forum_replies WHERE id = %s AND topic_id = %s "
                    "AND status = 'approved'",
                    (_uuid(body.reply_id), topic["id"]),
                )
                reply = await cur.fetchone()
                if reply is None:
                    raise HTTPException(status_code=404, detail="Yanıt bulunamadı")
                target_type, target_id, owner = "reply", reply["id"], reply["customer_id"]
            if owner == customer["id"]:
                raise HTTPException(status_code=409, detail="Kendi mesajınızı beğenemezsiniz")
            cur = await conn.execute(
                "DELETE FROM forum_likes WHERE customer_id = %s AND target_type = %s "
                "AND target_id = %s RETURNING target_id",
                (customer["id"], target_type, target_id),
            )
            removed = await cur.fetchone() is not None
            if not removed:
                await conn.execute(
                    "INSERT INTO forum_likes (customer_id, target_type, target_id) "
                    "VALUES (%s, %s, %s)",
                    (customer["id"], target_type, target_id),
                )
            cur = await conn.execute(
                "SELECT count(*) AS n FROM forum_likes WHERE target_type = %s AND target_id = %s",
                (target_type, target_id),
            )
            count = (await cur.fetchone() or {"n": 0})["n"]
        return {"liked": not removed, "count": count}

    @router.post("/me/topics/{number}/sentiment")
    async def sentiment(
        number: int, body: SentimentVote, request: Request, customer: dict[str, Any] = customer_dep
    ) -> dict[str, Any]:
        """Coin konusunda yükseliş / düşüş beklentisi (kişi başı bir oy, değiştirilebilir)."""
        check_origin(settings, request)
        verified(customer)
        limited(vote_limit, str(customer["id"]))
        async with db.connection() as conn:
            topic = await _approved_topic(conn, number)
            if not topic["coin_symbol"]:
                raise HTTPException(status_code=409, detail="Bu konuda coin oylaması yok")
            await conn.execute(
                "INSERT INTO forum_sentiment (topic_id, customer_id, vote) VALUES (%s, %s, %s) "
                "ON CONFLICT (topic_id, customer_id) DO UPDATE SET vote = EXCLUDED.vote, "
                "updated_at = now()",
                (topic["id"], customer["id"], body.vote),
            )
            cur = await conn.execute(
                "SELECT count(*) FILTER (WHERE vote = 'bull') AS bull, "
                "count(*) FILTER (WHERE vote = 'bear') AS bear FROM forum_sentiment "
                "WHERE topic_id = %s",
                (topic["id"],),
            )
            counts = await cur.fetchone() or {"bull": 0, "bear": 0}
        return {"vote": body.vote, "bull": counts["bull"], "bear": counts["bear"]}

    async def _approved_topic(conn: Any, number: int) -> Any:
        if number < 1 or number > 2**62:
            raise HTTPException(status_code=404, detail="Konu bulunamadı")
        cur = await conn.execute(
            "SELECT id, customer_id, coin_symbol FROM forum_topics WHERE number = %s "
            "AND status = 'approved'",
            (number,),
        )
        topic = await cur.fetchone()
        if topic is None:
            raise HTTPException(status_code=404, detail="Konu bulunamadı")
        return topic

    return router


def _uuid(value: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", value):
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı")
    return value


TOPIC_TRANSITIONS: dict[str, tuple[tuple[str, ...], str]] = {
    # eylem: (izinli eski durumlar, yeni durum)
    "approve": (("pending", "rejected", "hidden"), "approved"),
    "reject": (("pending",), "rejected"),
    "hide": (("approved",), "hidden"),
    "restore": (("hidden", "rejected"), "approved"),
}


def create_admin_forum_router(ctx: AdminContext) -> APIRouter:
    router = APIRouter(prefix="/admin/v1/forum")
    moderate = ctx.depends("forum.moderate")

    @router.get("/queue")
    async def queue(admin: Admin = moderate) -> dict[str, Any]:
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT t.id, t.number, t.title, t.body, t.category, t.coin_symbol, "
                "t.author_name, t.author_kind, t.flags, t.created_at, t.source_name, "
                "t.source_url, c.email::text AS customer_email, "
                "(SELECT count(*) FROM forum_topics x WHERE x.customer_id = t.customer_id "
                "AND x.status = 'approved') AS author_approved "
                "FROM forum_topics t LEFT JOIN customers c ON c.id = t.customer_id "
                "WHERE t.status = 'pending' ORDER BY t.created_at LIMIT 200"
            )
            topics = await cur.fetchall()
            cur = await conn.execute(
                "SELECT r.id, r.body, r.author_name, r.flags, r.created_at, t.number, "
                "t.title AS topic_title, c.email::text AS customer_email "
                "FROM forum_replies r JOIN forum_topics t ON t.id = r.topic_id "
                "LEFT JOIN customers c ON c.id = r.customer_id "
                "WHERE r.status = 'pending' ORDER BY r.created_at LIMIT 300"
            )
            replies = await cur.fetchall()
        return {"topics": topics, "replies": replies}

    @router.get("/topics")
    async def topics(
        admin: Admin = moderate,
        status: Annotated[
            Literal["pending", "approved", "rejected", "hidden"] | None, Query()
        ] = None,
        q: Annotated[str | None, Query(max_length=80)] = None,
    ) -> list[dict[str, Any]]:
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT t.id, t.number, t.title, t.category, t.coin_symbol, t.author_name, "
                "t.author_kind, t.status, t.pinned, t.locked, t.flags, t.view_count, "
                "t.moderation_note, t.created_at, t.published_at, "
                "(SELECT count(*) FROM forum_replies r WHERE r.topic_id = t.id "
                "AND r.status = 'approved') AS reply_count "
                "FROM forum_topics t WHERE (%(status)s::text IS NULL OR t.status = %(status)s) "
                "AND (%(q)s::text IS NULL OR t.title ILIKE %(q)s OR t.author_name ILIKE %(q)s) "
                "ORDER BY t.pinned DESC, coalesce(t.published_at, t.created_at) DESC LIMIT 200",
                {"status": status, "q": f"%{q.strip()}%" if q and q.strip() else None},
            )
            return await cur.fetchall()

    @router.post("/topics", status_code=201)
    async def team_topic(body: TeamTopic, request: Request, admin: Admin = moderate) -> Any:
        async with ctx.db.connection() as conn, conn.transaction():
            row = await create_team_topic(conn, admin, body)
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.forum_team_topic",
                target_type="forum_topic", target_id=row["id"], details={"title": body.title},
            )  # fmt: skip
        return row

    @router.post("/topics/{topic_id}/moderate")
    async def moderate_topic(
        topic_id: str, body: TopicModeration, request: Request, admin: Admin = moderate
    ) -> dict[str, Any]:
        tid = _uuid(topic_id)
        note = clean_text(body.note, multiline=False)
        if body.action == "reject" and len(note) < 3:
            raise HTTPException(status_code=422, detail="Reddetme nedeni yazın (müşteri görür)")
        async with ctx.db.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "SELECT status, title FROM forum_topics WHERE id = %s FOR UPDATE", (tid,)
            )
            row = await cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Konu bulunamadı")
            status = row["status"]
            if body.action == "delete":
                await conn.execute(
                    "UPDATE coin_news SET status = 'dismissed' WHERE topic_id = %s "
                    "AND status = 'drafted'",
                    (tid,),
                )
                await conn.execute(
                    "DELETE FROM forum_likes WHERE (target_type = 'topic' AND target_id = %s) "
                    "OR (target_type = 'reply' AND target_id IN "
                    "(SELECT id FROM forum_replies WHERE topic_id = %s))",
                    (tid, tid),
                )
                await conn.execute("DELETE FROM forum_topics WHERE id = %s", (tid,))
                status = "deleted"
            elif body.action in TOPIC_TRANSITIONS:
                allowed, status = TOPIC_TRANSITIONS[body.action]
                if row["status"] not in allowed:
                    raise HTTPException(
                        status_code=409, detail="Konunun şimdiki durumunda bu işlem yapılamaz"
                    )
                await conn.execute(
                    "UPDATE forum_topics SET status = %s, moderation_note = %s, "
                    "moderated_by = %s, moderated_at = now(), "
                    "published_at = CASE WHEN %s = 'approved' THEN coalesce(published_at, now()) "
                    "ELSE published_at END WHERE id = %s",
                    (status, note or None, admin.id, status, tid),
                )
                # Otomatik taslağın haberi: onaylanınca paylaşılmış, reddedilince gizli sayılır.
                news_status = {"approved": "shared", "rejected": "dismissed"}.get(status)
                if news_status:
                    await conn.execute(
                        "UPDATE coin_news SET status = %s WHERE topic_id = %s "
                        "AND status IN ('drafted', 'dismissed', 'shared')",
                        (news_status, tid),
                    )
            else:
                column, value = {
                    "pin": ("pinned", True),
                    "unpin": ("pinned", False),
                    "lock": ("locked", True),
                    "unlock": ("locked", False),
                }[body.action]
                await conn.execute(
                    f"UPDATE forum_topics SET {column} = %s WHERE id = %s",  # noqa: S608
                    (value, tid),
                )
            await ctx.audit(
                conn, request, actor_id=admin.id, action=f"admin.forum_topic_{body.action}",
                target_type="forum_topic", target_id=tid,
                details={"title": row["title"], "note": note},
            )  # fmt: skip
        return {"id": tid, "status": status}

    @router.post("/topics/{topic_id}/edit")
    async def edit_topic(
        topic_id: str, body: TeamTopic, request: Request, admin: Admin = moderate
    ) -> dict[str, Any]:
        """Ekip konusunu (ör. otomatik taslak) düzenler. Müşteri metinleri düzenlenmez."""
        tid = _uuid(topic_id)
        async with ctx.db.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "UPDATE forum_topics SET category = %s, title = %s, body = %s, coin_symbol = %s "
                "WHERE id = %s AND author_kind = 'team' RETURNING number",
                (body.category, body.title, body.body, body.coin_symbol, tid),
            )
            row = await cur.fetchone()
            if row is None:
                raise HTTPException(
                    status_code=404, detail="Ekip konusu bulunamadı (müşteri metni düzenlenemez)"
                )
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.forum_topic_edit",
                target_type="forum_topic", target_id=tid, details={"title": body.title},
            )  # fmt: skip
        return {"id": tid, "number": row["number"]}

    @router.get("/pending-count")
    async def pending_count(admin: Admin = moderate) -> dict[str, int]:
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT (SELECT count(*) FROM forum_topics WHERE status = 'pending') AS topics, "
                "(SELECT count(*) FROM forum_replies WHERE status = 'pending') AS replies"
            )
            row = await cur.fetchone() or {"topics": 0, "replies": 0}
        return {"topics": row["topics"], "replies": row["replies"]}

    @router.post("/replies/{reply_id}/moderate")
    async def moderate_reply(
        reply_id: str, body: ReplyModeration, request: Request, admin: Admin = moderate
    ) -> dict[str, Any]:
        rid = _uuid(reply_id)
        note = clean_text(body.note, multiline=False)
        if body.action == "reject" and len(note) < 3:
            raise HTTPException(status_code=422, detail="Reddetme nedeni yazın (müşteri görür)")
        async with ctx.db.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "SELECT status FROM forum_replies WHERE id = %s FOR UPDATE", (rid,)
            )
            row = await cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Yanıt bulunamadı")
            if body.action == "delete":
                await conn.execute(
                    "DELETE FROM forum_likes WHERE target_type = 'reply' AND target_id = %s",
                    (rid,),
                )
                await conn.execute("DELETE FROM forum_replies WHERE id = %s", (rid,))
                status = "deleted"
            else:
                allowed, status = TOPIC_TRANSITIONS[body.action]
                if row["status"] not in allowed:
                    raise HTTPException(
                        status_code=409, detail="Yanıtın şimdiki durumunda bu işlem yapılamaz"
                    )
                await conn.execute(
                    "UPDATE forum_replies SET status = %s, moderation_note = %s, "
                    "moderated_by = %s, moderated_at = now(), "
                    "published_at = CASE WHEN %s = 'approved' THEN coalesce(published_at, now()) "
                    "ELSE published_at END WHERE id = %s",
                    (status, note or None, admin.id, status, rid),
                )
            await ctx.audit(
                conn, request, actor_id=admin.id, action=f"admin.forum_reply_{body.action}",
                target_type="forum_reply", target_id=rid, details={"note": note},
            )  # fmt: skip
        return {"id": rid, "status": status}

    return router
