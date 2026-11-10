"""İndirme: uygulama sürümleri.

* ``GET /v1/releases`` (herkese açık): her platformun yayındaki en son sürümü. Web sitesinin
  indirme sayfası ve müşteri paneli bunu gösterir.
* ``/admin/v1/releases`` (``release.manage``): taslak ekleme/düzenleme, yayınlama (güncel TOTP
  kodu ister) ve geri çekme. Her değişiklik denetim kaydına yazılır.

Güvenlik:

* Windows kurulum paketi yalnızca ``ATI_RELEASE_DOWNLOAD_HOSTS`` alan adlarından, iPhone
  uygulaması yalnızca App Store/TestFlight adreslerinden gösterilir. Yönetici oturumu ele
  geçirilse bile bağlantı başka bir siteye yönlendirilemez; yayınlamak ayrıca TOTP kodu ister.
* Yayınlanmış sürümün adresi, SHA-256 özeti ve boyutu değiştirilemez (veritabanı tetikleyicisi).
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from psycopg import errors as pg_errors
from pydantic import BaseModel, Field, field_validator

from ati_cloud.accounts import Database
from ati_cloud.admin.context import Admin, AdminContext, Conn

Platform = Literal["windows", "ios"]
PLATFORMS: tuple[Platform, ...] = ("windows", "ios")
IOS_HOSTS = frozenset({"apps.apple.com", "testflight.apple.com"})
VERSION = r"^\d{1,4}\.\d{1,4}\.\d{1,6}(-[0-9A-Za-z.]{1,20})?$"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PUBLIC_FIELDS = "version, download_url, sha256, size_bytes, min_os, notes, signed, published_at"
ADMIN_FIELDS = (
    "id, platform, version, download_url, sha256, size_bytes, min_os, notes, signed, status, "
    "published_at, withdrawn_at, created_at, updated_at"
)
# Sorgular sabit sütun listelerinden bir kez kurulur (kullanıcı girdisi içermez).
SQL_LATEST = (
    f"SELECT {PUBLIC_FIELDS} FROM app_releases WHERE platform = %s "  # noqa: S608
    "AND status = 'published' ORDER BY published_at DESC LIMIT 1"
)
SQL_LIST = f"SELECT {ADMIN_FIELDS} FROM app_releases ORDER BY created_at DESC LIMIT 200"  # noqa: S608
SQL_LOAD = f"SELECT {ADMIN_FIELDS} FROM app_releases WHERE id = %s FOR UPDATE"  # noqa: S608
SQL_INSERT = (
    "INSERT INTO app_releases (platform, version, download_url, sha256, size_bytes, min_os, "  # noqa: S608
    f"notes, signed, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
    f"RETURNING {ADMIN_FIELDS}"
)
SQL_PUBLISH = (
    "UPDATE app_releases SET status = 'published', published_at = now(), "  # noqa: S608
    f"withdrawn_at = NULL WHERE id = %s RETURNING {ADMIN_FIELDS}"
)
SQL_WITHDRAW = (
    "UPDATE app_releases SET status = 'withdrawn', withdrawn_at = now() "  # noqa: S608
    f"WHERE id = %s RETURNING {ADMIN_FIELDS}"
)


def _normalize_sha(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip().lower()
    if not SHA256.match(value):
        raise ValueError("SHA-256 özeti 64 onaltılık karakter olmalı")
    return value


class ReleaseFields(BaseModel):
    download_url: str = Field(min_length=12, max_length=500)
    sha256: str | None = Field(default=None, max_length=80)
    size_bytes: int | None = Field(default=None, ge=1, le=4 * 1024**3)
    min_os: str = Field(default="", max_length=80)
    notes: str = Field(default="", max_length=4000)
    signed: bool = False

    _sha = field_validator("sha256")(_normalize_sha)


class ReleaseCreate(ReleaseFields):
    platform: Platform
    version: str = Field(pattern=VERSION)


class ReleaseUpdate(BaseModel):
    download_url: str | None = Field(default=None, min_length=12, max_length=500)
    sha256: str | None = Field(default=None, max_length=80)
    size_bytes: int | None = Field(default=None, ge=1, le=4 * 1024**3)
    min_os: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=4000)
    signed: bool | None = None

    _sha = field_validator("sha256")(_normalize_sha)


class PublishRequest(BaseModel):
    code: str = Field(min_length=6, max_length=10)


class WithdrawRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


def check_download_url(platform: str, url: str, windows_hosts: list[str]) -> None:
    """İndirme adresi yalnızca izinli alan adlarında olabilir (açık yönlendirme / zararlı dosya
    bağlantısına karşı). Kullanıcı bilgisi, port ve parça (``#``) kabul edilmez."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password:
        raise HTTPException(status_code=422, detail="İndirme adresi https:// ile başlamalı")
    if parts.port is not None or parts.fragment or any(c.isspace() for c in url):
        raise HTTPException(status_code=422, detail="İndirme adresi geçersiz")
    if platform == "windows":
        allowed = {h.lower() for h in windows_hosts}
        if host not in allowed:
            raise HTTPException(
                status_code=422,
                detail="Windows kurulum paketi yalnızca şu alan adlarından sunulabilir: "
                + ", ".join(sorted(allowed)),
            )
        if not parts.path.lower().endswith(".exe"):
            raise HTTPException(status_code=422, detail="Windows kurulum paketi .exe olmalı")
    elif host not in IOS_HOSTS:
        raise HTTPException(
            status_code=422,
            detail="iPhone uygulaması yalnızca App Store veya TestFlight adresiyle eklenebilir",
        )


def _release_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Sürüm bulunamadı") from exc


def _conflict(exc: pg_errors.Error) -> HTTPException:
    if isinstance(exc, pg_errors.UniqueViolation):
        return HTTPException(status_code=409, detail="Bu platformda aynı sürüm numarası zaten var")
    constraint = getattr(exc.diag, "constraint_name", None) or ""
    if constraint == "app_releases_windows_has_digest":
        return HTTPException(
            status_code=422, detail="Windows kurulum paketi için SHA-256 özeti ve boyut zorunlu"
        )
    return HTTPException(status_code=409, detail=str(exc.diag.message_primary))


def create_releases_router(db: Database) -> APIRouter:
    router = APIRouter(prefix="/v1")

    @router.get("/releases")
    async def latest(response: Response) -> dict[str, Any]:
        """Her platformun yayındaki en son sürümü (yoksa ``null``)."""
        result: dict[str, Any] = {}
        async with db.connection() as conn:
            for platform in PLATFORMS:
                cur = await conn.execute(SQL_LATEST, (platform,))
                result[platform] = await cur.fetchone()
        response.headers["Cache-Control"] = "public, max-age=60"
        return result

    return router


def create_admin_releases_router(ctx: AdminContext) -> APIRouter:
    router = APIRouter(prefix="/admin/v1/releases")
    manage = ctx.depends("release.manage")
    hosts = ctx.settings.release_download_hosts

    async def load(conn: Conn, release: uuid.UUID) -> dict[str, Any]:
        cur = await conn.execute(SQL_LOAD, (release,))
        row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Sürüm bulunamadı")
        return row

    @router.get("")
    async def list_releases(admin: Admin = manage) -> list[dict[str, Any]]:
        async with ctx.db.connection() as conn:
            cur = await conn.execute(SQL_LIST)
            return await cur.fetchall()

    @router.post("", status_code=201)
    async def create(
        body: ReleaseCreate, request: Request, admin: Admin = manage
    ) -> dict[str, Any]:
        check_download_url(body.platform, body.download_url, hosts)
        async with ctx.db.connection() as conn, conn.transaction():
            try:
                cur = await conn.execute(
                    SQL_INSERT,
                    (
                        body.platform, body.version, body.download_url, body.sha256,
                        body.size_bytes, body.min_os, body.notes, body.signed, admin.id,
                    ),
                )  # fmt: skip
            except (pg_errors.UniqueViolation, pg_errors.CheckViolation) as exc:
                raise _conflict(exc) from exc
            row = await cur.fetchone()
            if row is None:  # pragma: no cover - INSERT ... RETURNING her zaman satır döner
                raise HTTPException(status_code=500, detail="Sürüm kaydedilemedi")
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.release_created",
                target_type="release", target_id=row["id"],
                details={
                    "platform": body.platform, "version": body.version,
                    "download_url": body.download_url, "sha256": body.sha256,
                },
            )  # fmt: skip
        return row

    @router.patch("/{release_id}")
    async def update(
        release_id: str, body: ReleaseUpdate, request: Request, admin: Admin = manage
    ) -> dict[str, Any]:
        changes = body.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(status_code=422, detail="Değişiklik yok")
        release = _release_id(release_id)
        async with ctx.db.connection() as conn, conn.transaction():
            before = await load(conn, release)
            file_fields = {"download_url", "sha256", "size_bytes", "signed"} & changes.keys()
            if file_fields and before["status"] != "draft":
                raise HTTPException(
                    status_code=409,
                    detail="Yayınlanmış sürümün dosya bilgileri değiştirilemez; "
                    "geri çekip yeni sürüm ekleyin",
                )
            if "download_url" in changes:
                check_download_url(before["platform"], changes["download_url"], hosts)
            assignments = ", ".join(f"{name} = %s" for name in changes)
            try:
                cur = await conn.execute(
                    f"UPDATE app_releases SET {assignments} WHERE id = %s "  # noqa: S608 - sütun adları modelden
                    f"RETURNING {ADMIN_FIELDS}",
                    (*changes.values(), release),
                )
            except pg_errors.CheckViolation as exc:
                raise _conflict(exc) from exc
            row = await cur.fetchone()
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.release_updated",
                target_type="release", target_id=release, details={"changes": changes},
            )  # fmt: skip
        return dict(row or {})

    @router.post("/{release_id}/publish")
    async def publish(
        release_id: str, body: PublishRequest, request: Request, admin: Admin = manage
    ) -> dict[str, Any]:
        release = _release_id(release_id)
        async with ctx.db.connection() as conn, conn.transaction():
            before = await load(conn, release)
            if before["status"] == "published":
                raise HTTPException(status_code=409, detail="Sürüm zaten yayında")
            # Adres, izinli alan adları sonradan değiştiyse yeniden denetlenir.
            check_download_url(before["platform"], before["download_url"], hosts)
            await ctx.step_up(conn, admin, body.code)
            cur = await conn.execute(SQL_PUBLISH, (release,))
            row = await cur.fetchone()
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.release_published",
                target_type="release", target_id=release,
                details={
                    "platform": before["platform"], "version": before["version"],
                    "download_url": before["download_url"], "sha256": before["sha256"],
                },
            )  # fmt: skip
        return dict(row or {})

    @router.post("/{release_id}/withdraw")
    async def withdraw(
        release_id: str, body: WithdrawRequest, request: Request, admin: Admin = manage
    ) -> dict[str, Any]:
        release = _release_id(release_id)
        async with ctx.db.connection() as conn, conn.transaction():
            before = await load(conn, release)
            if before["status"] == "withdrawn":
                raise HTTPException(status_code=409, detail="Sürüm zaten geri çekilmiş")
            cur = await conn.execute(SQL_WITHDRAW, (release,))
            row = await cur.fetchone()
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.release_withdrawn",
                target_type="release", target_id=release,
                details={
                    "platform": before["platform"], "version": before["version"],
                    "previous_status": before["status"], "reason": body.reason,
                },
            )  # fmt: skip
        return dict(row or {})

    return router
