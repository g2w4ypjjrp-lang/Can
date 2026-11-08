"""Müşteri hesapları (Aşama 14): kayıt, e-posta doğrulama, giriş/çıkış, parola sıfırlama, panel.

Güvenlik kuralları:

* Parolalar Argon2id ile özetlenir (veritabanı CHECK kısıtı da ``$argon2id$`` ister).
* Oturum: 256 bitlik rastgele belirteç ``HttpOnly; Secure; SameSite=Strict`` çerezde. Veritabanında
  yalnızca SHA-256 özeti tutulur; belirteç sızan bir yedekten geri üretilemez.
* E-posta doğrulama ve parola sıfırlama belirteçleri de yalnızca özetle saklanır. Tek
  kullanımlıktır ve süreleri sınırlıdır.
* Kayıt ve parola sıfırlama, e-postanın kayıtlı olup olmadığını **açığa vurmaz** (aynı yanıt).
  Giriş, var olmayan kullanıcıda da parola doğrulaması kadar sürer (zamanlama farkı yok).
* Çerezle kimlik doğrulanan ve durum değiştiren her istek ``Origin`` başlığıyla web sitesinin
  kökenine bağlanır (CSRF). Giriş ve kayıt uç noktalarında IP ve e-posta başına hız sınırı vardır.
* E-postalar ``email_outbox`` tablosuna yazılır; gönderim, e-posta sağlayıcısı (G5) ile.
* Her önemli olay hash zincirli ``audit_log`` tablosuna yazılır.
"""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, EmailStr, Field

from ati_cloud.config import CloudSettings

SESSION_COOKIE = "ati_session"
VERIFY_TTL = timedelta(hours=24)
RESET_TTL = timedelta(hours=1)
MIN_PASSWORD = 10
COMMON_PASSWORDS = {
    "1234567890", "12345678910", "password123", "parola1234", "qwertyuiop", "1q2w3e4r5t",
    "abcdefghij", "sifre12345", "0123456789", "trading123", "binance123", "password1!",
}  # fmt: skip

hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)
# Var olmayan kullanıcıda da aynı süre harcansın diye sabit bir özet.
_DUMMY_HASH = hasher.hash(secrets.token_urlsafe(16))


def token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def password_problem(password: str, email: str) -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"Parola en az {MIN_PASSWORD} karakter olmalı"
    if len(password) > 256:
        return "Parola çok uzun"
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS or len(set(password)) < 4:
        return "Bu parola çok kolay tahmin edilir"
    local = email.split("@", 1)[0].lower()
    if len(local) >= 4 and local in lowered:
        return "Parola e-posta adresinizi içermemeli"
    return None


# --- Veritabanı ------------------------------------------------------------------------------


class Database:
    """Bağlantı havuzu; ilk istekte açılır."""

    def __init__(self, dsn: str) -> None:
        self._pool = AsyncConnectionPool(dsn, min_size=1, max_size=10, open=False)
        self._opened = False

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[psycopg.AsyncConnection[dict[str, Any]]]:
        if not self._opened:
            await self._pool.open(wait=True, timeout=10)
            self._opened = True
        async with self._pool.connection() as conn:
            conn.row_factory = dict_row  # type: ignore[assignment]
            yield conn  # type: ignore[misc]

    async def close(self) -> None:
        if self._opened:
            await self._pool.close()


# --- Hız sınırı --------------------------------------------------------------------------------


class SlidingWindowLimiter:
    """Anahtar başına kayan pencere. Tek örnek bellekte; çok örnekte Redis (dağıtım, G5)."""

    def __init__(
        self, limit: int, window_s: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit = limit
        self.window_s = window_s
        self.clock = clock
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = self.clock()
        bucket = self.hits[key]
        while bucket and now - bucket[0] > self.window_s:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return False
        bucket.append(now)
        return True


# --- Şemalar ------------------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    full_name: str | None = Field(default=None, max_length=120)
    locale: str = Field(default="tr", pattern=r"^(tr|en)$")
    accept_terms: bool
    marketing_consent: bool = False


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class TokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class ResetRequest(BaseModel):
    email: EmailStr


class ResetConfirm(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=1, max_length=256)


class PlanInfo(BaseModel):
    code: str
    name: str
    duration_days: int | None
    device_limit: int
    companion_device_limit: int
    is_trial: bool
    price_minor: int
    currency: str
    features: dict[str, Any]


class LicenseInfo(BaseModel):
    id: str
    key_hint: str
    plan_code: str
    plan_name: str
    status: str
    device_limit: int
    sold_at: datetime | None
    activated_at: datetime | None
    expires_at: datetime | None
    active_devices: int


class MeResponse(BaseModel):
    id: str
    email: str
    email_verified: bool
    full_name: str | None
    locale: str
    created_at: datetime
    licenses: list[LicenseInfo]


GENERIC_REGISTER = {
    "status": "ok",
    "message": "Kayıt alındı. Hesabınızı etkinleştirmek için e-postanızdaki bağlantıyı açın.",
}
GENERIC_RESET = {
    "status": "ok",
    "message": "Bu adres kayıtlıysa parola sıfırlama bağlantısı gönderildi.",
}


# --- Yönlendirici ---------------------------------------------------------------------------------


def create_accounts_router(settings: CloudSettings, db: Database) -> APIRouter:
    router = APIRouter(prefix="/v1")
    login_ip = SlidingWindowLimiter(20, 60)
    login_email = SlidingWindowLimiter(5, 60)
    register_ip = SlidingWindowLimiter(5, 3600)
    reset_ip = SlidingWindowLimiter(5, 3600)

    def client_ip(request: Request) -> str:
        return request.client.host if request.client else "0.0.0.0"  # noqa: S104

    def require_origin(request: Request) -> None:
        origin = request.headers.get("origin")
        if origin not in settings.web_origins:
            raise HTTPException(status_code=403, detail="İstek kaynağı doğrulanamadı")

    def limited(limiter: SlidingWindowLimiter, key: str) -> None:
        if not limiter.allow(key):
            raise HTTPException(
                status_code=429, detail="Çok fazla deneme. Biraz bekleyip tekrar deneyin."
            )

    async def audit(
        conn: psycopg.AsyncConnection[Any],
        *,
        actor_type: str,
        actor_id: str | None,
        action: str,
        request: Request,
        details: dict[str, Any] | None = None,
    ) -> None:
        await conn.execute(
            "INSERT INTO audit_log (actor_type, actor_id, action, target_type, target_id, ip, "
            "user_agent, details) VALUES (%s, %s, %s, 'customer', %s, %s, %s, %s)",
            (
                actor_type,
                actor_id,
                action,
                actor_id,
                client_ip(request),
                (request.headers.get("user-agent") or "")[:300],
                Jsonb(details or {}),
            ),
        )

    async def enqueue_email(
        conn: psycopg.AsyncConnection[Any], to: str, template: str, link: str, locale: str
    ) -> None:
        await conn.execute(
            "INSERT INTO email_outbox (dedupe_key, to_email, template, payload) "
            "VALUES (%s, %s, %s, %s)",
            (f"{template}:{uuid.uuid4()}", to, template, Jsonb({"link": link, "locale": locale})),
        )

    async def new_token(
        conn: psycopg.AsyncConnection[Any], customer_id: Any, purpose: str, ttl: timedelta
    ) -> str:
        token = secrets.token_urlsafe(32)
        await conn.execute(
            "INSERT INTO customer_tokens (customer_id, purpose, token_hash, expires_at) "
            "VALUES (%s, %s, %s, now() + %s)",
            (customer_id, purpose, token_digest(token), ttl),
        )
        return token

    async def consume_token(
        conn: psycopg.AsyncConnection[Any], token: str, purpose: str
    ) -> Any | None:
        cur = await conn.execute(
            "UPDATE customer_tokens SET used_at = now() WHERE token_hash = %s AND purpose = %s "
            "AND used_at IS NULL AND expires_at > now() RETURNING customer_id",
            (token_digest(token), purpose),
        )
        row = await cur.fetchone()
        return row["customer_id"] if row else None

    async def current_customer(request: Request) -> dict[str, Any]:
        token = request.cookies.get(SESSION_COOKIE)
        if not token or len(token) > 200:
            raise HTTPException(status_code=401, detail="Oturum açmanız gerekiyor")
        async with db.connection() as conn:
            cur = await conn.execute(
                "UPDATE customer_sessions s SET last_used_at = now() FROM customers c "
                "WHERE s.refresh_token_hash = %s AND s.revoked_at IS NULL AND s.expires_at > now() "
                "AND c.id = s.customer_id AND c.status = 'active' "
                "RETURNING c.id, c.email, c.email_verified_at, c.full_name, c.locale, "
                "c.created_at, "
                "s.id AS session_id",
                (token_digest(token),),
            )
            row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=401, detail="Oturum geçersiz veya süresi dolmuş")
        return row

    # Not: "from __future__ import annotations" altında yerel bir Annotated takma adı FastAPI
    # tarafından çözülemez; bağımlılık bu yüzden varsayılan değer olarak verilir.
    customer_dep = Depends(current_customer)

    # --- Herkese açık -------------------------------------------------------------------------

    @router.get("/plans", response_model=list[PlanInfo])
    async def plans() -> list[PlanInfo]:
        """Satıştaki paketler. Fiyat girilmemiş paket satışa açılamaz (veritabanı kısıtı)."""
        async with db.connection() as conn:
            cur = await conn.execute(
                "SELECT code, name, duration_days, device_limit, companion_device_limit, is_trial, "
                "price_minor, currency, features FROM license_plans WHERE is_active "
                "ORDER BY sort_order, code"
            )
            rows = await cur.fetchall()
        return [PlanInfo.model_validate(r) for r in rows]

    # --- Kayıt ve doğrulama -------------------------------------------------------------------

    @router.post("/auth/register", status_code=202)
    async def register(body: RegisterRequest, request: Request) -> dict[str, str]:
        require_origin(request)
        limited(register_ip, client_ip(request))
        if not body.accept_terms:
            raise HTTPException(status_code=422, detail="Kullanım koşullarını kabul etmelisiniz")
        email = str(body.email).strip().lower()
        problem = password_problem(body.password, email)
        if problem:
            raise HTTPException(status_code=422, detail=problem)
        password_hash = hasher.hash(body.password)
        async with db.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "INSERT INTO customers "
                "(email, password_hash, full_name, locale, marketing_consent) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING id",
                (email, password_hash, body.full_name, body.locale, body.marketing_consent),
            )
            row = await cur.fetchone()
            if row is None:
                # Kayıtlı adres: aynı yanıt; sahibine "zaten hesabınız var" e-postası.
                await enqueue_email(
                    conn, email, "account_exists", f"{settings.public_web_url}/giris", body.locale
                )
                return GENERIC_REGISTER
            token = await new_token(conn, row["id"], "email_verification", VERIFY_TTL)
            await enqueue_email(
                conn,
                email,
                "verify_email",
                f"{settings.public_web_url}/eposta-dogrula?token={token}",
                body.locale,
            )
            await audit(
                conn,
                actor_type="customer",
                actor_id=str(row["id"]),
                action="customer.registered",
                request=request,
                details={"marketing_consent": body.marketing_consent},
            )
        return GENERIC_REGISTER

    @router.post("/auth/verify-email")
    async def verify_email(body: TokenRequest, request: Request) -> dict[str, str]:
        require_origin(request)
        async with db.connection() as conn, conn.transaction():
            customer_id = await consume_token(conn, body.token, "email_verification")
            if customer_id is None:
                raise HTTPException(status_code=400, detail="Bağlantı geçersiz veya süresi dolmuş")
            await conn.execute(
                "UPDATE customers SET email_verified_at = coalesce(email_verified_at, now()) "
                "WHERE id = %s",
                (customer_id,),
            )
            await audit(
                conn,
                actor_type="customer",
                actor_id=str(customer_id),
                action="customer.email_verified",
                request=request,
            )
        return {"status": "ok", "message": "E-posta adresiniz doğrulandı. Giriş yapabilirsiniz."}

    # --- Giriş / çıkış ------------------------------------------------------------------------

    @router.post("/auth/login")
    async def login(body: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
        require_origin(request)
        email = str(body.email).strip().lower()
        limited(login_ip, client_ip(request))
        limited(login_email, email)
        async with db.connection() as conn:
            cur = await conn.execute(
                "SELECT id, password_hash, status, email_verified_at FROM customers "
                "WHERE email = %s AND status <> 'deleted'",
                (email,),
            )
            row = await cur.fetchone()
            stored = row["password_hash"] if row else _DUMMY_HASH
            try:
                hasher.verify(stored, body.password)
                valid = row is not None
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                valid = False
            if not valid or row is None:
                await audit(
                    conn,
                    actor_type="system",
                    actor_id=None,
                    action="customer.login_failed",
                    request=request,
                    details={"email_hash": hashlib.sha256(email.encode()).hexdigest()[:16]},
                )
                # Hata ile çıkılan bağlantı geri alınır; denetim kaydı kalsın diye önce işlenir.
                await conn.commit()
                raise HTTPException(status_code=401, detail="E-posta veya parola hatalı")
            if row["status"] == "blocked":
                raise HTTPException(
                    status_code=403, detail="Hesabınız engellenmiş. Destek ile iletişime geçin."
                )
            if row["email_verified_at"] is None:
                raise HTTPException(
                    status_code=403,
                    detail="Önce e-posta adresinizi doğrulayın (e-postanızdaki bağlantı)",
                )
            if hasher.check_needs_rehash(stored):
                await conn.execute(
                    "UPDATE customers SET password_hash = %s WHERE id = %s",
                    (hasher.hash(body.password), row["id"]),
                )
            token = secrets.token_urlsafe(32)
            expires = datetime.now(UTC) + timedelta(days=settings.session_days)
            await conn.execute(
                "INSERT INTO customer_sessions (customer_id, refresh_token_hash, client_kind, ip, "
                "user_agent, expires_at) VALUES (%s, %s, 'web', %s, %s, %s)",
                (
                    row["id"],
                    token_digest(token),
                    client_ip(request),
                    (request.headers.get("user-agent") or "")[:300],
                    expires,
                ),
            )
            await conn.execute(
                "UPDATE customers SET last_login_at = now() WHERE id = %s", (row["id"],)
            )
            await audit(
                conn,
                actor_type="customer",
                actor_id=str(row["id"]),
                action="customer.login",
                request=request,
            )
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=settings.session_days * 86400,
            httponly=True,
            secure=settings.session_cookie_secure,
            samesite="strict",
            path="/",
        )
        return {"status": "ok"}

    @router.post("/auth/logout")
    async def logout(
        request: Request, response: Response, customer: dict[str, Any] = customer_dep
    ) -> dict[str, str]:
        require_origin(request)
        async with db.connection() as conn:
            await conn.execute(
                "UPDATE customer_sessions SET revoked_at = now() WHERE id = %s",
                (customer["session_id"],),
            )
            await audit(
                conn,
                actor_type="customer",
                actor_id=str(customer["id"]),
                action="customer.logout",
                request=request,
            )
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"status": "ok"}

    # --- Parola sıfırlama ---------------------------------------------------------------------

    @router.post("/auth/password-reset", status_code=202)
    async def password_reset(body: ResetRequest, request: Request) -> dict[str, str]:
        require_origin(request)
        limited(reset_ip, client_ip(request))
        email = str(body.email).strip().lower()
        async with db.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "SELECT id, locale FROM customers WHERE email = %s AND status = 'active'", (email,)
            )
            row = await cur.fetchone()
            if row is not None:
                token = await new_token(conn, row["id"], "password_reset", RESET_TTL)
                await enqueue_email(
                    conn,
                    email,
                    "password_reset",
                    f"{settings.public_web_url}/sifre-sifirla?token={token}",
                    row["locale"],
                )
        return GENERIC_RESET

    @router.post("/auth/password-reset/confirm")
    async def password_reset_confirm(body: ResetConfirm, request: Request) -> dict[str, str]:
        require_origin(request)
        async with db.connection() as conn, conn.transaction():
            customer_id = await consume_token(conn, body.token, "password_reset")
            if customer_id is None:
                raise HTTPException(status_code=400, detail="Bağlantı geçersiz veya süresi dolmuş")
            cur = await conn.execute("SELECT email FROM customers WHERE id = %s", (customer_id,))
            row = await cur.fetchone()
            problem = password_problem(body.password, row["email"] if row else "")
            if problem:
                raise HTTPException(status_code=422, detail=problem)
            await conn.execute(
                "UPDATE customers SET password_hash = %s, "
                "email_verified_at = coalesce(email_verified_at, now()) WHERE id = %s",
                (hasher.hash(body.password), customer_id),
            )
            # Parola değişince tüm oturumlar kapatılır.
            await conn.execute(
                "UPDATE customer_sessions SET revoked_at = now() "
                "WHERE customer_id = %s AND revoked_at IS NULL",
                (customer_id,),
            )
            await audit(
                conn,
                actor_type="customer",
                actor_id=str(customer_id),
                action="customer.password_reset",
                request=request,
            )
        return {"status": "ok", "message": "Parolanız değiştirildi. Yeni parolanızla giriş yapın."}

    # --- Müşteri paneli -----------------------------------------------------------------------

    @router.get("/me", response_model=MeResponse)
    async def me(customer: dict[str, Any] = customer_dep) -> MeResponse:
        async with db.connection() as conn:
            cur = await conn.execute(
                "SELECT l.id::text, l.key_hint, l.plan_code, p.name AS plan_name, l.status::text, "
                "l.device_limit, l.sold_at, l.activated_at, l.expires_at, "
                "(SELECT count(*) FROM license_activations a WHERE a.license_id = l.id "
                " AND a.deactivated_at IS NULL)::int AS active_devices "
                "FROM licenses l JOIN license_plans p ON p.code = l.plan_code "
                "WHERE l.customer_id = %s ORDER BY l.sold_at DESC NULLS LAST",
                (customer["id"],),
            )
            licenses = await cur.fetchall()
        return MeResponse(
            id=str(customer["id"]),
            email=customer["email"],
            email_verified=customer["email_verified_at"] is not None,
            full_name=customer["full_name"],
            locale=customer["locale"],
            created_at=customer["created_at"],
            licenses=[LicenseInfo.model_validate(r) for r in licenses],
        )

    return router
