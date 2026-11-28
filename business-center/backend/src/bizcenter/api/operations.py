"""Otomasyon kuralları, bildirimler ve finans uç noktaları."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from ..auth import CurrentUser, current_user
from ..db import Database
from ..deps import get_db
from ..errors import db_error
from ..finance import compute_pnl, load_period, missing_data
from ..scheduler import TEMPLATES, next_run, valid_cron

router = APIRouter(prefix="/api", tags=["operations"])
ADMIN = "app.has_role(%s, array['owner','admin'])"


async def _require_admin(conn: Any, org: UUID) -> None:
    row = await (await conn.execute(f"select {ADMIN} as ok", (org,))).fetchone()
    if not row or not row["ok"]:
        raise HTTPException(403, "Yönetici yetkisi gerekli")


# ---- otomasyon ----------------------------------------------------------------------

class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    schedule_cron: str = Field(max_length=100)
    timezone: str = "Europe/Istanbul"
    command: str = Field(min_length=3, max_length=4000)
    enabled: bool = False

    @field_validator("schedule_cron")
    @classmethod
    def _cron(cls, v: str) -> str:
        if not valid_cron(v.strip()):
            raise ValueError("Geçersiz cron ifadesi (5 alan bekleniyor)")
        return v.strip()

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        from zoneinfo import available_timezones
        if v not in available_timezones():
            raise ValueError("Geçersiz saat dilimi")
        return v


@router.get("/automation/templates")
async def templates() -> list[dict[str, str]]:
    return TEMPLATES


@router.get("/organizations/{org_id}/automation")
async def list_rules(org_id: UUID, user: CurrentUser = Depends(current_user),
                     db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    async with db.user_tx(user) as conn:
        cur = await conn.execute(
            "select id, name, schedule_cron, timezone, command, enabled, last_run_at, next_run_at"
            " from automation_rules where organization_id=%s order by created_at", (org_id,))
        return await cur.fetchall()


@router.post("/organizations/{org_id}/automation", status_code=201)
async def create_rule(org_id: UUID, body: RuleIn, user: CurrentUser = Depends(current_user),
                      db: Database = Depends(get_db)) -> dict[str, Any]:
    nxt = next_run(body.schedule_cron, body.timezone, datetime.now(UTC)) if body.enabled else None
    try:
        async with db.user_tx(user) as conn:
            await _require_admin(conn, org_id)
            cur = await conn.execute(
                "insert into automation_rules(organization_id, name, schedule_cron, timezone, command, enabled,"
                " next_run_at, created_by) values (%s,%s,%s,%s,%s,%s,%s,%s) returning id, next_run_at",
                (org_id, body.name, body.schedule_cron, body.timezone, body.command, body.enabled, nxt, user.id))
            return await cur.fetchone() or {}
    except HTTPException:
        raise
    except Exception as exc:
        raise db_error(exc) from exc


class RuleToggle(BaseModel):
    enabled: bool


@router.patch("/automation/{rule_id}")
async def toggle_rule(rule_id: UUID, body: RuleToggle, user: CurrentUser = Depends(current_user),
                      db: Database = Depends(get_db)) -> dict[str, Any]:
    async with db.user_tx(user) as conn:
        row = await (await conn.execute(
            "select schedule_cron, timezone from automation_rules where id=%s", (rule_id,))).fetchone()
        if row is None:
            raise HTTPException(404, "Kural bulunamadı")
        nxt = next_run(row["schedule_cron"], row["timezone"], datetime.now(UTC)) if body.enabled else None
        row = await (await conn.execute(
            "update automation_rules set enabled=%s, next_run_at=%s where id=%s returning id, enabled, next_run_at",
            (body.enabled, nxt, rule_id))).fetchone()
        if row is None:
            raise HTTPException(403, "Yönetici yetkisi gerekli")
        return row


@router.delete("/automation/{rule_id}", status_code=204)
async def delete_rule(rule_id: UUID, user: CurrentUser = Depends(current_user),
                      db: Database = Depends(get_db)) -> None:
    async with db.user_tx(user) as conn:
        cur = await conn.execute("delete from automation_rules where id=%s returning id", (rule_id,))
        if await cur.fetchone() is None:
            raise HTTPException(404, "Kural bulunamadı veya yetki yok")


# ---- bildirimler --------------------------------------------------------------------

@router.get("/organizations/{org_id}/notifications")
async def notifications(org_id: UUID, user: CurrentUser = Depends(current_user),
                        db: Database = Depends(get_db)) -> dict[str, Any]:
    async with db.user_tx(user) as conn:
        items = await (await conn.execute(
            "select id, kind, title, body, link, read_at, created_at from notifications"
            " where organization_id=%s order by created_at desc limit 100", (org_id,))).fetchall()
    return {"unread": sum(1 for n in items if n["read_at"] is None), "items": items}


@router.post("/organizations/{org_id}/notifications/read")
async def mark_read(org_id: UUID, user: CurrentUser = Depends(current_user),
                    db: Database = Depends(get_db)) -> dict[str, int]:
    async with db.user_tx(user) as conn:
        cur = await conn.execute(
            "update notifications set read_at=now() where organization_id=%s and user_id=%s and read_at is null"
            " returning id", (org_id, user.id))
        return {"marked": len(await cur.fetchall())}


# ---- finans -------------------------------------------------------------------------

class EntryIn(BaseModel):
    kind: Literal["revenue", "expense", "fee", "refund", "discount", "tax"]
    department: Literal["youtube", "etsy", "shared"]
    category: str = Field(min_length=1, max_length=60)
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    occurred_on: date
    note: str | None = Field(default=None, max_length=500)


@router.post("/organizations/{org_id}/finance/entries", status_code=201)
async def add_entry(org_id: UUID, body: EntryIn, user: CurrentUser = Depends(current_user),
                    db: Database = Depends(get_db)) -> dict[str, Any]:
    if body.kind == "revenue" and body.department == "shared":
        raise HTTPException(422, "Gelir bir departmana ait olmalı")
    try:
        async with db.user_tx(user) as conn:
            await _require_admin(conn, org_id)
            if body.kind == "revenue":
                sql = ("insert into revenue_records(organization_id, department, category, amount, currency,"
                       " occurred_on, source) values (%s,%s,%s,%s,%s,%s,'manual') returning id")
                args: tuple[Any, ...] = (org_id, body.department, body.category, body.amount, body.currency,
                                         body.occurred_on)
            elif body.kind == "expense":
                sql = ("insert into expenses(organization_id, department, category, amount, currency, occurred_on,"
                       " source, note) values (%s,%s,%s,%s,%s,%s,'manual',%s) returning id")
                args = (org_id, body.department, body.category, body.amount, body.currency, body.occurred_on,
                        body.note)
            else:
                sql = ("insert into financial_records(organization_id, kind, department, amount, currency,"
                       " occurred_on, source) values (%s,%s,%s,%s,%s,%s,'manual') returning id")
                args = (org_id, body.kind, body.department, body.amount, body.currency, body.occurred_on)
            row = await (await conn.execute(sql, args)).fetchone()
            await conn.execute("select app.log_action(%s, 'finance.manual_entry', %s, %s, %s)",
                               (org_id, body.kind, str(row["id"]) if row else None,
                                Jsonb({"amount": str(body.amount), "currency": body.currency})))
            return row or {}
    except HTTPException:
        raise
    except Exception as exc:
        raise db_error(exc) from exc


@router.get("/organizations/{org_id}/finance/summary")
async def summary(org_id: UUID, start: date, end: date, user: CurrentUser = Depends(current_user),
                  db: Database = Depends(get_db)) -> dict[str, Any]:
    if end < start or (end - start).days > 366:
        raise HTTPException(422, "Geçersiz tarih aralığı (en fazla 1 yıl)")
    async with db.user_tx(user) as conn:
        rev, rec, exp = await load_period(conn, org_id, start, end)
    return {"period": {"start": start, "end": end}, "scopes": {
        s: {"by_currency": compute_pnl(s, rev, rec, exp), "missing_data": missing_data(s, rev, rec, exp)}
        for s in ("youtube", "etsy", "combined")}}


@router.post("/organizations/{org_id}/finance/reports", status_code=201)
async def save_report(org_id: UUID, start: date, end: date, user: CurrentUser = Depends(current_user),
                      db: Database = Depends(get_db)) -> dict[str, Any]:
    """Hesaplanan raporu kaydeder. Eksik veri yoksa 'verified' olur (dashboard yalnızca bunları gösterir)."""
    if end < start:
        raise HTTPException(422, "Geçersiz tarih aralığı")
    saved = 0
    async with db.user_tx(user) as conn:
        await _require_admin(conn, org_id)
        rev, rec, exp = await load_period(conn, org_id, start, end)
        for scope in ("youtube", "etsy", "combined"):
            miss = missing_data(scope, rev, rec, exp)
            for cur, figures in compute_pnl(scope, rev, rec, exp).items():
                await conn.execute(
                    "insert into profit_reports(organization_id, scope, period_start, period_end, currency,"
                    " figures, missing_data, verified) values (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (org_id, scope, start, end, cur, Jsonb(figures), miss, not miss))
                saved += 1
    return {"saved": saved}


# ---- işletme profili ----------------------------------------------------------------

class BusinessProfile(BaseModel):
    brand_name: str = Field(default="", max_length=120)
    language: str = Field(default="Türkçe", max_length=60)
    youtube_channel_url: str = Field(default="", max_length=300)
    youtube_niche: str = Field(default="", max_length=500)
    youtube_audience: str = Field(default="", max_length=500)
    etsy_shop_name: str = Field(default="", max_length=120)
    etsy_shop_url: str = Field(default="", max_length=300)
    etsy_niche: str = Field(default="", max_length=500)
    etsy_products: str = Field(default="", max_length=500)
    price_range: str = Field(default="", max_length=120)
    currency: str = Field(default="USD", max_length=3)
    target_markets: str = Field(default="", max_length=300)
    goals: str = Field(default="", max_length=1000)
    tone: str = Field(default="", max_length=300)
    avoid: str = Field(default="", max_length=1000)

    @field_validator("youtube_channel_url", "etsy_shop_url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if v and not v.startswith("https://"):
            raise ValueError("Adres https:// ile başlamalı")
        return v


@router.get("/organizations/{org_id}/profile")
async def get_profile(org_id: UUID, user: CurrentUser = Depends(current_user),
                      db: Database = Depends(get_db)) -> dict[str, Any]:
    async with db.user_tx(user) as conn:
        row = await (await conn.execute(
            "select value, updated_at from system_settings where organization_id=%s and key='business_profile'",
            (org_id,))).fetchone()
    return {"profile": row["value"] if row else None, "updated_at": row["updated_at"] if row else None}


@router.put("/organizations/{org_id}/profile")
async def put_profile(org_id: UUID, body: BusinessProfile, user: CurrentUser = Depends(current_user),
                      db: Database = Depends(get_db)) -> dict[str, Any]:
    async with db.user_tx(user) as conn:
        await _require_admin(conn, org_id)
        await conn.execute(
            "insert into system_settings(organization_id, key, value, updated_by) values (%s,'business_profile',%s,%s)"
            " on conflict (organization_id, key) do update set value=excluded.value, updated_by=excluded.updated_by,"
            " updated_at=now()", (org_id, Jsonb(body.model_dump()), user.id))
        await conn.execute("select app.log_action(%s, 'settings.business_profile', 'system_settings', %s, '{}')",
                           (org_id, "business_profile"))
    return {"profile": body.model_dump()}


# ---- ilk görev paketi (ajanları teker teker çalıştırır) -------------------------------

class StarterIn(BaseModel):
    agent_codes: list[str] = Field(min_length=1, max_length=25)


@router.get("/agents/starter-tasks")
async def starter_tasks() -> dict[str, str]:
    from ..agents.registry import STARTER_TASKS
    return STARTER_TASKS


@router.post("/organizations/{org_id}/starter-tasks", status_code=201)
async def launch_starter(org_id: UUID, body: StarterIn, request: Request,
                         user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)) -> dict[str, Any]:
    """Seçilen ajanlara ilk görevlerini verir. Görevler 'ertelenmiş' sıraya girer; zamanlayıcı onları
    eşzamanlı görev sınırına uyarak teker teker başlatır."""
    from ..agents.registry import STARTER_TASKS
    settings = request.app.state.settings
    if not settings.anthropic_api_key:
        raise HTTPException(409, "Anthropic API anahtarı yapılandırılmadan görev paketi başlatılamaz")
    codes = list(dict.fromkeys(body.agent_codes))
    unknown = [c for c in codes if c not in STARTER_TASKS]
    if unknown:
        raise HTTPException(422, f"Bilinmeyen ajan: {', '.join(unknown)}")
    async with db.user_tx(user) as conn:
        await _require_admin(conn, org_id)
        prof = await (await conn.execute(
            "select value from system_settings where organization_id=%s and key='business_profile'", (org_id,))).fetchone()
        if not prof or not (prof["value"].get("youtube_niche") or prof["value"].get("etsy_niche")):
            raise HTTPException(409, "Önce Settings > İşletme Profili'nde en az YouTube veya Etsy nişini doldurun")
        agents = {r["code"]: r["id"] for r in await (await conn.execute(
            "select code, id from agents where organization_id=%s and enabled and code = any(%s)",
            (org_id, codes))).fetchall()}
        created = []
        for c in codes:
            if c not in agents:
                continue
            cmd = STARTER_TASKS[c]
            row = await (await conn.execute(
                "insert into tasks(organization_id, title, command, created_by, assigned_agent_id, result)"
                " values (%s,%s,%s,%s,%s,%s) returning id",
                (org_id, f"[İlk görev] {cmd}"[:120], cmd, user.id, agents[c],
                 Jsonb({"direct_agent": c, "deferred": True})))).fetchone()
            created.append(row["id"] if row else None)
        await conn.execute("select app.log_action(%s, 'tasks.starter_pack', 'organization', %s, %s)",
                           (org_id, str(org_id), Jsonb({"count": len(created)})))
    return {"queued": len(created), "max_cost_usd_per_task": settings.max_task_cost_usd,
            "max_parallel": settings.max_active_tasks_per_org}


@router.get("/system/status")
async def system_status(request: Request, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    """Arayüzün neyin hazır olduğunu dürüstçe göstermesi için (gizli bilgi döndürmez)."""
    s = request.app.state.settings
    return {"llm_configured": bool(s.anthropic_api_key), "model": s.llm_model,
            "max_task_cost_usd": s.max_task_cost_usd, "max_parallel_tasks": s.max_active_tasks_per_org}
