"""İsteğe bağlı uygulama hata raporları.

Herkese açık uç nokta (çerez yok, köken gerekmez — masaüstü motoru gönderir):
    POST /v1/crash-reports        rapor (alan uzunlukları sınırlı; IP başına saatte 30)

Yönetici (``crash.manage``):
    GET   /admin/v1/crash-reports            son raporlar (durum süzgeci)
    PATCH /admin/v1/crash-reports/{fp}       durum: yeni / görüldü / düzeltildi / yok sayıldı

Gizlilik: IP adresi, cihaz ya da müşteri kimliği saklanmaz. Uygulama metni göndermeden önce
ayıklar; sunucu e-posta, IP, lisans anahtarı ve uzun gizli dizgileri bir kez daha ayıklar.
Aynı hata (parmak izi) tek satırda sayılır; tablo dolarsa (``MAX_ROWS``) yeni hatalar kabul edilmez
ama mevcutların sayacı artmaya devam eder.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ati_cloud.accounts import Database, SlidingWindowLimiter, client_ip
from ati_cloud.admin.context import Admin, AdminContext

MAX_ROWS = 5000

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_LICENSE = re.compile(r"\bATI-[0-9A-Z*]{4}(?:-[0-9A-Z*]{4}){3}\b")
_SECRETISH = re.compile(
    r"\b(?=[A-Za-z0-9+/=_-]*\d)(?=[A-Za-z0-9+/=_-]*[A-Za-z])[A-Za-z0-9+/=_-]{32,}"
)
_WIN_HOME = re.compile(
    r"(?i)([A-Z]:\\+(?:Users|Documents and Settings)\\+)(?!<kullanici>)[^\\/\"'\n]+"
)
_UNIX_HOME = re.compile(r"(/(?:home|Users)/)(?!<kullanici>)[^/\s\"']+")


def scrub(text: str) -> str:
    text = _WIN_HOME.sub(r"\1<kullanici>", text)
    text = _UNIX_HOME.sub(r"\1<kullanici>", text)
    text = _EMAIL.sub("<e-posta>", text)
    text = _LICENSE.sub("<lisans>", text)
    text = _IPV4.sub("<ip>", text)
    return _SECRETISH.sub("<gizli>", text)


Short = Annotated[str, Field(min_length=1, max_length=120)]


class CrashReport(BaseModel):
    app: Literal["engine", "desktop"]
    version: str = Field(pattern=r"^[0-9A-Za-z.+-]{1,40}$")
    os: str = Field(min_length=1, max_length=60)
    component: Short
    error_type: Short
    message: str = Field(max_length=500)
    stack: str = Field(max_length=8000)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{32}$")
    occurred_at: str | None = Field(default=None, max_length=40)


class StatusChange(BaseModel):
    status: Literal["new", "seen", "fixed", "ignored"]


def create_crash_router(db: Database) -> APIRouter:
    router = APIRouter(prefix="/v1")
    per_ip = SlidingWindowLimiter(30, 3600)

    @router.post("/crash-reports", status_code=202)
    async def receive(report: CrashReport, request: Request) -> dict[str, str]:
        if not per_ip.allow(client_ip(request)):
            raise HTTPException(status_code=429, detail="Çok fazla rapor")
        values = {
            "fingerprint": report.fingerprint,
            "app": report.app,
            "component": scrub(report.component)[:120],
            "error_type": scrub(report.error_type)[:120],
            "message": scrub(report.message)[:500],
            "stack": scrub(report.stack)[:8000],
            "version": report.version,
            "os": scrub(report.os)[:60],
        }
        async with db.connection() as conn:
            # Bilinen hata: sayaç, son sürüm ve zaman; "düzeltildi" işaretli hata yeni sürümde
            # tekrar görülürse yeniden açılır.
            cur = await conn.execute(
                "UPDATE crash_reports SET occurrences = occurrences + 1, last_seen = now(), "
                "last_version = %(version)s, "
                "status = CASE WHEN status = 'fixed' AND last_version <> %(version)s THEN 'new' "
                "ELSE status END WHERE fingerprint = %(fingerprint)s RETURNING fingerprint",
                values,
            )
            if await cur.fetchone() is not None:
                return {"status": "counted"}
            cur = await conn.execute("SELECT count(*) AS n FROM crash_reports")
            row = await cur.fetchone()
            if row is not None and row["n"] >= MAX_ROWS:
                return {"status": "full"}
            await conn.execute(
                "INSERT INTO crash_reports (fingerprint, app, component, error_type, message, "
                "stack, first_version, last_version, os) VALUES (%(fingerprint)s, %(app)s, "
                "%(component)s, %(error_type)s, %(message)s, %(stack)s, %(version)s, "
                "%(version)s, %(os)s) ON CONFLICT (fingerprint) DO UPDATE SET "
                "occurrences = crash_reports.occurrences + 1, last_seen = now()",
                values,
            )
        return {"status": "stored"}

    return router


def create_admin_crash_router(ctx: AdminContext) -> APIRouter:
    router = APIRouter(prefix="/admin/v1/crash-reports")
    manage = ctx.depends("crash.manage")

    @router.get("")
    async def list_reports(
        admin: Admin = manage,
        status: Annotated[Literal["new", "seen", "fixed", "ignored"] | None, Query()] = None,
    ) -> list[dict[str, Any]]:
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT fingerprint, app, component, error_type, message, stack, first_version, "
                "last_version, os, occurrences, status, first_seen, last_seen FROM crash_reports "
                "WHERE %(status)s::text IS NULL OR status = %(status)s "
                "ORDER BY (status = 'new') DESC, last_seen DESC LIMIT 200",
                {"status": status},
            )
            return await cur.fetchall()

    @router.patch("/{fingerprint}")
    async def change_status(
        fingerprint: str, body: StatusChange, request: Request, admin: Admin = manage
    ) -> dict[str, str]:
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "UPDATE crash_reports SET status = %s WHERE fingerprint = %s RETURNING status",
                (body.status, fingerprint),
            )
            if await cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Rapor bulunamadı")
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.crash_status",
                target_type="crash_report", target_id=fingerprint,
                details={"status": body.status},
            )  # fmt: skip
        return {"fingerprint": fingerprint, "status": body.status}

    return router
