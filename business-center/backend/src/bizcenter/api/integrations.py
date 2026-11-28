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
