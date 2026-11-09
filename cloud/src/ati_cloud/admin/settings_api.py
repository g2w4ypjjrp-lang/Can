"""Sistem ayarları (``settings.manage``): ödeme sağlayıcısı ve şirket/fatura bilgileri.

Ödeme sağlayıcı anahtarları veritabanında AES-256-GCM ile şifreli durur ve API'den **geri
okunamaz** (yalnızca "tanımlı" bilgisi ve son 4 karakter). Anahtar girmek/silmek güncel TOTP
kodu ister.

Canlı ödeme iki kilitlidir:

1. Dağıtım ayarı ``ATI_PAYMENTS_LIVE_ALLOWED`` (yalnızca G3 onayıyla açılır).
2. Panelde: güncel TOTP kodu + onay ifadesi ``CANLI ÖDEMEYİ AÇ`` + gerekli anahtarların tamamı.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, EmailStr, Field

from ati_cloud.admin.context import Admin, AdminContext, Conn
from ati_cloud.admin.security import SecretBox

LIVE_PHRASE = "CANLI ÖDEMEYİ AÇ"

# Sağlayıcı başına alanlar: açık (gizli olmayan) ve gizli (şifreli, geri okunamaz). Yalnızca
# uyarlayıcısı yazılmış sağlayıcılar (``ati_cloud.payments.providers``). ``simulator`` yalnızca
# geliştirme/test ortamında seçilebilir; gerçek tahsilat yapmaz.
PROVIDERS: dict[str, dict[str, list[str]]] = {
    "none": {"public": [], "secrets": []},
    "paytr": {"public": ["merchant_id"], "secrets": ["merchant_key", "merchant_salt"]},
    "iyzico": {"public": [], "secrets": ["api_key", "secret_key"]},
    "simulator": {"public": [], "secrets": []},
}
Provider = Literal["none", "paytr", "iyzico", "simulator"]


class PaymentUpdate(BaseModel):
    provider: Provider
    mode: Literal["test", "live"] = "test"
    public: dict[str, str] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)  # yeni değerler; verilmeyen korunur
    clear: list[str] = Field(default_factory=list)
    code: str | None = Field(default=None, max_length=10)  # TOTP (anahtar değişikliği / canlı)
    confirm: str | None = Field(default=None, max_length=40)


class CompanyInfo(BaseModel):
    legal_name: str = Field(default="", max_length=200)
    address: str = Field(default="", max_length=400)
    tax_office: str = Field(default="", max_length=120)
    tax_number: str = Field(default="", pattern=r"^(\d{10,11})?$")
    mersis: str = Field(default="", pattern=r"^(\d{16})?$")
    kep: str = Field(default="", max_length=200)
    email: EmailStr | Literal[""] = ""
    phone: str = Field(default="", max_length=40)


def _aad(provider: str, name: str) -> str:
    return f"payment|{provider}|{name}"


async def _load(conn: Conn, key: str) -> dict[str, Any] | None:
    cur = await conn.execute("SELECT value FROM system_settings WHERE key = %s", (key,))
    row = await cur.fetchone()
    return dict(row["value"]) if row else None


async def _store(conn: Conn, key: str, value: dict[str, Any], admin_id: Any) -> None:
    await conn.execute(
        "INSERT INTO system_settings (key, value, updated_by) VALUES (%s, %s, %s) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = now(), "
        "updated_by = excluded.updated_by",
        (key, Jsonb(value), admin_id),
    )


def _providers_for(environment: str) -> dict[str, dict[str, list[str]]]:
    if environment in ("staging", "production"):
        return {k: v for k, v in PROVIDERS.items() if k != "simulator"}
    return PROVIDERS


def _public_view(
    stored: dict[str, Any] | None, live_allowed: bool, environment: str
) -> dict[str, Any]:
    stored = stored or {"provider": "none", "mode": "test", "public": {}, "secrets": {}}
    provider = stored.get("provider", "none")
    spec = PROVIDERS.get(provider, PROVIDERS["none"])
    secrets_info = stored.get("secrets", {})
    return {
        "provider": provider,
        "mode": stored.get("mode", "test"),
        "public": stored.get("public", {}),
        "secrets": {
            name: {
                "configured": name in secrets_info,
                "hint": secrets_info.get(name, {}).get("hint"),
                "updated_at": secrets_info.get(name, {}).get("updated_at"),
            }
            for name in spec["secrets"]
        },
        "live_allowed": live_allowed,
        "providers": _providers_for(environment),
    }


async def load_payment_secrets(conn: Conn, box: SecretBox) -> dict[str, Any]:
    """Ödeme sistemi (Aşama 17) için çözülmüş yapılandırma. API'den dışarı verilmez."""
    stored = await _load(conn, "payment") or {}
    provider = stored.get("provider", "none")
    secrets_plain = {
        name: box.open(base64.b64decode(item["enc"]), _aad(provider, name)).decode()
        for name, item in stored.get("secrets", {}).items()
    }
    return {
        "provider": provider,
        "mode": stored.get("mode", "test"),
        "public": stored.get("public", {}),
        "secrets": secrets_plain,
    }


def create_admin_settings_router(ctx: AdminContext) -> APIRouter:
    router = APIRouter(prefix="/admin/v1/settings")
    manage = ctx.depends("settings.manage")

    @router.get("/payment")
    async def get_payment(admin: Admin = manage) -> dict[str, Any]:
        async with ctx.db.connection() as conn:
            stored = await _load(conn, "payment")
        return _public_view(stored, ctx.settings.payments_live_allowed, ctx.settings.environment)

    @router.put("/payment")
    async def put_payment(
        body: PaymentUpdate, request: Request, admin: Admin = manage
    ) -> dict[str, Any]:
        spec = PROVIDERS[body.provider]
        unknown = (set(body.public) - set(spec["public"])) | (
            (set(body.secrets) | set(body.clear)) - set(spec["secrets"])
        )
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Bu sağlayıcı için geçersiz alan: {', '.join(sorted(unknown))}",
            )
        if body.provider == "simulator" and (
            ctx.settings.environment in ("staging", "production") or body.mode == "live"
        ):
            raise HTTPException(
                status_code=409,
                detail="Test ödeme simülatörü yalnızca geliştirme/test ortamında ve test modunda "
                "kullanılabilir",
            )
        box = ctx.secret_box()
        async with ctx.db.connection() as conn, conn.transaction():
            stored = await _load(conn, "payment") or {}
            same_provider = stored.get("provider") == body.provider
            secrets_stored: dict[str, Any] = (
                dict(stored.get("secrets", {})) if same_provider else {}
            )
            sensitive = bool(body.secrets or body.clear) or body.mode == "live"
            if sensitive:
                await ctx.step_up(conn, admin, body.code)
            now = datetime.now(UTC).isoformat()
            for name, raw in body.secrets.items():
                secret = raw.strip()
                if not 8 <= len(secret) <= 500:
                    raise HTTPException(status_code=422, detail=f"{name}: 8-500 karakter olmalı")
                sealed = box.seal(secret.encode(), _aad(body.provider, name))
                secrets_stored[name] = {
                    "enc": base64.b64encode(sealed).decode(),
                    "hint": f"…{secret[-4:]}",
                    "updated_at": now,
                }
            for name in body.clear:
                secrets_stored.pop(name, None)
            if body.mode == "live":
                if not ctx.settings.payments_live_allowed:
                    raise HTTPException(
                        status_code=409,
                        detail="Canlı ödeme bu dağıtımda kapalı. Açılması için işletme sahibinin "
                        "açık onayı (G3) ve dağıtım ayarı gerekir.",
                    )
                if body.confirm != LIVE_PHRASE:
                    raise HTTPException(status_code=400, detail=f"Onay için '{LIVE_PHRASE}' yazın")
                missing = [n for n in spec["secrets"] if n not in secrets_stored]
                if body.provider == "none" or missing:
                    raise HTTPException(
                        status_code=409,
                        detail="Canlı ödeme için sağlayıcı ve tüm anahtarlar tanımlı olmalı"
                        + (f" (eksik: {', '.join(missing)})" if missing else ""),
                    )
            value = {
                "provider": body.provider,
                "mode": body.mode,
                "public": {k: v.strip()[:200] for k, v in body.public.items()},
                "secrets": secrets_stored,
            }
            await _store(conn, "payment", value, admin.id)
            went_live = body.mode == "live" and stored.get("mode") != "live"
            await ctx.audit(
                conn, request, actor_id=admin.id,
                action=(
                    "admin.payments_live_enabled" if went_live else "admin.payment_settings_updated"
                ),
                target_type="settings", target_id="payment",
                details={
                    "provider": body.provider, "mode": body.mode,
                    "secrets_set": sorted(body.secrets), "secrets_cleared": sorted(body.clear),
                },
            )  # fmt: skip
        return _public_view(value, ctx.settings.payments_live_allowed, ctx.settings.environment)

    @router.get("/company")
    async def get_company(admin: Admin = manage) -> dict[str, Any]:
        async with ctx.db.connection() as conn:
            stored = await _load(conn, "company")
        return CompanyInfo.model_validate(stored or {}).model_dump()

    @router.put("/company")
    async def put_company(
        body: CompanyInfo, request: Request, admin: Admin = manage
    ) -> dict[str, Any]:
        value = body.model_dump()
        async with ctx.db.connection() as conn, conn.transaction():
            await _store(conn, "company", value, admin.id)
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.company_updated",
                target_type="settings", target_id="company",
            )  # fmt: skip
        return value

    return router
