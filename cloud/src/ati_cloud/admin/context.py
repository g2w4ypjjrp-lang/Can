"""Yönetici API'sinin ortak parçaları: oturum çözümü, yetki denetimi, denetim kaydı.

Her yönetim uç noktası ``require("<yetki>")`` bağımlılığını kullanır. Bağımlılık nesnesi
``permission`` özniteliği taşır; testler tüm yönetici rotalarını tarayıp her birinin bir yetki
denetimi olduğunu ve her rol için doğru sonucu verdiğini doğrular (``tests/test_admin_rbac.py``).

Yetki **yalnızca sunucuda** denetlenir. Arayüz, menüleri yetkiye göre gizler ama bu bir güvenlik
önlemi değildir.
"""

from __future__ import annotations

import base64
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from fastapi import Depends, HTTPException, Request, Response
from psycopg.types.json import Jsonb

from ati_cloud.accounts import Database, SlidingWindowLimiter, client_ip
from ati_cloud.admin.security import SecretBox, token_digest, verify_totp
from ati_cloud.config import CloudSettings
from ati_cloud.licensing.service import Licensing

ADMIN_COOKIE = "ati_admin"
ADMIN_COOKIE_PATH = "/admin"
Conn = psycopg.AsyncConnection[dict[str, Any]]


@dataclass
class Admin:
    id: Any
    email: str
    full_name: str
    session_id: Any
    permissions: frozenset[str]
    roles: list[str]

    def has(self, permission: str) -> bool:
        return permission in self.permissions


@dataclass
class AdminContext:
    settings: CloudSettings
    db: Database
    licensing: Licensing | None
    box: SecretBox | None
    limiters: dict[str, SlidingWindowLimiter] = field(default_factory=dict)

    @classmethod
    def build(
        cls, settings: CloudSettings, db: Database, licensing: Licensing | None
    ) -> AdminContext:
        box = None
        if settings.admin_secret_kek is not None:
            box = SecretBox(base64.b64decode(settings.admin_secret_kek.get_secret_value()))
        return cls(
            settings=settings,
            db=db,
            licensing=licensing,
            box=box,
            limiters={
                "login_ip": SlidingWindowLimiter(10, 60),
                "login_email": SlidingWindowLimiter(10, 900),
                "verify_ip": SlidingWindowLimiter(20, 60),
                "invite_ip": SlidingWindowLimiter(20, 3600),
            },
        )

    def secret_box(self) -> SecretBox:
        if self.box is None:
            raise HTTPException(
                status_code=503,
                detail="Yönetici gizli anahtarı (ATI_ADMIN_SECRET_KEK) tanımlı değil",
            )
        return self.box

    def check_origin(self, request: Request) -> None:
        if request.headers.get("origin") not in self.settings.admin_origins:
            raise HTTPException(status_code=403, detail="İstek kaynağı doğrulanamadı")

    def limited(self, name: str, key: str) -> None:
        if not self.limiters[name].allow(key):
            raise HTTPException(
                status_code=429, detail="Çok fazla deneme. Biraz sonra tekrar deneyin."
            )

    # --- Oturum ----------------------------------------------------------------------------

    async def create_session(
        self, conn: Conn, admin_id: Any, request: Request, response: Response
    ) -> None:
        token = secrets.token_urlsafe(32)
        hours = self.settings.admin_session_hours
        await conn.execute(
            "INSERT INTO admin_sessions (admin_id, token_hash, mfa_verified_at, ip, user_agent, "
            "expires_at) VALUES (%s, %s, now(), %s, %s, now() + make_interval(hours => %s))",
            (admin_id, token_digest(token), client_ip(request), _ua(request), hours),
        )
        await conn.execute(
            "UPDATE admin_users SET last_login_at = now(), failed_login_count = 0, "
            "locked_until = NULL WHERE id = %s",
            (admin_id,),
        )
        response.set_cookie(
            ADMIN_COOKIE,
            token,
            max_age=hours * 3600,
            httponly=True,
            secure=self.settings.session_cookie_secure,
            samesite="strict",
            path=ADMIN_COOKIE_PATH,
        )

    async def current_admin(self, request: Request) -> Admin:
        token = request.cookies.get(ADMIN_COOKIE)
        if not token or len(token) > 200:
            raise HTTPException(status_code=401, detail="Yönetici girişi gerekli")
        async with self.db.connection() as conn:
            cur = await conn.execute(
                "SELECT a.id, a.email, a.full_name, s.id AS session_id FROM admin_sessions s "
                "JOIN admin_users a ON a.id = s.admin_id WHERE s.token_hash = %s "
                "AND s.revoked_at IS NULL AND s.expires_at > now() AND a.status = 'active'",
                (token_digest(token),),
            )
            row = await cur.fetchone()
            if row is None:
                raise HTTPException(status_code=401, detail="Oturum geçersiz veya süresi dolmuş")
            cur = await conn.execute(
                "SELECT permission_code FROM admin_effective_permissions WHERE admin_id = %s",
                (row["id"],),
            )
            permissions = frozenset(r["permission_code"] for r in await cur.fetchall())
            cur = await conn.execute(
                "SELECT role_code FROM admin_user_roles WHERE admin_id = %s ORDER BY role_code",
                (row["id"],),
            )
            roles = [r["role_code"] for r in await cur.fetchall()]
        return Admin(
            id=row["id"],
            email=row["email"],
            full_name=row["full_name"],
            session_id=row["session_id"],
            permissions=permissions,
            roles=roles,
        )

    def require(self, permission: str | None) -> Callable[..., Awaitable[Admin]]:
        """Oturum + (verilirse) yetki. Durum değiştiren isteklerde köken de denetlenir."""

        async def dependency(request: Request) -> Admin:
            admin = await self.current_admin(request)
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                self.check_origin(request)
            if permission is not None and not admin.has(permission):
                raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok")
            return admin

        dependency.permission = permission  # type: ignore[attr-defined]
        return dependency

    def depends(self, permission: str | None) -> Any:
        return Depends(self.require(permission))

    # --- Adım yükseltme (hassas işlemler) ---------------------------------------------------

    async def step_up(self, conn: Conn, admin: Admin, code: str | None) -> None:
        """Hassas işlemlerde güncel TOTP kodu istenir (oturum açık olsa bile)."""
        cur = await conn.execute(
            "SELECT totp_secret_enc, totp_last_counter FROM admin_users WHERE id = %s FOR UPDATE",
            (admin.id,),
        )
        row = await cur.fetchone()
        if row is None or row["totp_secret_enc"] is None or not code:
            raise HTTPException(status_code=400, detail="Doğrulama kodu gerekli")
        secret = self.secret_box().open(bytes(row["totp_secret_enc"]), f"admin-totp|{admin.id}")
        counter = verify_totp(secret, code, last_counter=row["totp_last_counter"])
        if counter is None:
            raise HTTPException(status_code=400, detail="Doğrulama kodu hatalı veya kullanılmış")
        await conn.execute(
            "UPDATE admin_users SET totp_last_counter = %s WHERE id = %s", (counter, admin.id)
        )

    # --- Denetim kaydı ---------------------------------------------------------------------

    @staticmethod
    async def act_as(conn: Conn, admin: Admin) -> None:
        """Tetikleyicilerin (lisans olayları) yöneticiyi aktör olarak kaydetmesi için."""
        await conn.execute("SELECT set_config('ati.actor_type', 'admin', true)")
        await conn.execute("SELECT set_config('ati.actor_id', %s, true)", (str(admin.id),))

    @staticmethod
    async def audit(
        conn: Conn,
        request: Request,
        *,
        actor_id: Any | None,
        action: str,
        target_type: str | None = None,
        target_id: Any | None = None,
        details: dict[str, Any] | None = None,
        actor_type: str = "admin",
    ) -> None:
        await conn.execute(
            "INSERT INTO audit_log (actor_type, actor_id, action, target_type, target_id, ip, "
            "user_agent, details) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                actor_type,
                None if actor_id is None else str(actor_id),
                action,
                target_type,
                None if target_id is None else str(target_id),
                client_ip(request),
                _ua(request),
                Jsonb(details or {}),
            ),
        )


def _ua(request: Request) -> str:
    return (request.headers.get("user-agent") or "")[:300]


def utcnow() -> datetime:
    return datetime.now(UTC)


INVITE_TTL = timedelta(hours=72)
CHALLENGE_TTL = timedelta(minutes=5)
MAX_CHALLENGE_ATTEMPTS = 5
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15
