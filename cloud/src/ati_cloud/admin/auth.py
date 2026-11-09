"""Yönetici girişi.

Akışlar:

* **Davet:** ``invite/start`` (davet belirteciyle TOTP sırrı üretilir, QR için ``otpauth://``) →
  ``invite/complete`` (parola + ilk TOTP kodu; hesap etkinleşir, 10 kurtarma kodu bir kez
  gösterilir, oturum açılır). Davet bağlantısı 72 saat geçerli ve tek kullanımlıktır.
* **Giriş:** ``login`` (e-posta + parola → 5 dakikalık doğrulama adımı belirteci) → ``verify``
  (TOTP veya kurtarma kodu → oturum). Parola veya kod 5 kez hatalı girilirse hesap 15 dakika
  kilitlenir.
  Aynı TOTP kodu ikinci kez kabul edilmez.

Yanıtlar hesabın varlığını açığa vurmaz (tek tip "Giriş başarısız").
"""

from __future__ import annotations

import base64
import secrets
from typing import Any

from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field

from ati_cloud.accounts import _DUMMY_HASH, client_ip, hasher, password_problem
from ati_cloud.admin.context import (
    ADMIN_COOKIE,
    ADMIN_COOKIE_PATH,
    CHALLENGE_TTL,
    INVITE_TTL,
    LOCK_MINUTES,
    MAX_CHALLENGE_ATTEMPTS,
    MAX_FAILED_LOGINS,
    Admin,
    AdminContext,
    Conn,
)
from ati_cloud.admin.security import (
    new_recovery_codes,
    new_totp_secret,
    otpauth_uri,
    recovery_digest,
    token_digest,
    verify_totp,
)

GENERIC_FAIL = "Giriş başarısız. Bilgileri kontrol edip tekrar deneyin."
MIN_ADMIN_PASSWORD = 12


class InviteToken(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class InviteComplete(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=6, max_length=10)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class VerifyRequest(BaseModel):
    challenge: str = Field(min_length=20, max_length=200)
    code: str | None = Field(default=None, max_length=10)
    recovery_code: str | None = Field(default=None, max_length=20)


class StepUp(BaseModel):
    code: str = Field(min_length=6, max_length=10)


async def issue_invite(conn: Conn, admin_id: Any) -> str:
    """Yeni davet belirteci (öncekiler geçersizleşir). Bağlantı: ``/yonetim/davet?token=``."""
    await conn.execute(
        "UPDATE admin_tokens SET used_at = now() WHERE admin_id = %s AND purpose = 'invite' "
        "AND used_at IS NULL",
        (admin_id,),
    )
    token = secrets.token_urlsafe(32)
    await conn.execute(
        "INSERT INTO admin_tokens (admin_id, purpose, token_hash, expires_at) "
        "VALUES (%s, 'invite', %s, now() + %s)",
        (admin_id, token_digest(token), INVITE_TTL),
    )
    return token


def invite_url(ctx: AdminContext, token: str) -> str:
    return f"{ctx.settings.admin_public_url}/yonetim/davet?token={token}"


async def store_recovery_codes(conn: Conn, admin_id: Any) -> list[str]:
    codes = new_recovery_codes()
    await conn.execute("DELETE FROM admin_recovery_codes WHERE admin_id = %s", (admin_id,))
    for code in codes:
        await conn.execute(
            "INSERT INTO admin_recovery_codes (admin_id, code_hash) VALUES (%s, %s)",
            (admin_id, recovery_digest(code)),
        )
    return codes


def create_admin_auth_router(ctx: AdminContext) -> APIRouter:
    router = APIRouter(prefix="/admin/v1/auth")

    async def invite_row(conn: Conn, token: str) -> dict[str, Any]:
        cur = await conn.execute(
            "SELECT t.id AS token_id, a.id, a.email, a.status FROM admin_tokens t "
            "JOIN admin_users a ON a.id = t.admin_id WHERE t.token_hash = %s "
            "AND t.purpose = 'invite' AND t.used_at IS NULL AND t.expires_at > now() "
            "FOR UPDATE OF t, a",
            (token_digest(token),),
        )
        row = await cur.fetchone()
        if row is None or row["status"] not in ("invited",):
            raise HTTPException(
                status_code=400, detail="Davet bağlantısı geçersiz veya süresi dolmuş"
            )
        return row

    # --- Davet -------------------------------------------------------------------------------

    @router.post("/invite/start")
    async def invite_start(body: InviteToken, request: Request) -> dict[str, str]:
        ctx.check_origin(request)
        ctx.limited("invite_ip", client_ip(request))
        box = ctx.secret_box()
        async with ctx.db.connection() as conn, conn.transaction():
            row = await invite_row(conn, body.token)
            secret = new_totp_secret()
            await conn.execute(
                "UPDATE admin_users SET totp_secret_enc = %s, totp_confirmed_at = NULL, "
                "totp_last_counter = NULL WHERE id = %s",
                (box.seal(secret, f"admin-totp|{row['id']}"), row["id"]),
            )
        return {
            "email": row["email"],
            "otpauth_uri": otpauth_uri(secret, row["email"]),
            "secret": base64.b32encode(secret).decode().rstrip("="),
        }

    @router.post("/invite/complete")
    async def invite_complete(
        body: InviteComplete, request: Request, response: Response
    ) -> dict[str, Any]:
        ctx.check_origin(request)
        ctx.limited("invite_ip", client_ip(request))
        box = ctx.secret_box()
        if len(body.password) < MIN_ADMIN_PASSWORD:
            raise HTTPException(
                status_code=422,
                detail=f"Yönetici parolası en az {MIN_ADMIN_PASSWORD} karakter olmalı",
            )
        async with ctx.db.connection() as conn, conn.transaction():
            row = await invite_row(conn, body.token)
            problem = password_problem(body.password, row["email"])
            if problem:
                raise HTTPException(status_code=422, detail=problem)
            cur = await conn.execute(
                "SELECT totp_secret_enc FROM admin_users WHERE id = %s", (row["id"],)
            )
            pending = await cur.fetchone()
            if pending is None or pending["totp_secret_enc"] is None:
                raise HTTPException(status_code=400, detail="Önce doğrulama uygulamasını kurun")
            secret = box.open(bytes(pending["totp_secret_enc"]), f"admin-totp|{row['id']}")
            counter = verify_totp(secret, body.code, last_counter=None)
            if counter is None:
                raise HTTPException(status_code=400, detail="Doğrulama kodu hatalı")
            await conn.execute(
                "UPDATE admin_users SET password_hash = %s, totp_confirmed_at = now(), "
                "totp_last_counter = %s, status = 'active' WHERE id = %s",
                (hasher.hash(body.password), counter, row["id"]),
            )
            await conn.execute(
                "UPDATE admin_tokens SET used_at = now() WHERE id = %s", (row["token_id"],)
            )
            codes = await store_recovery_codes(conn, row["id"])
            await ctx.create_session(conn, row["id"], request, response)
            await ctx.audit(
                conn, request, actor_id=row["id"], action="admin.activated",
                target_type="admin", target_id=row["id"],
            )  # fmt: skip
        return {"status": "ok", "recovery_codes": codes}

    # --- Giriş -------------------------------------------------------------------------------

    @router.post("/login")
    async def login(body: LoginRequest, request: Request) -> dict[str, str]:
        ctx.check_origin(request)
        email = str(body.email).strip().lower()
        ctx.limited("login_ip", client_ip(request))
        ctx.limited("login_email", email)
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT id, password_hash, status, locked_until > now() AS locked "
                "FROM admin_users WHERE email = %s",
                (email,),
            )
            row = await cur.fetchone()
            stored = row["password_hash"] if row else _DUMMY_HASH
            try:
                hasher.verify(stored, body.password)
                password_ok = row is not None
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                password_ok = False
            usable = row is not None and row["status"] == "active" and not row["locked"]
            if row is None or not (password_ok and usable):
                if row is not None and not password_ok:
                    await _register_failure(conn, row["id"])
                await ctx.audit(
                    conn, request, actor_id=None, action="admin.login_failed",
                    details={"email": email[:3] + "***"}, actor_type="system",
                )  # fmt: skip
                await conn.commit()
                raise HTTPException(status_code=401, detail=GENERIC_FAIL)
            challenge = secrets.token_urlsafe(32)
            await conn.execute(
                "INSERT INTO admin_tokens (admin_id, purpose, token_hash, expires_at) "
                "VALUES (%s, 'totp_challenge', %s, now() + %s)",
                (row["id"], token_digest(challenge), CHALLENGE_TTL),
            )
        return {"status": "totp_required", "challenge": challenge}

    async def _register_failure(conn: Conn, admin_id: Any) -> None:
        # UPDATE içindeki tüm ifadeler satırın eski değerlerini görür.
        await conn.execute(
            "UPDATE admin_users SET "
            "locked_until = CASE WHEN failed_login_count + 1 >= %s "
            "THEN now() + make_interval(mins => %s) ELSE locked_until END, "
            "failed_login_count = CASE WHEN failed_login_count + 1 >= %s THEN 0 "
            "ELSE failed_login_count + 1 END WHERE id = %s",
            (MAX_FAILED_LOGINS, LOCK_MINUTES, MAX_FAILED_LOGINS, admin_id),
        )

    @router.post("/verify")
    async def verify(body: VerifyRequest, request: Request, response: Response) -> dict[str, str]:
        ctx.check_origin(request)
        ctx.limited("verify_ip", client_ip(request))
        box = ctx.secret_box()
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT t.id AS token_id, t.attempts, a.id, a.totp_secret_enc, a.totp_last_counter "
                "FROM admin_tokens t JOIN admin_users a ON a.id = t.admin_id "
                "WHERE t.token_hash = %s AND t.purpose = 'totp_challenge' AND t.used_at IS NULL "
                "AND t.expires_at > now() AND a.status = 'active' "
                "AND (a.locked_until IS NULL OR a.locked_until <= now()) FOR UPDATE OF t, a",
                (token_digest(body.challenge),),
            )
            row = await cur.fetchone()
            if row is None or row["attempts"] >= MAX_CHALLENGE_ATTEMPTS:
                raise HTTPException(
                    status_code=401, detail="Doğrulama adımının süresi doldu; yeniden giriş yapın"
                )
            ok = False
            method = "totp"
            if body.recovery_code:
                method = "recovery"
                cur = await conn.execute(
                    "UPDATE admin_recovery_codes SET used_at = now() WHERE admin_id = %s "
                    "AND code_hash = %s AND used_at IS NULL RETURNING admin_id",
                    (row["id"], recovery_digest(body.recovery_code)),
                )
                ok = await cur.fetchone() is not None
            elif body.code and row["totp_secret_enc"] is not None:
                secret = box.open(bytes(row["totp_secret_enc"]), f"admin-totp|{row['id']}")
                counter = verify_totp(secret, body.code, last_counter=row["totp_last_counter"])
                if counter is not None:
                    ok = True
                    await conn.execute(
                        "UPDATE admin_users SET totp_last_counter = %s WHERE id = %s",
                        (counter, row["id"]),
                    )
            if not ok:
                await conn.execute(
                    "UPDATE admin_tokens SET attempts = attempts + 1 WHERE id = %s",
                    (row["token_id"],),
                )
                await _register_failure(conn, row["id"])
                await ctx.audit(
                    conn, request, actor_id=row["id"], action="admin.verify_failed",
                    target_type="admin", target_id=row["id"], details={"method": method},
                )  # fmt: skip
                await conn.commit()
                raise HTTPException(status_code=401, detail="Doğrulama kodu hatalı")
            await conn.execute(
                "UPDATE admin_tokens SET used_at = now() WHERE id = %s", (row["token_id"],)
            )
            await ctx.create_session(conn, row["id"], request, response)
            await ctx.audit(
                conn, request, actor_id=row["id"], action="admin.login",
                target_type="admin", target_id=row["id"], details={"method": method},
            )  # fmt: skip
        return {"status": "ok"}

    # --- Oturum ------------------------------------------------------------------------------

    session = ctx.depends(None)

    @router.get("/me")
    async def me(admin: Admin = session) -> dict[str, Any]:
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT count(*)::int AS n FROM admin_recovery_codes WHERE admin_id = %s "
                "AND used_at IS NULL",
                (admin.id,),
            )
            row = await cur.fetchone()
        return {
            "id": str(admin.id),
            "email": admin.email,
            "full_name": admin.full_name,
            "roles": admin.roles,
            "permissions": sorted(admin.permissions),
            "recovery_codes_left": row["n"] if row else 0,
        }

    @router.post("/logout")
    async def logout(
        request: Request, response: Response, admin: Admin = session
    ) -> dict[str, str]:
        async with ctx.db.connection() as conn:
            await conn.execute(
                "UPDATE admin_sessions SET revoked_at = now() WHERE id = %s", (admin.session_id,)
            )
            await ctx.audit(conn, request, actor_id=admin.id, action="admin.logout")
        response.delete_cookie(ADMIN_COOKIE, path=ADMIN_COOKIE_PATH)
        return {"status": "ok"}

    @router.post("/recovery-codes")
    async def regenerate_codes(
        body: StepUp, request: Request, admin: Admin = session
    ) -> dict[str, Any]:
        async with ctx.db.connection() as conn, conn.transaction():
            await ctx.step_up(conn, admin, body.code)
            codes = await store_recovery_codes(conn, admin.id)
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.recovery_codes_regenerated"
            )
        return {"recovery_codes": codes}

    return router
