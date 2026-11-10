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

import asyncio
import base64
import hashlib
import ipaddress
import secrets
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Awaitable, Callable
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

from ati_cloud.admin.security import (
    SecretBox,
    new_recovery_codes,
    new_totp_secret,
    otpauth_uri,
    recovery_digest,
    verify_totp,
)
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
    """Bağlantı havuzu; ilk istekte açılır.

    Açılış kilitlidir: yeniden başlatmadan hemen sonra aynı anda gelen ilk istekler havuzu birlikte
    açmaya çalışırsa psycopg_pool ``wait()`` içinde hata verir (yük testinde 500 olarak görüldü).
    """

    def __init__(self, dsn: str, max_size: int = 10) -> None:
        self._pool = AsyncConnectionPool(dsn, min_size=1, max_size=max_size, open=False)
        self._opened = False
        self._open_lock = asyncio.Lock()

    async def _ensure_open(self) -> None:
        if self._opened:
            return
        async with self._open_lock:
            if not self._opened:
                await self._pool.open(wait=True, timeout=10)
                self._opened = True

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[psycopg.AsyncConnection[dict[str, Any]]]:
        await self._ensure_open()
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


def client_ip(request: Request) -> str:
    """İstemci adresi (hız sınırı, denetim kaydı).

    * ``ATI_FORWARDED_HOPS`` = 0: güvenilen vekil arkasında uvicorn ``X-Forwarded-For``'u çözer
      (``ATI_TRUSTED_PROXIES``); başlık başka yerden gelirse yok sayılır.
    * ``ATI_FORWARDED_HOPS`` = n > 0 (iç adresleri bilinmeyen yük dengeleyici): başlığın sağdan
      n'inci değeri alınır. Vekiller kendi gördükleri adresi sona ekler; istemcinin gönderdiği
      sahte değerler solda kalır ve yok sayılır.
    """
    peer = request.client.host if request.client else "0.0.0.0"  # noqa: S104
    settings = getattr(request.app.state, "settings", None)
    hops = getattr(settings, "forwarded_hops", 0)
    if not hops:
        return peer
    chain = [
        part.strip()
        for header in request.headers.getlist("x-forwarded-for")
        for part in header.split(",")
        if part.strip()
    ]
    if len(chain) < hops:
        return peer
    try:
        return str(ipaddress.ip_address(chain[-hops]))
    except ValueError:
        return peer


def check_origin(settings: CloudSettings, request: Request) -> None:
    """Durum değiştiren istek yalnızca web sitesinin kökeninden gelebilir (CSRF)."""
    if request.headers.get("origin") not in settings.web_origins:
        raise HTTPException(status_code=403, detail="İstek kaynağı doğrulanamadı")


def limited(limiter: SlidingWindowLimiter, key: str) -> None:
    if not limiter.allow(key):
        raise HTTPException(
            status_code=429, detail="Çok fazla deneme. Biraz bekleyip tekrar deneyin."
        )


async def session_customer_id(db: Database, request: Request) -> Any | None:
    """Geçerli oturum çerezi varsa müşteri kimliği (isteğe bağlı kimlik doğrulama)."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token or len(token) > 200:
        return None
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT s.customer_id FROM customer_sessions s "
            "JOIN customers c ON c.id = s.customer_id "
            "WHERE s.refresh_token_hash = %s AND s.revoked_at IS NULL AND s.expires_at > now() "
            "AND c.status = 'active'",
            (token_digest(token),),
        )
        row = await cur.fetchone()
    return row["customer_id"] if row else None


def customer_dependency(db: Database) -> Callable[[Request], Awaitable[dict[str, Any]]]:
    """Oturum çerezinden müşteriyi çözen FastAPI bağımlılığı (diğer yönlendiriciler de kullanır)."""

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
                "c.created_at, c.password_hash, "
                "s.id AS session_id",
                (token_digest(token),),
            )
            row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=401, detail="Oturum geçersiz veya süresi dolmuş")
        return row

    return current_customer


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


class MfaLoginRequest(BaseModel):
    challenge: str = Field(min_length=20, max_length=100)
    code: str = Field(min_length=6, max_length=20)


class PasswordConfirm(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class MfaCode(BaseModel):
    code: str = Field(min_length=6, max_length=20)


class MfaDisable(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=6, max_length=20)


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


class DeviceInfo(BaseModel):
    id: str
    name: str
    platform: str
    activated_at: datetime
    last_seen_at: datetime


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
    devices: list[DeviceInfo] = []
    device_resets_left: int = 0


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
GENERIC_RESEND = {
    "status": "ok",
    "message": "Bu adres kayıtlı ve doğrulanmamışsa yeni bir doğrulama bağlantısı gönderildi.",
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
    resend_ip = SlidingWindowLimiter(5, 3600)
    resend_email = SlidingWindowLimiter(3, 3600)

    def require_origin(request: Request) -> None:
        check_origin(settings, request)

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

    async def open_session(
        conn: psycopg.AsyncConnection[Any], customer_id: Any, request: Request, response: Response
    ) -> None:
        token = secrets.token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(days=settings.session_days)
        await conn.execute(
            "INSERT INTO customer_sessions (customer_id, refresh_token_hash, client_kind, ip, "
            "user_agent, expires_at) VALUES (%s, %s, 'web', %s, %s, %s)",
            (
                customer_id,
                token_digest(token),
                client_ip(request),
                (request.headers.get("user-agent") or "")[:300],
                expires,
            ),
        )
        await conn.execute(
            "UPDATE customers SET last_login_at = now() WHERE id = %s", (customer_id,)
        )
        await audit(
            conn,
            actor_type="customer",
            actor_id=str(customer_id),
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

    current_customer = customer_dependency(db)

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

    @router.post("/auth/resend-verification", status_code=202)
    async def resend_verification(body: ResetRequest, request: Request) -> dict[str, str]:
        """Doğrulama bağlantısını yeniden gönderir. Yanıt, adresin durumunu açığa vurmaz."""
        require_origin(request)
        email = str(body.email).strip().lower()
        limited(resend_ip, client_ip(request))
        if not resend_email.allow(email):
            return GENERIC_RESEND  # sınır dolunca da aynı yanıt; e-posta gönderilmez
        async with db.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "SELECT id, locale FROM customers WHERE email = %s AND status = 'active' "
                "AND email_verified_at IS NULL",
                (email,),
            )
            row = await cur.fetchone()
            if row is not None:
                # Önceki bağlantılar geçersiz olur; yalnızca en yenisi çalışır.
                await conn.execute(
                    "UPDATE customer_tokens SET used_at = now() WHERE customer_id = %s "
                    "AND purpose = 'email_verification' AND used_at IS NULL",
                    (row["id"],),
                )
                token = await new_token(conn, row["id"], "email_verification", VERIFY_TTL)
                await enqueue_email(
                    conn,
                    email,
                    "verify_email",
                    f"{settings.public_web_url}/eposta-dogrula?token={token}",
                    row["locale"],
                )
        return GENERIC_RESEND

    # --- Giriş / çıkış ------------------------------------------------------------------------

    @router.post("/auth/login")
    async def login(body: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
        require_origin(request)
        email = str(body.email).strip().lower()
        limited(login_ip, client_ip(request))
        limited(login_email, email)
        async with db.connection() as conn:
            cur = await conn.execute(
                "SELECT id, password_hash, status, email_verified_at, mfa_enabled_at "
                "FROM customers WHERE email = %s AND status <> 'deleted'",
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
            if row["mfa_enabled_at"] is not None:
                # Parola doğru ama oturum henüz açılmaz: doğrulama kodu adımı (5 dk, 5 deneme).
                challenge = secrets.token_urlsafe(32)
                await conn.execute(
                    "DELETE FROM customer_login_challenges WHERE customer_id = %s "
                    "OR expires_at < now()",
                    (row["id"],),
                )
                await conn.execute(
                    "INSERT INTO customer_login_challenges (token_hash, customer_id, expires_at) "
                    "VALUES (%s, %s, now() + interval '5 minutes')",
                    (token_digest(challenge), row["id"]),
                )
                return {"status": "mfa_required", "challenge": challenge}
            await open_session(conn, row["id"], request, response)
        return {"status": "ok"}

    # --- İki adımlı doğrulama (2FA) -------------------------------------------------------------

    mfa_box = (
        SecretBox(base64.b64decode(settings.admin_secret_kek.get_secret_value()))
        if settings.admin_secret_kek
        else None
    )
    mfa_ip = SlidingWindowLimiter(20, 300)

    def box() -> SecretBox:
        if mfa_box is None:
            raise HTTPException(
                status_code=503, detail="İki adımlı doğrulama bu sunucuda yapılandırılmadı"
            )
        return mfa_box

    def check_password(stored: str | None, password: str) -> None:
        try:
            hasher.verify(stored or _DUMMY_HASH, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            raise HTTPException(status_code=401, detail="Parola hatalı") from None

    async def verify_second_factor(
        conn: psycopg.AsyncConnection[Any], customer_id: Any, code: str
    ) -> str | None:
        """Kod doğruysa "totp" ya da "recovery" döner (kurtarma kodu harcanır); değilse None."""
        cur = await conn.execute(
            "SELECT mfa_totp_secret_enc, mfa_last_counter, mfa_recovery_hashes FROM customers "
            "WHERE id = %s AND mfa_enabled_at IS NOT NULL FOR UPDATE",
            (customer_id,),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        secret = box().open(bytes(row["mfa_totp_secret_enc"]), f"customer-totp|{customer_id}")
        counter = verify_totp(secret, code, last_counter=row["mfa_last_counter"])
        if counter is not None:
            await conn.execute(
                "UPDATE customers SET mfa_last_counter = %s WHERE id = %s", (counter, customer_id)
            )
            return "totp"
        digest = recovery_digest(code)
        remaining = [bytes(h) for h in row["mfa_recovery_hashes"]]
        if digest in remaining:
            remaining.remove(digest)
            await conn.execute(
                "UPDATE customers SET mfa_recovery_hashes = %s WHERE id = %s",
                (remaining, customer_id),
            )
            return "recovery"
        return None

    @router.post("/auth/login/2fa")
    async def login_second_factor(
        body: MfaLoginRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        require_origin(request)
        limited(mfa_ip, client_ip(request))
        async with db.connection() as conn:
            cur = await conn.execute(
                "SELECT customer_id, attempts FROM customer_login_challenges "
                "WHERE token_hash = %s AND expires_at > now() FOR UPDATE",
                (token_digest(body.challenge),),
            )
            challenge = await cur.fetchone()
            if challenge is None:
                raise HTTPException(
                    status_code=401, detail="Doğrulama süresi doldu; yeniden giriş yapın"
                )
            customer_id = challenge["customer_id"]
            used = await verify_second_factor(conn, customer_id, body.code)
            if used is None:
                if challenge["attempts"] + 1 >= 5:
                    await conn.execute(
                        "DELETE FROM customer_login_challenges WHERE token_hash = %s",
                        (token_digest(body.challenge),),
                    )
                else:
                    await conn.execute(
                        "UPDATE customer_login_challenges SET attempts = attempts + 1 "
                        "WHERE token_hash = %s",
                        (token_digest(body.challenge),),
                    )
                await audit(
                    conn, actor_type="customer", actor_id=str(customer_id),
                    action="customer.login_mfa_failed", request=request,
                )  # fmt: skip
                await conn.commit()
                raise HTTPException(status_code=401, detail="Doğrulama kodu hatalı")
            await conn.execute(
                "DELETE FROM customer_login_challenges WHERE customer_id = %s", (customer_id,)
            )
            if used == "recovery":
                await audit(
                    conn, actor_type="customer", actor_id=str(customer_id),
                    action="customer.recovery_code_used", request=request,
                )  # fmt: skip
            await open_session(conn, customer_id, request, response)
        return {"status": "ok"}

    @router.get("/me/2fa")
    async def mfa_status(customer: dict[str, Any] = customer_dep) -> dict[str, Any]:
        async with db.connection() as conn:
            cur = await conn.execute(
                "SELECT mfa_enabled_at, cardinality(mfa_recovery_hashes) AS recovery_left "
                "FROM customers WHERE id = %s",
                (customer["id"],),
            )
            row = await cur.fetchone()
        assert row is not None  # noqa: S101 - oturumdaki müşteri vardır
        return {
            "enabled": row["mfa_enabled_at"] is not None,
            "enabled_at": row["mfa_enabled_at"],
            "recovery_left": row["recovery_left"] if row["mfa_enabled_at"] else 0,
            "available": mfa_box is not None,
        }

    @router.post("/me/2fa/setup")
    async def mfa_setup(
        body: PasswordConfirm, request: Request, customer: dict[str, Any] = customer_dep
    ) -> dict[str, str]:
        require_origin(request)
        sealer = box()
        check_password(customer["password_hash"], body.password)
        secret = new_totp_secret()
        async with db.connection() as conn:
            cur = await conn.execute(
                "UPDATE customers SET mfa_pending_enc = %s WHERE id = %s "
                "AND mfa_enabled_at IS NULL RETURNING id",
                (sealer.seal(secret, f"customer-totp|{customer['id']}"), customer["id"]),
            )
            if await cur.fetchone() is None:
                raise HTTPException(status_code=409, detail="İki adımlı doğrulama zaten açık")
        return {
            "secret": base64.b32encode(secret).decode().rstrip("="),
            "otpauth_uri": otpauth_uri(secret, str(customer["email"])),
        }

    @router.post("/me/2fa/enable")
    async def mfa_enable(
        body: MfaCode, request: Request, customer: dict[str, Any] = customer_dep
    ) -> dict[str, Any]:
        require_origin(request)
        sealer = box()
        async with db.connection() as conn:
            cur = await conn.execute(
                "SELECT mfa_pending_enc FROM customers WHERE id = %s AND mfa_enabled_at IS NULL "
                "FOR UPDATE",
                (customer["id"],),
            )
            row = await cur.fetchone()
            if row is None or row["mfa_pending_enc"] is None:
                raise HTTPException(status_code=409, detail="Önce kurulumu başlatın")
            pending = bytes(row["mfa_pending_enc"])
            secret = sealer.open(pending, f"customer-totp|{customer['id']}")
            counter = verify_totp(secret, body.code, last_counter=None)
            if counter is None:
                raise HTTPException(
                    status_code=400,
                    detail="Kod doğrulanamadı; telefonunuzun saatinin doğru olduğundan emin olun",
                )
            codes = new_recovery_codes()
            await conn.execute(
                "UPDATE customers SET mfa_totp_secret_enc = %s, mfa_pending_enc = NULL, "
                "mfa_enabled_at = now(), mfa_last_counter = %s, mfa_recovery_hashes = %s "
                "WHERE id = %s",
                (pending, counter, [recovery_digest(c) for c in codes], customer["id"]),
            )
            await audit(
                conn, actor_type="customer", actor_id=str(customer["id"]),
                action="customer.mfa_enabled", request=request,
            )  # fmt: skip
        return {"status": "enabled", "recovery_codes": codes}

    @router.post("/me/2fa/disable")
    async def mfa_disable(
        body: MfaDisable, request: Request, customer: dict[str, Any] = customer_dep
    ) -> dict[str, str]:
        require_origin(request)
        box()
        check_password(customer["password_hash"], body.password)
        async with db.connection() as conn:
            if await verify_second_factor(conn, customer["id"], body.code) is None:
                await conn.commit()
                raise HTTPException(status_code=400, detail="Doğrulama kodu hatalı")
            await conn.execute(
                "UPDATE customers SET mfa_enabled_at = NULL, mfa_totp_secret_enc = NULL, "
                "mfa_pending_enc = NULL, mfa_last_counter = NULL, mfa_recovery_hashes = '{}' "
                "WHERE id = %s",
                (customer["id"],),
            )
            await audit(
                conn, actor_type="customer", actor_id=str(customer["id"]),
                action="customer.mfa_disabled", request=request,
            )  # fmt: skip
        return {"status": "disabled"}

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
                " AND a.deactivated_at IS NULL)::int AS active_devices, "
                "(SELECT coalesce(json_agg(json_build_object('id', d.id::text, "
                " 'name', d.display_name, 'platform', d.platform::text, "
                " 'activated_at', a.activated_at, 'last_seen_at', d.last_seen_at) "
                " ORDER BY a.activated_at), '[]'::json) FROM license_activations a "
                " JOIN devices d ON d.id = a.device_id "
                " WHERE a.license_id = l.id AND a.deactivated_at IS NULL) AS devices, "
                "(SELECT count(*) FROM license_activations a WHERE a.license_id = l.id "
                " AND a.deactivated_by = 'customer' "
                " AND a.deactivated_at > now() - interval '30 days')::int AS resets_used "
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
            licenses=[
                LicenseInfo.model_validate(
                    {
                        **r,
                        "device_resets_left": max(
                            0, settings.device_resets_per_30d - r["resets_used"]
                        ),
                    }
                )
                for r in licenses
            ],
        )

    return router
