"""Coin haberleri: herkese açık kaynaklardan düzenli çekilir; yönetici beğendiğini foruma paylaşır.

Kaynaklar (hepsi herkese açık, kimlik bilgisi kullanılmaz; kimsenin hesabına erişilmez):

* **Binance duyuruları** — "New Cryptocurrency Listing" kategorisi (binance.com'un kendi duyuru
  sayfasını besleyen açık uç nokta). Yeni listelemeler, vadeli işlem sözleşmeleri.
* **Binance yeni işlem çiftleri** — resmî açık piyasa API'si (``/api/v3/ticker/price``). İlk
  çalıştırmada bilinen çiftler kaydedilir; sonra eklenen her çift haber olur.
* **Kripto haber siteleri** — RSS akışları (Cointelegraph, BTCHaber, Uzmancoin, Investing.com
  Türkiye). Listeleme / yeni token haberleri "Yeni coin" olarak işaretlenir.

Yalnızca başlık, kısa özet (en çok 300 karakter) ve kaynağa bağlantı saklanır; haberin tamamı
kopyalanmaz. Bağlantılar yalnızca ``https`` ve kaynağın kendi alan adı olabilir.

**Otomatik taslak** (panelden açılıp kapatılır, varsayılan açık): yeni bir coin haberi (listeleme,
coin sembolü belli, son 48 saatte yayımlanmış) gelince forumda ekip konusu taslağı hazırlanır ve
**onay kuyruğuna** düşer; yönetici onaylamadan yayımlanmaz. Aynı coin için son 24 saatte konu varsa
yeni taslak açılmaz; bir turda en çok 10 taslak.

API sürecinde arka planda çalışır (``ATI_NEWS_INTERVAL_S``, varsayılan 15 dakika; 0 kapatır).
Birden çok süreç çalışsa da veritabanındaki "sıra bende" kaydı sayesinde tek çekim yapılır.

Yönetici (``forum.moderate``):
    GET  /admin/v1/news                    haberler (tür / durum süzgeci) ve kaynak durumu
    POST /admin/v1/news/refresh            hemen çek
    PUT  /admin/v1/news/sources            kaynakları aç / kapat
    POST /admin/v1/news/{id}/share         foruma ekip konusu olarak paylaş
    POST /admin/v1/news/{id}/status        gizle / geri al
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import html
import json
import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from ati_cloud.accounts import Database
from ati_cloud.admin.context import Admin, AdminContext
from ati_cloud.admin.security import SecretBox
from ati_cloud.forum import (
    TEAM_NAME,
    CoinSymbol,
    TeamTopic,
    Title,
    TopicBody,
    create_team_topic,
)
from ati_cloud.translate import (
    SECRET_AAD,
    Translator,
    public_view,
    translator_from,
)
from ati_cloud.translate import SETTINGS_KEY as TRANSLATION_KEY
from ati_cloud.translate import describe as describe_translation
from ati_cloud.translate import load_settings as load_translation

logger = logging.getLogger(__name__)

MAX_BYTES = 3 * 1024 * 1024
AUTO_DRAFT_MAX_AGE = timedelta(hours=48)
AUTO_DRAFT_PER_RUN = 10
AUTO_FLAG = "otomatik taslak"
KEEP_ROWS = 3000
USER_AGENT = "Mozilla/5.0 (compatible; ATI-News/1.0)"

# Listeleme / yeni coin haberini tanıyan ifadeler (Türkçe ve İngilizce başlık ve özetlerde).
LISTING = re.compile(
    r"(?i)\b(will\s+list|lists|listed|listing|new\s+(coin|token)s?|launchpool|launchpad|"
    r"megadrop|hodler\s+airdrop|airdrop|pre-?market|perpetual\s+contract|alpha|"
    r"listele\w*|listeye\s+ekle\w*|yeni\s+(coin|token|kripto)\w*|işlem\s+görmeye|"
    r"ön\s*satış|presale|token\s+satış\w*|ieo|ido)\b"
)
_SYMBOL_PAREN = re.compile(r"\(([A-Z0-9]{2,12})\)")
_SYMBOL_DOLLAR = re.compile(r"\$([A-Z][A-Z0-9]{1,11})\b")
_TAGS = re.compile(r"<[^>]+>")
QUOTES = ("USDT", "USDC", "FDUSD", "TRY", "BTC", "ETH", "BNB", "EUR", "TUSD", "DAI", "BRL", "JPY")
IGNORED_SYMBOLS = {"USD", "USDT", "USDC", "UTC", "AI", "ETF", "CEO", "SEC", "NFT", "TVL", "API"}


@dataclass(frozen=True)
class Source:
    key: str
    name: str
    kind: Literal["binance_cms", "binance_pairs", "rss"]
    url: str
    hosts: tuple[str, ...]
    lang: str = "tr"  # haberlerin dili (Türkçe değilse çevrilir)


SOURCES: dict[str, Source] = {
    s.key: s
    for s in (
        Source(
            "binance",
            "Binance duyuruları",
            "binance_cms",
            "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
            "?type=1&catalogId=48&pageNo=1&pageSize=30",
            ("www.binance.com",),
            "en",
        ),
        Source(
            "binance_pairs",
            "Binance yeni işlem çiftleri",
            "binance_pairs",
            "https://api.binance.com/api/v3/ticker/price",
            ("www.binance.com",),
        ),
        Source(
            "cointelegraph",
            "Cointelegraph",
            "rss",
            "https://cointelegraph.com/rss",
            ("cointelegraph.com",),
            "en",
        ),
        Source(
            "btchaber",
            "BTCHaber",
            "rss",
            "https://www.btchaber.com/feed/",
            ("www.btchaber.com", "btchaber.com"),
        ),
        Source(
            "uzmancoin",
            "Uzmancoin",
            "rss",
            "https://uzmancoin.com/feed/",
            ("uzmancoin.com", "www.uzmancoin.com"),
        ),
        Source(
            "investing",
            "Investing.com Türkiye",
            "rss",
            "https://tr.investing.com/rss/news_301.rss",
            ("tr.investing.com",),
        ),
    )
}


@dataclass
class Item:
    source: str
    external_id: str
    kind: Literal["listing", "news"]
    title: str
    url: str
    published_at: datetime
    summary: str = ""
    symbols: list[str] = field(default_factory=list)
    title_tr: str | None = None
    summary_tr: str | None = None

    @property
    def lang(self) -> str:
        source = SOURCES.get(self.source)
        return source.lang if source else "tr"


# --- Ayrıştırma ----------------------------------------------------------------------------------


def plain(text: str | None, limit: int) -> str:
    text = html.unescape(_TAGS.sub(" ", text or ""))
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def symbols_in(*texts: str) -> list[str]:
    found: list[str] = []
    for text in texts:
        for match in (*_SYMBOL_PAREN.findall(text), *_SYMBOL_DOLLAR.findall(text)):
            if match not in IGNORED_SYMBOLS and not match.isdigit() and match not in found:
                found.append(match)
    return found[:8]


def safe_url(url: str, hosts: tuple[str, ...]) -> str | None:
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme != "https" or (parts.hostname or "") not in hosts or len(url) > 500:
        return None
    if any(ch.isspace() for ch in url):
        return None
    return url


def parse_date(value: str | None) -> datetime:
    if value:
        value = value.strip()
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            try:
                parsed = datetime.fromisoformat(value.replace(" ", "T"))
            except ValueError:
                parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            now = datetime.now(UTC)
            return min(parsed, now)
    return datetime.now(UTC)


def classify(title: str, summary: str) -> Literal["listing", "news"]:
    return "listing" if LISTING.search(title) or LISTING.search(summary[:200]) else "news"


def parse_binance_cms(source: Source, payload: Any) -> list[Item]:
    items: list[Item] = []
    catalogs = (
        (payload or {}).get("data", {}).get("catalogs", []) if isinstance(payload, dict) else []
    )
    for catalog in catalogs:
        for article in catalog.get("articles", []) or []:
            code = str(article.get("code", ""))
            title = plain(str(article.get("title", "")), 300)
            if not re.fullmatch(r"[0-9a-f]{16,64}", code) or not title:
                continue
            released = article.get("releaseDate")
            published = (
                min(datetime.fromtimestamp(int(released) / 1000, UTC), datetime.now(UTC))
                if isinstance(released, int | float)
                else datetime.now(UTC)
            )
            items.append(
                Item(
                    source=source.key,
                    external_id=code,
                    kind="listing",
                    title=title,
                    url=f"https://www.binance.com/en/support/announcement/detail/{code}",
                    published_at=published,
                    summary="Binance resmî duyurusu (yeni listeleme kategorisi).",
                    symbols=symbols_in(title),
                )
            )
    return items


def split_pair(symbol: str) -> tuple[str, str] | None:
    for quote in QUOTES:
        if symbol.endswith(quote) and len(symbol) > len(quote) + 1:
            return symbol[: -len(quote)], quote
    return None


def new_pairs(source: Source, payload: Any, known: set[str]) -> tuple[list[Item], set[str]]:
    """Bilinen çiftlerle karşılaştırır. İlk çalıştırmada (bilinen yok) yalnızca kaydeder."""
    current = {
        str(row.get("symbol"))
        for row in (payload if isinstance(payload, list) else [])
        if isinstance(row, dict) and re.fullmatch(r"[A-Z0-9]{3,20}", str(row.get("symbol", "")))
    }
    if not current:
        return [], known
    if not known:
        return [], current
    now = datetime.now(UTC)
    grouped: dict[str, list[str]] = {}
    for symbol in sorted(current - known):
        pair = split_pair(symbol)
        if pair is not None:
            grouped.setdefault(pair[0], []).append(pair[1])
    items = [
        Item(
            source=source.key,
            external_id=f"{base}:{'-'.join(quotes)}:{now:%Y%m%d}",
            kind="listing",
            title=f"Binance'te yeni işlem çifti: {', '.join(base + q for q in quotes)}",
            url=f"https://www.binance.com/en/trade/{base}_{quotes[0]}",
            published_at=now,
            summary=f"{base} Binance spot piyasasında {', '.join(quotes)} karşılığında "
            "işlem görmeye başladı (Binance açık piyasa verisi).",
            symbols=[base],
        )
        for base, quotes in grouped.items()
    ]
    return items, known | current


def parse_rss(source: Source, body: bytes) -> list[Item]:
    head = body[:4096].lower()
    # DTD ve varlık tanımı içeren belge reddedilir (XML varlık genişletme saldırıları).
    if b"<!doctype" in head or b"<!entity" in body.lower():
        raise ValueError("RSS belgesi DTD içeriyor")
    root = ET.fromstring(body)  # noqa: S314 - DTD yukarıda reddedildi; dış varlık çözülmez
    items: list[Item] = []
    for node in root.iter("item"):
        title = plain(node.findtext("title"), 300)
        link = (node.findtext("link") or "").strip()
        url = safe_url(link, source.hosts)
        if not title or url is None:
            continue
        summary = plain(node.findtext("description"), 300)
        guid = (node.findtext("guid") or link).strip()[:300]
        items.append(
            Item(
                source=source.key,
                external_id=guid or url,
                kind=classify(title, summary),
                title=title,
                url=url,
                published_at=parse_date(node.findtext("pubDate")),
                summary=summary,
                symbols=symbols_in(title, summary),
            )
        )
    return items[:60]


# --- Çekme ---------------------------------------------------------------------------------------

Fetcher = Callable[[str], Awaitable[bytes]]


def http_fetcher(client: httpx.AsyncClient) -> Fetcher:
    async def fetch(url: str) -> bytes:
        async with client.stream(
            "GET", url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
        ) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("Yanıt çok büyük")
                chunks.append(chunk)
            return b"".join(chunks)

    return fetch


async def _setting(conn: Any, key: str) -> Any:
    cur = await conn.execute("SELECT value FROM system_settings WHERE key = %s", (key,))
    row = await cur.fetchone()
    return row["value"] if row else None


async def _store(conn: Any, key: str, value: Any) -> None:
    await conn.execute(
        "INSERT INTO system_settings (key, value) VALUES (%s, %s) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
        (key, Jsonb(value)),
    )


async def enabled_sources(conn: Any) -> list[str]:
    value = await _setting(conn, "news_sources")
    if isinstance(value, dict) and isinstance(value.get("enabled"), list):
        return [k for k in value["enabled"] if k in SOURCES]
    return list(SOURCES)


async def claim(db: Database, interval_s: int) -> bool:
    """Bu tur çekimi bu süreç mi yapacak? (Birden çok API süreci aynı anda çekmesin.)"""
    async with db.connection() as conn:
        cur = await conn.execute(
            "INSERT INTO system_settings (key, value) VALUES ('news_claim', "
            "jsonb_build_object('at', now())) ON CONFLICT (key) DO UPDATE SET "
            "value = EXCLUDED.value, updated_at = now() "
            "WHERE (system_settings.value->>'at')::timestamptz < now() - make_interval(secs => %s) "
            "RETURNING key",
            (max(interval_s - 5, 1),),
        )
        return await cur.fetchone() is not None


_BINANCE_LIST = re.compile(r"^Binance Will List (.+?)(?:\s+with\b.*)?$", re.IGNORECASE)


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def draft_title(item: Item) -> str:
    """Taslak başlığı: Türkçe çeviri varsa o; yoksa Binance listeleme başlıkları kalıpla
    Türkçeleştirilir, diğerleri olduğu gibi."""
    match = _BINANCE_LIST.match(item.title)
    title = item.title_tr or (f"Binance {match.group(1)} listeliyor" if match else item.title)
    if item.symbols and not any(sym in title for sym in item.symbols):
        title = f"{item.symbols[0]}: {title}"
    title = _shorten(title, 120)
    return title if len(title) >= 5 else f"Yeni coin: {item.symbols[0] if item.symbols else title}"


def draft_body(item: Item, source_name: str) -> str:
    title = item.title_tr or item.title
    summary = item.summary_tr or item.summary
    parts = [f"Yeni coin haberi: “{title}”"]
    if summary and summary not in (item.title, title):
        parts.append(summary)
    if item.title_tr and item.title_tr != item.title:
        parts.append(f"Orijinal başlık: “{item.title}” (Türkçe çeviri otomatiktir)")
    parts.append(
        f"Kaynak: {source_name}. Ayrıntılar ve kesin tarihler için kaynak bağlantısına bakın."
    )
    parts.append(
        "Bu konu yeni coin haberinden otomatik hazırlanıp ekip onayıyla yayımlandı. "
        "Bilgilendirme amaçlıdır; yatırım tavsiyesi değildir."
    )
    return "\n\n".join(parts)[:5000]


async def auto_draft_enabled(conn: Any) -> bool:
    value = await _setting(conn, "news_auto_draft")
    return bool(value.get("enabled", True)) if isinstance(value, dict) else True


async def create_drafts(conn: Any, fresh: list[tuple[Any, Item]]) -> int:
    """Yeni coin haberlerinden onay bekleyen ekip konusu taslakları (bkz. modül açıklaması)."""
    drafted = 0
    cutoff = datetime.now(UTC) - AUTO_DRAFT_MAX_AGE
    seen: set[str] = set()
    for news_id, item in sorted(fresh, key=lambda pair: pair[1].published_at, reverse=True):
        if drafted >= AUTO_DRAFT_PER_RUN:
            break
        if item.kind != "listing" or not item.symbols or item.published_at < cutoff:
            continue
        symbol = item.symbols[0]
        if symbol in seen or not re.fullmatch(r"[A-Z0-9]{2,12}", symbol):
            continue
        seen.add(symbol)
        cur = await conn.execute(
            "SELECT 1 FROM forum_topics WHERE coin_symbol = %s "
            "AND status IN ('pending', 'approved') AND created_at > now() - interval '24 hours' "
            "LIMIT 1",
            (symbol,),
        )
        if await cur.fetchone() is not None:
            continue
        source = SOURCES.get(item.source)
        source_name = source.name if source else item.source
        cur = await conn.execute(
            "INSERT INTO forum_topics (author_kind, author_name, category, title, body, "
            "coin_symbol, source_name, source_url, status, flags) "
            "VALUES ('team', %s, 'yeni-coin', %s, %s, %s, %s, %s, 'pending', %s) RETURNING id",
            (
                TEAM_NAME,
                draft_title(item),
                draft_body(item, source_name),
                symbol,
                source_name[:60],
                item.url,
                [AUTO_FLAG],
            ),
        )
        topic = await cur.fetchone()
        if topic is None:
            continue
        await conn.execute(
            "UPDATE coin_news SET status = 'drafted', topic_id = %s WHERE id = %s",
            (topic["id"], news_id),
        )
        drafted += 1
    return drafted


TRANSLATE_PER_RUN = 40


async def translate_items(
    conn: Any, translator: Translator, pending: list[tuple[Any, Item]]
) -> tuple[int, str | None]:
    """Türkçe olmayan haberlerin başlık ve özetini çevirir ve kaydeder. Hata olursa durur
    (kota dolmuş olabilir); kalanlar sonraki turda ya da panelden çevrilir."""
    done = 0
    for news_id, item in pending[:TRANSLATE_PER_RUN]:
        if item.lang == "tr" or item.title_tr:
            continue
        texts = [item.title] + ([item.summary] if item.summary else [])
        try:
            out = await translator.translate(texts, item.lang)
        except Exception as exc:
            return done, describe_translation(exc)
        item.title_tr = out[0][:400] if out and out[0] else None
        item.summary_tr = out[1][:800] if len(out) > 1 and out[1] else None
        await conn.execute(
            "UPDATE coin_news SET title_tr = %s, summary_tr = %s WHERE id = %s",
            (item.title_tr, item.summary_tr, news_id),
        )
        done += 1
    return done, None


async def fetch_all(
    db: Database, fetch: Fetcher, translator: Translator | None = None
) -> dict[str, Any]:
    """Açık kaynakların hepsinden çeker, yenileri kaydeder; kaynak başına durum döner."""
    async with db.connection() as conn:
        keys = await enabled_sources(conn)
        known_value = await _setting(conn, "news_known_pairs")
    known = set(known_value) if isinstance(known_value, list) else set()
    status: dict[str, Any] = {}
    collected: list[Item] = []
    for key in keys:
        source = SOURCES[key]
        try:
            body = await fetch(source.url)
            if source.kind == "rss":
                items = parse_rss(source, body)
            elif source.kind == "binance_cms":
                items = parse_binance_cms(source, json.loads(body))
            else:
                items, updated = new_pairs(source, json.loads(body), known)
                if updated != known:
                    async with db.connection() as conn:
                        await _store(conn, "news_known_pairs", sorted(updated))
                    known = updated
            collected.extend(items)
            status[key] = {"ok": True, "count": len(items), "error": None}
        except Exception as exc:  # bir kaynağın hatası diğerlerini durdurmaz
            logger.info("Haber kaynağı okunamadı: %s (%s)", key, type(exc).__name__)
            status[key] = {"ok": False, "count": 0, "error": _describe(exc)}
    fresh: list[tuple[Any, Item]] = []
    async with db.connection() as conn:
        for item in collected:
            cur = await conn.execute(
                "INSERT INTO coin_news (source, external_id, kind, title, summary, url, symbols, "
                "published_at, lang) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (source, external_id) DO NOTHING RETURNING id",
                (
                    item.source,
                    item.external_id[:300],
                    item.kind,
                    item.title[:300],
                    item.summary[:600],
                    item.url,
                    item.symbols,
                    item.published_at,
                    item.lang,
                ),
            )
            row = await cur.fetchone()
            if row is not None:
                fresh.append((row["id"], item))
        translated, translation_error = 0, None
        if translator is not None:
            # Yeni coin haberleri önce çevrilir (taslak başlıkları Türkçe olsun).
            ordered = sorted(fresh, key=lambda pair: pair[1].kind != "listing")
            translated, translation_error = await translate_items(conn, translator, ordered)
        drafted = await create_drafts(conn, fresh) if await auto_draft_enabled(conn) else 0
        # Eski ve paylaşılmamış haberler temizlenir (tablo sınırlı kalır).
        await conn.execute(
            "DELETE FROM coin_news WHERE status NOT IN ('shared', 'drafted') AND id IN ("
            "SELECT id FROM coin_news WHERE status NOT IN ('shared', 'drafted') "
            "ORDER BY published_at DESC OFFSET %s)",
            (KEEP_ROWS,),
        )
        summary = {
            "at": datetime.now(UTC).isoformat(),
            "added": len(fresh),
            "drafted": drafted,
            "translated": translated,
            "translation_error": translation_error,
            "sources": status,
        }
        await _store(conn, "news_status", summary)
    return summary


def _describe(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 451 or code == 403:
            return f"Kaynak bu sunucunun bölgesinden erişime kapalı (HTTP {code})"
        return f"Kaynak hata döndü (HTTP {code})"
    if isinstance(exc, httpx.TimeoutException):
        return "Kaynak zamanında yanıt vermedi"
    if isinstance(exc, httpx.TransportError):
        return "Kaynağa bağlanılamadı"
    if isinstance(exc, ET.ParseError | ValueError):
        return "Kaynağın yanıtı okunamadı"
    return type(exc).__name__


async def run_loop(
    db: Database, interval_s: int, box: Callable[[], SecretBox | None] = lambda: None
) -> None:
    """API süreciyle birlikte çalışır: açılıştan kısa süre sonra ve sonra her ``interval_s``."""
    await asyncio.sleep(20)
    async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
        fetch = http_fetcher(client)
        while True:
            try:
                if await claim(db, interval_s):
                    async with db.connection() as conn:
                        settings = await load_translation(conn)
                    async with translator_from(settings, box()) as translator:
                        await fetch_all(db, fetch, translator)
            except Exception:  # veritabanı geçici olarak yoksa bir sonraki turda denenir
                logger.warning("Haber çekme turu başarısız", exc_info=True)
            await asyncio.sleep(interval_s)


# --- Yönetici API'si -----------------------------------------------------------------------------


class ShareNews(BaseModel):
    category: Literal["yeni-coin", "haber"]
    title: Title
    body: TopicBody
    coin_symbol: CoinSymbol = None
    pinned: bool = False


class NewsStatus(BaseModel):
    status: Literal["new", "dismissed"]


class AutoDraft(BaseModel):
    enabled: bool


class TranslationUpdate(BaseModel):
    enabled: bool
    provider: Literal["mymemory", "deepl"] = "mymemory"
    # MyMemory günlük kotası e-posta yazılınca artar (isteğe bağlı).
    email: str | None = Field(
        default=None, max_length=200, pattern=r"^$|^[^@\s]+@[^@\s]+\.[^@\s]+$"
    )
    # DeepL API anahtarı: boş bırakılırsa kayıtlı olan korunur; "sil" yazılırsa silinir.
    deepl_key: str | None = Field(default=None, max_length=200)


class SourcesUpdate(BaseModel):
    enabled: list[str] = Field(max_length=len(SOURCES))


FetcherFactory = Callable[[], contextlib.AbstractAsyncContextManager[Fetcher]]


def create_admin_news_router(ctx: AdminContext) -> APIRouter:
    router = APIRouter(prefix="/admin/v1/news")
    moderate = ctx.depends("forum.moderate")
    refresh_lock = asyncio.Lock()

    @contextlib.asynccontextmanager
    async def translator_for(request: Request) -> AsyncIterator[Translator | None]:
        # Testler sahte çevirmen verir (app.state.news_translator); üretimde ayarlardaki servis.
        override = getattr(request.app.state, "news_translator", None)
        if override is not None or ctx.settings.environment == "test":
            yield override  # test ortamında dış çeviri servisine bağlanılmaz
            return
        async with ctx.db.connection() as conn:
            settings = await load_translation(conn)
        async with translator_from(settings, ctx.box) as translator:
            yield translator

    @router.get("")
    async def list_news(
        admin: Admin = moderate,
        kind: Annotated[Literal["listing", "news"] | None, Query()] = None,
        status: Annotated[Literal["new", "drafted", "shared", "dismissed"] | None, Query()] = "new",
        q: Annotated[str | None, Query(max_length=80)] = None,
    ) -> dict[str, Any]:
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT n.id, n.source, n.kind, n.title, n.summary, n.title_tr, n.summary_tr, "
                "n.lang, n.url, n.symbols, n.published_at, n.fetched_at, n.status, "
                "t.number AS topic_number "
                "FROM coin_news n LEFT JOIN forum_topics t ON t.id = n.topic_id "
                "WHERE (%(kind)s::text IS NULL OR n.kind = %(kind)s) "
                "AND (%(status)s::text IS NULL OR n.status = %(status)s) "
                "AND (%(q)s::text IS NULL OR n.title ILIKE %(q)s OR n.title_tr ILIKE %(q)s "
                "OR %(sym)s = ANY(n.symbols)) "
                "ORDER BY n.published_at DESC LIMIT 150",
                {
                    "kind": kind,
                    "status": status,
                    "q": f"%{q.strip()}%" if q and q.strip() else None,
                    "sym": (q or "").strip().upper(),
                },
            )
            items = await cur.fetchall()
            cur = await conn.execute(
                "SELECT kind, count(*) AS n FROM coin_news WHERE status = 'new' GROUP BY kind"
            )
            fresh = {r["kind"]: r["n"] for r in await cur.fetchall()}
            cur = await conn.execute(
                "SELECT count(*) AS n FROM coin_news n JOIN forum_topics t ON t.id = n.topic_id "
                "WHERE n.status = 'drafted' AND t.status = 'pending'"
            )
            drafts = (await cur.fetchone() or {"n": 0})["n"]
            auto = await auto_draft_enabled(conn)
            translation = public_view(await load_translation(conn))
            last = await _setting(conn, "news_status")
            enabled = await enabled_sources(conn)
        for item in items:
            known_source = SOURCES.get(item["source"])
            item["source_name"] = known_source.name if known_source else item["source"]
        last_sources = (last or {}).get("sources", {}) if isinstance(last, dict) else {}
        return {
            "items": items,
            "new_counts": {"listing": fresh.get("listing", 0), "news": fresh.get("news", 0)},
            "pending_drafts": drafts,
            "auto_draft": auto,
            "translation": {
                **translation,
                "last_error": (last or {}).get("translation_error")
                if isinstance(last, dict)
                else None,
            },
            "last_run": (last or {}).get("at") if isinstance(last, dict) else None,
            "interval_s": ctx.settings.news_interval_s,
            "sources": [
                {
                    "key": s.key,
                    "name": s.name,
                    "enabled": s.key in enabled,
                    **last_sources.get(s.key, {"ok": None, "count": 0, "error": None}),
                }
                for s in SOURCES.values()
            ],
        }

    @router.post("/refresh")
    async def refresh(request: Request, admin: Admin = moderate) -> dict[str, Any]:
        if refresh_lock.locked():
            raise HTTPException(status_code=409, detail="Haberler şu anda çekiliyor")
        # Testler sahte kaynak verir (app.state.news_fetcher); üretimde gerçek HTTP istemcisi.
        factory: FetcherFactory = (
            getattr(request.app.state, "news_fetcher", None) or default_fetcher
        )
        async with refresh_lock, factory() as fetch, translator_for(request) as translator:
            summary = await fetch_all(ctx.db, fetch, translator)
        async with ctx.db.connection() as conn:
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.news_refreshed",
                details={"added": summary["added"]},
            )  # fmt: skip
        return summary

    @router.put("/sources")
    async def sources(body: SourcesUpdate, request: Request, admin: Admin = moderate) -> Any:
        unknown = [k for k in body.enabled if k not in SOURCES]
        if unknown:
            raise HTTPException(status_code=422, detail=f"Bilinmeyen kaynak: {', '.join(unknown)}")
        enabled = [k for k in SOURCES if k in body.enabled]
        async with ctx.db.connection() as conn:
            await _store(conn, "news_sources", {"enabled": enabled})
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.news_sources",
                details={"enabled": enabled},
            )  # fmt: skip
        return {"enabled": enabled}

    @router.put("/translation")
    async def translation(
        body: TranslationUpdate, request: Request, admin: Admin = moderate
    ) -> Any:
        async with ctx.db.connection() as conn:
            current = await load_translation(conn)
            deepl = current.get("deepl")
            key = (body.deepl_key or "").strip()
            if key.lower() == "sil":
                deepl = None
            elif key:
                box = ctx.secret_box()
                deepl = {
                    "enc": base64.b64encode(box.seal(key.encode(), SECRET_AAD)).decode(),
                    "hint": f"…{key[-4:]}",
                }
            if body.provider == "deepl" and not deepl:
                raise HTTPException(status_code=422, detail="DeepL için API anahtarı girin")
            value = {
                "enabled": body.enabled,
                "provider": body.provider,
                "email": (body.email or "").strip() or None,
                "deepl": deepl,
            }
            await _store(conn, TRANSLATION_KEY, value)
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.news_translation",
                details={"enabled": body.enabled, "provider": body.provider,
                         "deepl_key_changed": bool(key)},
            )  # fmt: skip
        return public_view({**value})

    @router.post("/{news_id}/translate")
    async def translate_one(news_id: str, request: Request, admin: Admin = moderate) -> Any:
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", news_id):
            raise HTTPException(status_code=404, detail="Haber bulunamadı")
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT source, external_id, kind, title, summary, url, published_at "
                "FROM coin_news WHERE id = %s",
                (news_id,),
            )
            row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Haber bulunamadı")
        item = Item(**row)
        if item.lang == "tr":
            return {"title_tr": None, "summary_tr": None, "message": "Haber zaten Türkçe"}
        async with translator_for(request) as translator, ctx.db.connection() as conn:
            if translator is None:
                raise HTTPException(status_code=409, detail="Çeviri kapalı (Çeviri ayarları)")
            done, error = await translate_items(conn, translator, [(news_id, item)])
        if error:
            raise HTTPException(status_code=502, detail=error)
        return {"title_tr": item.title_tr, "summary_tr": item.summary_tr, "translated": done}

    @router.put("/auto-draft")
    async def auto_draft(body: AutoDraft, request: Request, admin: Admin = moderate) -> Any:
        async with ctx.db.connection() as conn:
            await _store(conn, "news_auto_draft", {"enabled": body.enabled})
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.news_auto_draft",
                details={"enabled": body.enabled},
            )  # fmt: skip
        return {"enabled": body.enabled}

    @router.post("/{news_id}/share", status_code=201)
    async def share(
        news_id: str, body: ShareNews, request: Request, admin: Admin = moderate
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", news_id):
            raise HTTPException(status_code=404, detail="Haber bulunamadı")
        async with ctx.db.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "SELECT source, url, status FROM coin_news WHERE id = %s FOR UPDATE", (news_id,)
            )
            news = await cur.fetchone()
            if news is None:
                raise HTTPException(status_code=404, detail="Haber bulunamadı")
            if news["status"] == "shared":
                raise HTTPException(status_code=409, detail="Bu haber zaten paylaşıldı")
            if news["status"] == "drafted":
                raise HTTPException(
                    status_code=409,
                    detail="Bu haberin otomatik taslağı onay bekliyor (Forum onayları)",
                )
            source = SOURCES.get(news["source"])
            topic = await create_team_topic(
                conn,
                admin,
                TeamTopic(
                    category=body.category,
                    title=body.title,
                    body=body.body,
                    coin_symbol=body.coin_symbol,
                    pinned=body.pinned,
                ),
                source_name=source.name if source else news["source"],
                source_url=news["url"],
            )
            await conn.execute(
                "UPDATE coin_news SET status = 'shared', topic_id = %s WHERE id = %s",
                (topic["id"], news_id),
            )
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.news_shared",
                target_type="forum_topic", target_id=topic["id"],
                details={"news_id": news_id, "title": body.title},
            )  # fmt: skip
        return {"number": topic["number"], "id": topic["id"]}

    @router.post("/{news_id}/status")
    async def set_status(
        news_id: str, body: NewsStatus, request: Request, admin: Admin = moderate
    ) -> dict[str, str]:
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", news_id):
            raise HTTPException(status_code=404, detail="Haber bulunamadı")
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "UPDATE coin_news SET status = %s WHERE id = %s "
                "AND status NOT IN ('shared', 'drafted') RETURNING id",
                (body.status, news_id),
            )
            if await cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Haber bulunamadı ya da paylaşılmış")
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.news_status",
                target_type="coin_news", target_id=news_id, details={"status": body.status},
            )  # fmt: skip
        return {"id": news_id, "status": body.status}

    return router


@contextlib.asynccontextmanager
async def default_fetcher() -> AsyncIterator[Fetcher]:
    async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
        yield http_fetcher(client)
