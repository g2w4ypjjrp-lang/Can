"""Yönetici hesapları ve roller (``admin.manage``).

Kendini kilitleme önlemleri: yönetici kendi hesabını engelleyemez, kendi ``admin.manage``
yetkisini kaldıramaz; son etkin süper yönetici engellenemez veya rolü düşürülemez.
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from ati_cloud.accounts import hasher
from ati_cloud.admin.auth import invite_url, issue_invite
from ati_cloud.admin.context import Admin, AdminContext, Conn


class AdminCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    roles: list[str] = Field(min_length=1, max_length=5)


class RolesUpdate(BaseModel):
    roles: list[str] = Field(min_length=1, max_length=5)


async def _valid_roles(conn: Conn, roles: list[str]) -> list[str]:
    cur = await conn.execute("SELECT code FROM admin_roles WHERE code = ANY(%s)", (roles,))
    found = {r["code"] for r in await cur.fetchall()}
    unknown = sorted(set(roles) - found)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Bilinmeyen rol: {', '.join(unknown)}")
    return sorted(found)


async def _active_super_admins(conn: Conn) -> set[Any]:
    cur = await conn.execute(
        "SELECT ur.admin_id FROM admin_user_roles ur JOIN admin_users a ON a.id = ur.admin_id "
        "WHERE ur.role_code = 'super_admin' AND a.status = 'active'"
    )
    return {r["admin_id"] for r in await cur.fetchall()}


async def create_invited_admin(
    conn: Conn, *, email: str, full_name: str, roles: list[str], created_by: Any | None
) -> tuple[Any, str]:
    """Davetli yönetici oluşturur (parola ve 2FA davet bağlantısıyla belirlenir)."""
    roles = await _valid_roles(conn, roles)
    # Kullanılamaz rastgele parola özeti: hesap davet tamamlanana kadar giriş yapamaz.
    cur = await conn.execute(
        "INSERT INTO admin_users (email, full_name, password_hash, status, created_by) "
        "VALUES (%s, %s, %s, 'invited', %s) ON CONFLICT (email) DO NOTHING RETURNING id",
        (email.lower(), full_name, hasher.hash(secrets.token_urlsafe(32)), created_by),
    )
    row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=409, detail="Bu e-posta ile bir yönetici zaten var")
    for role in roles:
        await conn.execute(
            "INSERT INTO admin_user_roles (admin_id, role_code, granted_by) VALUES (%s, %s, %s)",
            (row["id"], role, created_by),
        )
    token = await issue_invite(conn, row["id"])
    return row["id"], token


def create_admin_users_router(ctx: AdminContext) -> APIRouter:
    router = APIRouter(prefix="/admin/v1")
    manage = ctx.depends("admin.manage")

    @router.get("/roles")
    async def roles(admin: Admin = manage) -> list[dict[str, Any]]:
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT r.code, r.name, r.description, coalesce(array_agg(rp.permission_code "
                "ORDER BY rp.permission_code) FILTER (WHERE rp.permission_code IS NOT NULL), '{}') "
                "AS permissions FROM admin_roles r LEFT JOIN admin_role_permissions rp "
                "ON rp.role_code = r.code GROUP BY r.code ORDER BY r.code"
            )
            return await cur.fetchall()

    @router.get("/admins")
    async def list_admins(admin: Admin = manage) -> list[dict[str, Any]]:
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT a.id::text, a.email, a.full_name, a.status::text, a.last_login_at, "
                "a.totp_confirmed_at IS NOT NULL AS two_factor, a.locked_until, "
                "coalesce(array_agg(ur.role_code ORDER BY ur.role_code) "
                "FILTER (WHERE ur.role_code IS NOT NULL), '{}') AS roles "
                "FROM admin_users a LEFT JOIN admin_user_roles ur ON ur.admin_id = a.id "
                "WHERE a.status <> 'deleted' GROUP BY a.id ORDER BY a.created_at"
            )
            return await cur.fetchall()

    @router.post("/admins")
    async def create_admin(
        body: AdminCreate, request: Request, admin: Admin = manage
    ) -> dict[str, str]:
        async with ctx.db.connection() as conn, conn.transaction():
            admin_id, token = await create_invited_admin(
                conn, email=str(body.email), full_name=body.full_name, roles=body.roles,
                created_by=admin.id,
            )  # fmt: skip
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.admin_invited",
                target_type="admin", target_id=admin_id, details={"roles": sorted(body.roles)},
            )  # fmt: skip
        # Bağlantı yalnızca bir kez gösterilir; güvenli bir kanalla iletilmelidir.
        return {"id": str(admin_id), "invite_url": invite_url(ctx, token)}

    @router.put("/admins/{admin_id}/roles")
    async def set_roles(
        admin_id: str, body: RolesUpdate, request: Request, admin: Admin = manage
    ) -> dict[str, Any]:
        async with ctx.db.connection() as conn, conn.transaction():
            roles = await _valid_roles(conn, body.roles)
            target = await _target(conn, admin_id)
            if target == admin.id:
                cur = await conn.execute(
                    "SELECT 1 FROM admin_role_permissions WHERE role_code = ANY(%s) "
                    "AND permission_code = 'admin.manage'",
                    (roles,),
                )
                if await cur.fetchone() is None:
                    raise HTTPException(
                        status_code=409, detail="Kendi yönetici yönetimi yetkinizi kaldıramazsınız"
                    )
            supers = await _active_super_admins(conn)
            if target in supers and "super_admin" not in roles and len(supers) <= 1:
                raise HTTPException(
                    status_code=409, detail="Son süper yöneticinin rolü değiştirilemez"
                )
            await conn.execute("DELETE FROM admin_user_roles WHERE admin_id = %s", (target,))
            for role in roles:
                await conn.execute(
                    "INSERT INTO admin_user_roles (admin_id, role_code, granted_by) VALUES (%s, "
                    "%s, %s)",
                    (target, role, admin.id),
                )
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.admin_roles_changed",
                target_type="admin", target_id=target, details={"roles": roles},
            )  # fmt: skip
        return {"id": str(target), "roles": roles}

    @router.post("/admins/{admin_id}/block")
    async def block(admin_id: str, request: Request, admin: Admin = manage) -> dict[str, str]:
        async with ctx.db.connection() as conn, conn.transaction():
            target = await _target(conn, admin_id)
            if target == admin.id:
                raise HTTPException(status_code=409, detail="Kendi hesabınızı engelleyemezsiniz")
            supers = await _active_super_admins(conn)
            if target in supers and len(supers) <= 1:
                raise HTTPException(status_code=409, detail="Son süper yönetici engellenemez")
            await conn.execute("UPDATE admin_users SET status = 'blocked' WHERE id = %s", (target,))
            await conn.execute(
                "UPDATE admin_sessions SET revoked_at = now() WHERE admin_id = %s AND revoked_at "
                "IS NULL",
                (target,),
            )
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.admin_blocked",
                target_type="admin", target_id=target,
            )  # fmt: skip
        return {"status": "blocked"}

    @router.post("/admins/{admin_id}/unblock")
    async def unblock(admin_id: str, request: Request, admin: Admin = manage) -> dict[str, str]:
        async with ctx.db.connection() as conn, conn.transaction():
            target = await _target(conn, admin_id)
            cur = await conn.execute(
                "UPDATE admin_users SET status = CASE WHEN totp_confirmed_at IS NULL "
                "THEN 'invited'::admin_status ELSE 'active'::admin_status END, failed_login_count "
                "= 0, "
                "locked_until = NULL WHERE id = %s AND status = 'blocked' RETURNING status::text",
                (target,),
            )
            row = await cur.fetchone()
            if row is None:
                raise HTTPException(status_code=409, detail="Yönetici engelli değil")
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.admin_unblocked",
                target_type="admin", target_id=target,
            )  # fmt: skip
        return {"status": row["status"]}

    @router.post("/admins/{admin_id}/reset-2fa")
    async def reset_two_factor(
        admin_id: str, request: Request, admin: Admin = manage
    ) -> dict[str, str]:
        """Telefonunu kaybeden yönetici için: 2FA ve kurtarma kodları silinir; yeni davet
        bağlantısı üretilir."""
        async with ctx.db.connection() as conn, conn.transaction():
            target = await _target(conn, admin_id)
            if target == admin.id:
                raise HTTPException(
                    status_code=409, detail="Kendi 2FA kaydınızı buradan sıfırlayamazsınız"
                )
            supers = await _active_super_admins(conn)
            if target in supers and len(supers) <= 1:
                raise HTTPException(
                    status_code=409, detail="Son süper yöneticinin 2FA kaydı sıfırlanamaz"
                )
            await conn.execute(
                "UPDATE admin_users SET status = 'invited', totp_secret_enc = NULL, "
                "totp_confirmed_at = NULL, totp_last_counter = NULL WHERE id = %s",
                (target,),
            )
            await conn.execute("DELETE FROM admin_recovery_codes WHERE admin_id = %s", (target,))
            await conn.execute(
                "UPDATE admin_sessions SET revoked_at = now() WHERE admin_id = %s AND revoked_at "
                "IS NULL",
                (target,),
            )
            token = await issue_invite(conn, target)
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.admin_two_factor_reset",
                target_type="admin", target_id=target,
            )  # fmt: skip
        return {"invite_url": invite_url(ctx, token)}

    return router


async def _target(conn: Conn, admin_id: str) -> Any:
    import uuid

    try:
        target = uuid.UUID(admin_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Yönetici bulunamadı") from exc
    cur = await conn.execute(
        "SELECT id FROM admin_users WHERE id = %s AND status <> 'deleted' FOR UPDATE", (target,)
    )
    row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Yönetici bulunamadı")
    return row["id"]
