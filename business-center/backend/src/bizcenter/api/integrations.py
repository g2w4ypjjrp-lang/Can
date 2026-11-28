"""Entegrasyon bağlantıları. Tokenlar şifreli saklanır, hiçbir yanıtta geri döndürülmez."""

from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from ..auth import CurrentUser, current_user
from ..db import Database
from ..deps import get_db
from ..integrations.crypto import TokenCipher
from ..integrations.printify import PrintifyClient, PrintifyError, simplify_variants

router = APIRouter(prefix="/api", tags=["integrations"])


def _cipher(request: Request) -> TokenCipher:
    try:
        return TokenCipher(request.app.state.settings.token_encryption_key)
    except ValueError as exc:
        raise HTTPException(503, "Sunucuda BC_TOKEN_ENCRYPTION_KEY tanımlı değil") from exc


def _transport(request: Request) -> httpx.AsyncBaseTransport | None:
    return getattr(request.app.state, "http_transport", None)  # testlerde sahte taşıyıcı


async def _admin(conn: Any, org: UUID) -> None:
    row = await (await conn.execute("select app.has_role(%s, array['owner','admin']) as ok", (org,))).fetchone()
    if not row or not row["ok"]:
        raise HTTPException(403, "Yönetici yetkisi gerekli")


@router.get("/organizations/{org_id}/integrations")
async def list_integrations(org_id: UUID, user: CurrentUser = Depends(current_user),
                            db: Database = Depends(get_db)) -> dict[str, Any]:
    async with db.user_tx(user) as conn:
        rows = {r["provider"]: r for r in await (await conn.execute(
            "select provider, status, external_account_id, display_name, last_error, last_synced_at"
            " from integrations where organization_id=%s", (org_id,))).fetchall()}
        n = await (await conn.execute("select count(*) as n from printify_products where organization_id=%s",
                                      (org_id,))).fetchone()
    out = {p: rows.get(p) or {"provider": p, "status": "disconnected"} for p in ("youtube", "etsy", "printify")}
    out["printify"]["product_count"] = n["n"] if n else 0
    return out


class PrintifyConnect(BaseModel):
    token: str = Field(min_length=20, max_length=4000)
    shop_id: int | None = None


@router.post("/organizations/{org_id}/integrations/printify")
async def connect_printify(org_id: UUID, body: PrintifyConnect, request: Request,
                           user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)) -> dict[str, Any]:
    cipher = _cipher(request)
    async with db.user_tx(user) as conn:
        await _admin(conn, org_id)
    async with PrintifyClient(body.token.strip(), _transport(request)) as pc:
        try:
            shops = await pc.shops()
        except PrintifyError as exc:
            raise HTTPException(400, str(exc)) from exc
    if not shops:
        raise HTTPException(400, "Bu Printify hesabında mağaza yok")
    if body.shop_id is None and len(shops) > 1:
        raise HTTPException(409, {"message": "Birden fazla mağaza var; birini seçin", "shops": shops})
    shop = next((s for s in shops if body.shop_id in (None, s["id"])), None)
    if shop is None:
        raise HTTPException(422, "Seçilen mağaza bu hesapta yok")

    async with db.user_tx(user) as conn:
        row = await (await conn.execute(
            """insert into integrations(organization_id, provider, status, external_account_id, display_name, scopes, last_error)
               values (%s,'printify','connected',%s,%s,'{}',null)
               on conflict (organization_id, provider) do update set status='connected',
                 external_account_id=excluded.external_account_id, display_name=excluded.display_name, last_error=null
               returning id""", (org_id, str(shop["id"]), shop["title"]))).fetchone()
        await conn.execute("select app.log_action(%s, 'integration.printify_connected', 'integration', %s, %s)",
                           (org_id, str(row["id"]) if row else None, Jsonb({"shop": shop["title"]})))
    # Token tablosu istemci rolüne kapalıdır; yalnızca servis bağlantısıyla yazılır.
    async with db.pool.connection() as conn:
        await conn.execute(
            """insert into oauth_tokens(integration_id, access_token_enc) values (%s,%s)
               on conflict (integration_id) do update set access_token_enc=excluded.access_token_enc, updated_at=now()""",
            (row["id"], cipher.encrypt(body.token.strip())))
        await conn.commit()
    return {"status": "connected", "shop": shop}


async def _printify_token(db: Database, request: Request, org_id: UUID) -> tuple[str, int, Any]:
    async with db.pool.connection() as conn:
        row = await (await conn.execute(
            """select i.id, i.external_account_id, t.access_token_enc from integrations i
               join oauth_tokens t on t.integration_id = i.id
               where i.organization_id=%s and i.provider='printify' and i.status='connected'""", (org_id,))).fetchone()
    if not row:
        raise HTTPException(409, "Printify bağlı değil")
    try:
        return _cipher(request).decrypt(row["access_token_enc"]), int(row["external_account_id"]), row["id"]
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/organizations/{org_id}/integrations/printify/sync")
async def sync_printify(org_id: UUID, request: Request, user: CurrentUser = Depends(current_user),
                        db: Database = Depends(get_db)) -> dict[str, Any]:
    async with db.user_tx(user) as conn:
        await _admin(conn, org_id)
    token, shop_id, integ_id = await _printify_token(db, request, org_id)
    async with PrintifyClient(token, _transport(request)) as pc:
        try:
            products = await pc.products(shop_id)
        except PrintifyError as exc:
            async with db.pool.connection() as conn:
                await conn.execute("update integrations set status='error', last_error=%s where id=%s", (str(exc), integ_id))
                await conn.commit()
            raise HTTPException(502, str(exc)) from exc
    async with db.user_tx(user) as conn:
        for p in products:
            await conn.execute(
                """insert into printify_products(organization_id, printify_shop_id, printify_product_id, blueprint_id,
                       print_provider_id, title, variants, synced_at)
                   values (%s,%s,%s,%s,%s,%s,%s,now())
                   on conflict (organization_id, printify_product_id) do update set title=excluded.title,
                     blueprint_id=excluded.blueprint_id, print_provider_id=excluded.print_provider_id,
                     variants=excluded.variants, synced_at=now()""",
                (org_id, shop_id, str(p["id"]), p.get("blueprint_id"), p.get("print_provider_id"),
                 str(p.get("title", ""))[:300], Jsonb(simplify_variants(p))))
        await conn.execute("update integrations set last_synced_at=now(), status='connected', last_error=null"
                           " where organization_id=%s and provider='printify'", (org_id,))
    return {"synced": len(products)}


@router.delete("/organizations/{org_id}/integrations/printify", status_code=204)
async def disconnect_printify(org_id: UUID, user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)) -> None:
    async with db.user_tx(user) as conn:
        await _admin(conn, org_id)
        row = await (await conn.execute(
            "update integrations set status='disconnected' where organization_id=%s and provider='printify' returning id",
            (org_id,))).fetchone()
        if row:
            await conn.execute("select app.log_action(%s, 'integration.printify_disconnected', 'integration', %s, '{}')",
                               (org_id, str(row["id"])))
    if row:
        async with db.pool.connection() as conn:
            await conn.execute("delete from oauth_tokens where integration_id=%s", (row["id"],))
            await conn.commit()


@router.get("/organizations/{org_id}/printify/products")
async def printify_products(org_id: UUID, user: CurrentUser = Depends(current_user),
                            db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    async with db.user_tx(user) as conn:
        return await (await conn.execute(
            "select printify_product_id, title, blueprint_id, print_provider_id, variants, synced_at"
            " from printify_products where organization_id=%s order by title limit 500", (org_id,))).fetchall()


# ---- Etsy (OAuth 2.0 + PKCE) ---------------------------------------------------------

import hashlib  # noqa: E402
import secrets  # noqa: E402
import time  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402

from ..integrations.etsy import EtsyClient, EtsyError, authorize_url, money, pkce_pair  # noqa: E402


def _etsy_settings(request: Request) -> Any:
    s = request.app.state.settings
    if not s.etsy_keystring or not s.etsy_redirect_uri:
        raise HTTPException(503, "Sunucuda BC_ETSY_KEYSTRING ve BC_ETSY_REDIRECT_URI tanımlı değil")
    return s


@router.post("/organizations/{org_id}/integrations/etsy/start")
async def etsy_start(org_id: UUID, request: Request, write: bool = False, user: CurrentUser = Depends(current_user),
                     db: Database = Depends(get_db)) -> dict[str, str]:
    s, cipher = _etsy_settings(request), _cipher(request)
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(32)
    async with db.user_tx(user) as conn:
        await _admin(conn, org_id)
        await conn.execute(
            "insert into system_settings(organization_id, key, value, updated_by) values (%s,'oauth_pending_etsy',%s,%s)"
            " on conflict (organization_id, key) do update set value=excluded.value, updated_by=excluded.updated_by,"
            " updated_at=now()",
            (org_id, Jsonb({"state_hash": hashlib.sha256(state.encode()).hexdigest(), "user": user.id,
                            "verifier": cipher.encrypt(verifier).decode(), "exp": int(time.time()) + 600,
                            "write": write}), user.id))
    return {"url": authorize_url(s.etsy_keystring, s.etsy_redirect_uri, state, challenge, write)}


class EtsyCallback(BaseModel):
    code: str = Field(min_length=1, max_length=2000)
    state: str = Field(min_length=10, max_length=200)


@router.post("/organizations/{org_id}/integrations/etsy/callback")
async def etsy_callback(org_id: UUID, body: EtsyCallback, request: Request, user: CurrentUser = Depends(current_user),
                        db: Database = Depends(get_db)) -> dict[str, Any]:
    s, cipher = _etsy_settings(request), _cipher(request)
    async with db.user_tx(user) as conn:
        await _admin(conn, org_id)
        row = await (await conn.execute(
            "delete from system_settings where organization_id=%s and key='oauth_pending_etsy' returning value",
            (org_id,))).fetchone()
    p = row["value"] if row else None
    if (not p or p.get("user") != user.id or p.get("exp", 0) < time.time()
            or not secrets.compare_digest(p.get("state_hash", ""), hashlib.sha256(body.state.encode()).hexdigest())):
        raise HTTPException(400, "Geçersiz veya süresi dolmuş Etsy bağlantı isteği; yeniden deneyin")
    verifier = cipher.decrypt(p["verifier"].encode())
    try:
        async with EtsyClient(s.etsy_api_key, transport=_transport(request)) as ec:
            tok = await ec.exchange(s.etsy_keystring, s.etsy_redirect_uri, body.code, verifier)
        async with EtsyClient(s.etsy_api_key, tok["access_token"], _transport(request)) as ec:
            me = await ec.me()
            if not me.get("shop_id"):
                raise HTTPException(400, "Bu Etsy hesabında mağaza yok")
            shop = await ec.shop(int(me["shop_id"]))
    except EtsyError as exc:
        raise HTTPException(400, str(exc)) from exc

    async with db.user_tx(user) as conn:
        integ = await (await conn.execute(
            """insert into integrations(organization_id, provider, status, external_account_id, display_name, scopes, last_error)
               values (%s,'etsy','connected',%s,%s,%s,null)
               on conflict (organization_id, provider) do update set status='connected',
                 external_account_id=excluded.external_account_id, display_name=excluded.display_name,
                 scopes=excluded.scopes, last_error=null returning id""",
            (org_id, str(me["shop_id"]), shop.get("shop_name", ""),
             ["shops_r", "listings_r", "transactions_r"] + (["listings_w"] if p.get("write") else [])))).fetchone()
        await conn.execute(
            """insert into etsy_shops(organization_id, integration_id, etsy_shop_id, name, currency) values (%s,%s,%s,%s,%s)
               on conflict (organization_id, etsy_shop_id) do update set name=excluded.name, currency=excluded.currency,
                 integration_id=excluded.integration_id""",
            (org_id, integ["id"], int(me["shop_id"]), shop.get("shop_name", ""), shop.get("currency_code")))
        await conn.execute("select app.log_action(%s, 'integration.etsy_connected', 'integration', %s, %s)",
                           (org_id, str(integ["id"]), Jsonb({"shop": shop.get("shop_name")})))
    await _store_tokens(db, cipher, integ["id"], tok)
    return {"status": "connected", "shop": {"id": me["shop_id"], "name": shop.get("shop_name")}}


async def _store_tokens(db: Database, cipher: TokenCipher, integ_id: Any, tok: dict[str, Any]) -> None:
    exp = datetime.now(UTC) + timedelta(seconds=int(tok.get("expires_in", 3600)) - 60)
    async with db.pool.connection() as conn:
        await conn.execute(
            """insert into oauth_tokens(integration_id, access_token_enc, refresh_token_enc, expires_at) values (%s,%s,%s,%s)
               on conflict (integration_id) do update set access_token_enc=excluded.access_token_enc,
                 refresh_token_enc=coalesce(excluded.refresh_token_enc, oauth_tokens.refresh_token_enc),
                 expires_at=excluded.expires_at, updated_at=now()""",
            (integ_id, cipher.encrypt(tok["access_token"]),
             cipher.encrypt(tok["refresh_token"]) if tok.get("refresh_token") else None, exp))
        await conn.commit()


async def _etsy_access(db: Database, request: Request, org_id: UUID) -> tuple[str, int, Any]:
    s, cipher = _etsy_settings(request), _cipher(request)
    async with db.pool.connection() as conn:
        row = await (await conn.execute(
            """select i.id, i.external_account_id, t.access_token_enc, t.refresh_token_enc, t.expires_at
               from integrations i join oauth_tokens t on t.integration_id=i.id
               where i.organization_id=%s and i.provider='etsy' and i.status in ('connected','error')""", (org_id,))).fetchone()
    if not row:
        raise HTTPException(409, "Etsy bağlı değil")
    token = cipher.decrypt(row["access_token_enc"])
    if row["expires_at"] and row["expires_at"] <= datetime.now(UTC):
        if not row["refresh_token_enc"]:
            raise HTTPException(409, "Etsy oturumu sona erdi; yeniden bağlanın")
        try:
            async with EtsyClient(s.etsy_api_key, transport=_transport(request)) as ec:
                tok = await ec.refresh(s.etsy_keystring, cipher.decrypt(row["refresh_token_enc"]))
        except EtsyError as exc:
            raise HTTPException(409, f"Etsy oturumu yenilenemedi: {exc}") from exc
        await _store_tokens(db, cipher, row["id"], tok)
        token = tok["access_token"]
    return token, int(row["external_account_id"]), row["id"]


@router.post("/organizations/{org_id}/integrations/etsy/sync")
async def etsy_sync(org_id: UUID, request: Request, user: CurrentUser = Depends(current_user),
                    db: Database = Depends(get_db)) -> dict[str, int]:
    async with db.user_tx(user) as conn:
        await _admin(conn, org_id)
    s = _etsy_settings(request)
    token, shop_id, integ_id = await _etsy_access(db, request, org_id)
    since = int(time.time()) - 90 * 86400
    try:
        async with EtsyClient(s.etsy_api_key, token, _transport(request)) as ec:
            listings = await ec.listings(shop_id)
            receipts = await ec.receipts(shop_id, since)
    except EtsyError as exc:
        async with db.pool.connection() as conn:
            await conn.execute("update integrations set status='error', last_error=%s where id=%s", (str(exc), integ_id))
            await conn.commit()
        raise HTTPException(502, str(exc)) from exc

    async with db.user_tx(user) as conn:
        shop = await (await conn.execute("select id from etsy_shops where organization_id=%s and etsy_shop_id=%s",
                                         (org_id, shop_id))).fetchone()
        for li in listings:
            price, cur = money(li.get("price"))
            await conn.execute(
                """insert into etsy_listings(organization_id, shop_id, etsy_listing_id, title, description, tags,
                       price_amount, currency, quantity, state, synced_at) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                   on conflict (shop_id, etsy_listing_id) do update set title=excluded.title, description=excluded.description,
                     tags=excluded.tags, price_amount=excluded.price_amount, currency=excluded.currency,
                     quantity=excluded.quantity, state=excluded.state, synced_at=now()""",
                (org_id, shop["id"], li["listing_id"], str(li.get("title", ""))[:140], str(li.get("description", ""))[:20000],
                 [str(t)[:20] for t in li.get("tags", [])][:13], price, cur, li.get("quantity"),
                 li.get("state") if li.get("state") in ("active", "inactive", "sold_out", "expired", "draft") else "active"))
        revenue = 0
        for r in receipts:
            total, cur = money(r.get("grandtotal"))
            created = datetime.fromtimestamp(int(r.get("created_timestamp") or r.get("create_timestamp")), UTC)
            status = str(r.get("status") or ("paid" if r.get("is_paid") else "open"))
            await conn.execute(
                """insert into etsy_orders(organization_id, shop_id, etsy_receipt_id, status, grandtotal_amount, currency,
                       ordered_at, shipped_at, synced_at) values (%s,%s,%s,%s,%s,%s,%s,%s,now())
                   on conflict (shop_id, etsy_receipt_id) do update set status=excluded.status,
                     grandtotal_amount=excluded.grandtotal_amount, shipped_at=excluded.shipped_at, synced_at=now()""",
                (org_id, shop["id"], r["receipt_id"], status, total, cur, created,
                 datetime.now(UTC) if r.get("is_shipped") else None))
            if r.get("is_paid") and total is not None and cur:
                await conn.execute(
                    """insert into revenue_records(organization_id, department, category, amount, currency, occurred_on,
                           source, source_ref) values (%s,'etsy','sales',%s,%s,%s,'etsy_api',%s)
                       on conflict (organization_id, source, source_ref) do update set amount=excluded.amount""",
                    (org_id, total, cur, created.date(), str(r["receipt_id"])))
                revenue += 1
        await conn.execute("update integrations set last_synced_at=now(), status='connected', last_error=null"
                           " where organization_id=%s and provider='etsy'", (org_id,))
    return {"listings": len(listings), "orders": len(receipts), "revenue_records": revenue}


@router.delete("/organizations/{org_id}/integrations/etsy", status_code=204)
async def etsy_disconnect(org_id: UUID, user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)) -> None:
    async with db.user_tx(user) as conn:
        await _admin(conn, org_id)
        row = await (await conn.execute(
            "update integrations set status='disconnected' where organization_id=%s and provider='etsy' returning id",
            (org_id,))).fetchone()
        if row:
            await conn.execute("select app.log_action(%s, 'integration.etsy_disconnected', 'integration', %s, '{}')",
                               (org_id, str(row["id"])))
    if row:
        async with db.pool.connection() as conn:
            await conn.execute("delete from oauth_tokens where integration_id=%s", (row["id"],))
            await conn.commit()


# ---- YouTube (Google OAuth 2.0 + PKCE) -----------------------------------------------

from ..integrations import youtube as yt  # noqa: E402


def _yt_settings(request: Request) -> Any:
    s = request.app.state.settings
    if not (s.google_client_id and s.google_client_secret and s.youtube_redirect_uri):
        raise HTTPException(503, "Sunucuda BC_GOOGLE_CLIENT_ID, BC_GOOGLE_CLIENT_SECRET ve BC_YOUTUBE_REDIRECT_URI tanımlı değil")
    return s


@router.post("/organizations/{org_id}/integrations/youtube/start")
async def youtube_start(org_id: UUID, request: Request, write: bool = False, user: CurrentUser = Depends(current_user),
                        db: Database = Depends(get_db)) -> dict[str, str]:
    s, cipher = _yt_settings(request), _cipher(request)
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(32)
    async with db.user_tx(user) as conn:
        await _admin(conn, org_id)
        await conn.execute(
            "insert into system_settings(organization_id, key, value, updated_by) values (%s,'oauth_pending_youtube',%s,%s)"
            " on conflict (organization_id, key) do update set value=excluded.value, updated_by=excluded.updated_by,"
            " updated_at=now()",
            (org_id, Jsonb({"state_hash": hashlib.sha256(state.encode()).hexdigest(), "user": user.id,
                            "verifier": cipher.encrypt(verifier).decode(), "exp": int(time.time()) + 600,
                            "write": write}), user.id))
    return {"url": yt.authorize_url(s.google_client_id, s.youtube_redirect_uri, state, challenge, write)}


@router.post("/organizations/{org_id}/integrations/youtube/callback")
async def youtube_callback(org_id: UUID, body: EtsyCallback, request: Request, user: CurrentUser = Depends(current_user),
                           db: Database = Depends(get_db)) -> dict[str, Any]:
    s, cipher = _yt_settings(request), _cipher(request)
    async with db.user_tx(user) as conn:
        await _admin(conn, org_id)
        row = await (await conn.execute(
            "delete from system_settings where organization_id=%s and key='oauth_pending_youtube' returning value",
            (org_id,))).fetchone()
    p = row["value"] if row else None
    if (not p or p.get("user") != user.id or p.get("exp", 0) < time.time()
            or not secrets.compare_digest(p.get("state_hash", ""), hashlib.sha256(body.state.encode()).hexdigest())):
        raise HTTPException(400, "Geçersiz veya süresi dolmuş YouTube bağlantı isteği; yeniden deneyin")
    try:
        async with yt.YouTubeClient(transport=_transport(request)) as c:
            tok = await c.exchange(s.google_client_id, s.google_client_secret, s.youtube_redirect_uri, body.code,
                                   cipher.decrypt(p["verifier"].encode()))
        async with yt.YouTubeClient(tok["access_token"], _transport(request)) as c:
            ch = await c.my_channel()
    except yt.YouTubeError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not ch:
        raise HTTPException(400, "Bu Google hesabında YouTube kanalı yok")
    granted = str(tok.get("scope", "")).split()
    async with db.user_tx(user) as conn:
        integ = await (await conn.execute(
            """insert into integrations(organization_id, provider, status, external_account_id, display_name, scopes, last_error)
               values (%s,'youtube','connected',%s,%s,%s,null)
               on conflict (organization_id, provider) do update set status='connected',
                 external_account_id=excluded.external_account_id, display_name=excluded.display_name,
                 scopes=excluded.scopes, last_error=null returning id""",
            (org_id, ch["id"], ch["snippet"]["title"], granted))).fetchone()
        await _upsert_channel(conn, org_id, integ["id"], ch)
        await conn.execute("select app.log_action(%s, 'integration.youtube_connected', 'integration', %s, %s)",
                           (org_id, str(integ["id"]), Jsonb({"channel": ch["snippet"]["title"]})))
    await _store_tokens(db, cipher, integ["id"], tok)
    return {"status": "connected", "channel": {"id": ch["id"], "title": ch["snippet"]["title"]}}


async def _upsert_channel(conn: Any, org_id: UUID, integ_id: Any, ch: dict[str, Any]) -> Any:
    st = ch.get("statistics", {})
    row = await (await conn.execute(
        """insert into youtube_channels(organization_id, integration_id, youtube_channel_id, title, subscriber_count,
               view_count, video_count, stats_fetched_at) values (%s,%s,%s,%s,%s,%s,%s,now())
           on conflict (organization_id, youtube_channel_id) do update set title=excluded.title,
             integration_id=excluded.integration_id,
             subscriber_count=excluded.subscriber_count, view_count=excluded.view_count, video_count=excluded.video_count,
             stats_fetched_at=now() returning id""",
        (org_id, integ_id, ch["id"], ch["snippet"]["title"],
         None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount", 0)),
         int(st.get("viewCount", 0)), int(st.get("videoCount", 0))))).fetchone()
    return row["id"]


async def _youtube_access(db: Database, request: Request, org_id: UUID) -> tuple[str, Any]:
    s, cipher = _yt_settings(request), _cipher(request)
    async with db.pool.connection() as conn:
        row = await (await conn.execute(
            """select i.id, t.access_token_enc, t.refresh_token_enc, t.expires_at from integrations i
               join oauth_tokens t on t.integration_id=i.id
               where i.organization_id=%s and i.provider='youtube' and i.status in ('connected','error')""",
            (org_id,))).fetchone()
    if not row:
        raise HTTPException(409, "YouTube bağlı değil")
    token = cipher.decrypt(row["access_token_enc"])
    if row["expires_at"] and row["expires_at"] <= datetime.now(UTC):
        if not row["refresh_token_enc"]:
            raise HTTPException(409, "YouTube oturumu sona erdi; yeniden bağlanın")
        try:
            async with yt.YouTubeClient(transport=_transport(request)) as c:
                tok = await c.refresh(s.google_client_id, s.google_client_secret, cipher.decrypt(row["refresh_token_enc"]))
        except yt.YouTubeError as exc:
            raise HTTPException(409, f"YouTube oturumu yenilenemedi: {exc}") from exc
        await _store_tokens(db, cipher, row["id"], tok)
        token = tok["access_token"]
    return token, row["id"]


@router.post("/organizations/{org_id}/integrations/youtube/sync")
async def youtube_sync(org_id: UUID, request: Request, user: CurrentUser = Depends(current_user),
                       db: Database = Depends(get_db)) -> dict[str, Any]:
    async with db.user_tx(user) as conn:
        await _admin(conn, org_id)
    token, integ_id = await _youtube_access(db, request, org_id)
    end = datetime.now(UTC).date() - timedelta(days=1)
    start = end - timedelta(days=89)
    revenue_note = None
    try:
        async with yt.YouTubeClient(token, _transport(request)) as c:
            ch = await c.my_channel()
            if not ch:
                raise HTTPException(409, "Kanal bulunamadı")
            videos = await c.recent_videos(ch["contentDetails"]["relatedPlaylists"]["uploads"])
            try:
                report = await c.daily_report(start.isoformat(), end.isoformat(), with_revenue=True)
            except yt.YouTubeError as exc:
                if exc.status != 403:
                    raise
                report = await c.daily_report(start.isoformat(), end.isoformat(), with_revenue=False)
                revenue_note = "Gelir verisi alınamadı (kanal para kazanmıyor veya gelir izni verilmedi)"
    except yt.YouTubeError as exc:
        async with db.pool.connection() as conn:
            await conn.execute("update integrations set status='error', last_error=%s where id=%s", (str(exc), integ_id))
            await conn.commit()
        raise HTTPException(502, str(exc)) from exc

    cols = [h["name"] for h in report.get("columnHeaders", [])]
    async with db.user_tx(user) as conn:
        channel_id = await _upsert_channel(conn, org_id, integ_id, ch)
        for v in videos:
            sn = v.get("snippet", {})
            await conn.execute(
                """insert into youtube_videos(organization_id, channel_id, youtube_video_id, title, description, tags,
                       privacy_status, lifecycle, published_at) values (%s,%s,%s,%s,%s,%s,%s,'published',%s)
                   on conflict (channel_id, youtube_video_id) do update set title=excluded.title,
                     description=excluded.description, tags=excluded.tags, privacy_status=excluded.privacy_status""",
                (org_id, channel_id, v["id"], str(sn.get("title", ""))[:300], str(sn.get("description", ""))[:5000],
                 sn.get("tags", [])[:50], v.get("status", {}).get("privacyStatus"), sn.get("publishedAt")))
        for r in report.get("rows", []):
            d = dict(zip(cols, r, strict=False))
            rev = d.get("estimatedRevenue")
            await conn.execute(
                """insert into youtube_analytics(organization_id, channel_id, day, views, watch_time_minutes,
                       subscribers_gained, subscribers_lost, estimated_revenue, currency)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   on conflict (channel_id, coalesce(video_id, '00000000-0000-0000-0000-000000000000'::uuid), day)
                   do update set views=excluded.views, watch_time_minutes=excluded.watch_time_minutes,
                     subscribers_gained=excluded.subscribers_gained, subscribers_lost=excluded.subscribers_lost,
                     estimated_revenue=excluded.estimated_revenue, currency=excluded.currency, fetched_at=now()""",
                (org_id, channel_id, d["day"], d.get("views"), d.get("estimatedMinutesWatched"), d.get("subscribersGained"),
                 d.get("subscribersLost"), rev, "USD" if rev is not None else None))
            if rev:
                await conn.execute(
                    """insert into revenue_records(organization_id, department, category, amount, currency, occurred_on,
                           source, source_ref) values (%s,'youtube','ad_revenue',%s,'USD',%s,'youtube_api',%s)
                       on conflict (organization_id, source, source_ref) do update set amount=excluded.amount""",
                    (org_id, rev, d["day"], f"{ch['id']}:{d['day']}"))
        await conn.execute("update integrations set last_synced_at=now(), status='connected', last_error=%s"
                           " where organization_id=%s and provider='youtube'", (revenue_note, org_id))
    return {"videos": len(videos), "days": len(report.get("rows", [])), "note": revenue_note}


@router.delete("/organizations/{org_id}/integrations/youtube", status_code=204)
async def youtube_disconnect(org_id: UUID, user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)) -> None:
    async with db.user_tx(user) as conn:
        await _admin(conn, org_id)
        row = await (await conn.execute(
            "update integrations set status='disconnected' where organization_id=%s and provider='youtube' returning id",
            (org_id,))).fetchone()
        if row:
            await conn.execute("select app.log_action(%s, 'integration.youtube_disconnected', 'integration', %s, '{}')",
                               (org_id, str(row["id"])))
    if row:
        async with db.pool.connection() as conn:
            await conn.execute("delete from oauth_tokens where integration_id=%s", (row["id"],))
            await conn.commit()
