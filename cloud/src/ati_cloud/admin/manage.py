"""Yönetim uç noktaları: paketler, lisanslar, müşteriler, cihazlar, siparişler, mesajlar, raporlar,
denetim kaydı. Her uç nokta tek bir yetkiye bağlıdır (``ctx.depends("<yetki>")``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from psycopg import errors as pg_errors
from psycopg.types.json import Jsonb
from pydantic import BaseModel, EmailStr, Field

from ati_cloud.admin.context import Admin, AdminContext, Conn
from ati_cloud.licensing.keys import InvalidLicenseKey
from ati_cloud.licensing.service import LicenseError, Licensing

Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0, le=1_000_000)]


class PlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    price_minor: int | None = Field(default=None, ge=0, le=100_000_000_00)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10_000)
    companion_device_limit: int | None = Field(default=None, ge=0, le=10)
    features: dict[str, Any] | None = None


class CouponCreate(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{2,31}$")
    percent_off: int | None = Field(default=None, ge=1, le=100)
    amount_off_minor: int | None = Field(default=None, gt=0, le=100_000_000_00)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    plan_codes: list[Annotated[str, Field(pattern=r"^[a-z0-9_]{1,40}$")]] = Field(
        default_factory=list, max_length=20
    )
    max_redemptions: int | None = Field(default=None, ge=1, le=1_000_000)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    note: str = Field(default="", max_length=200)


class CouponUpdate(BaseModel):
    is_active: bool | None = None
    max_redemptions: int | None = Field(default=None, ge=1, le=1_000_000)
    valid_until: datetime | None = None
    note: str | None = Field(default=None, max_length=200)


class GenerateRequest(BaseModel):
    plan_code: str = Field(min_length=1, max_length=40)
    customer_email: EmailStr | None = None


class AssignRequest(BaseModel):
    customer_email: EmailStr


class BatchRequest(BaseModel):
    plan_code: str = Field(min_length=1, max_length=40)
    quantity: int = Field(ge=1, le=1000)
    purpose: Literal["sale_pool", "manual", "promotion", "replacement"] = "sale_pool"
    note: str | None = Field(default=None, max_length=300)


class Reason(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class ExtendRequest(BaseModel):
    days: int = Field(ge=1, le=3650)
    reason: str = Field(min_length=3, max_length=300)


class StepUpCode(BaseModel):
    code: str = Field(min_length=6, max_length=10)


class DeleteCustomer(BaseModel):
    """Müşteri silme: yanlış kişiyi silmemek için e-posta adresi yazılarak onaylanır."""

    code: str = Field(min_length=6, max_length=10)
    confirm_email: str = Field(min_length=3, max_length=320)
    reason: str = Field(min_length=3, max_length=300)


class MessageStatus(BaseModel):
    status: Literal["new", "in_progress", "closed", "spam"]


PERMISSIONS = (
    "device.read",
    "report.payments",
    "audit.read",
    "coupon.manage",
    "customer.block",
    "customer.delete",
    "customer.read",
    "customer.update",
    "device.revoke",
    "license.bulk_generate",
    "license.cancel",
    "license.extend",
    "license.freeze",
    "license.generate",
    "license.read",
    "license.reveal_key",
    "order.read",
    "payment.read",
    "plan.manage",
    "report.sales",
    "report.usage",
)


def _uuid(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"{what} bulunamadı") from exc


def create_admin_manage_router(ctx: AdminContext) -> APIRouter:
    router = APIRouter(prefix="/admin/v1")
    # Her yetki için bağımlılık bir kez oluşturulur (uç noktalar need["<yetki>"] ile kullanır).
    need = {code: ctx.depends(code) for code in PERMISSIONS}

    def licensing() -> Licensing:
        if ctx.licensing is None:
            raise HTTPException(status_code=503, detail="Lisans servisi yapılandırılmadı")
        return ctx.licensing

    async def change_license(
        conn: Conn, admin: Admin, request: Request, license_id: str, sql: str,
        params: tuple[Any, ...],
        action: str, details: dict[str, Any],
    ) -> dict[str, Any]:  # fmt: skip
        lic = _uuid(license_id, "Lisans")
        await ctx.act_as(conn, admin)
        try:
            cur = await conn.execute(sql, (*params, lic))
        except pg_errors.CheckViolation as exc:
            raise HTTPException(status_code=409, detail=str(exc.diag.message_primary)) from exc
        row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=409, detail="Lisans bu işlem için uygun durumda değil")
        await ctx.audit(
            conn, request, actor_id=admin.id, action=action, target_type="license",
            target_id=lic, details=details,
        )  # fmt: skip
        return {"id": str(lic), "status": row["status"]}

    # --- Panel özeti ----------------------------------------------------------------------

    @router.get("/stats")
    async def stats(admin: Admin = need["report.usage"]) -> dict[str, Any]:
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT status::text AS status, sum(license_count)::int AS n "
                "FROM admin_license_stats GROUP BY status"
            )
            licenses = {r["status"]: r["n"] for r in await cur.fetchall()}
            cur = await conn.execute(
                "SELECT platform::text AS platform, active_devices::int AS devices, "
                "active_customers::int AS customers FROM admin_active_usage"
            )
            usage = await cur.fetchall()
            cur = await conn.execute(
                "SELECT count(*)::int AS total, "
                "count(*) FILTER (WHERE created_at > now() - interval '30 days')::int AS new_30d, "
                "count(*) FILTER (WHERE status = 'blocked')::int AS blocked "
                "FROM customers WHERE status <> 'deleted'"
            )
            customers = await cur.fetchone()
            cur = await conn.execute(
                "SELECT count(*)::int AS n FROM contact_messages WHERE status = 'new'"
            )
            messages = await cur.fetchone()
        return {
            "licenses": licenses,
            "usage": usage,
            "customers": customers,
            "new_messages": messages["n"] if messages else 0,
        }

    # --- Paketler ve fiyatlar ----------------------------------------------------------------

    @router.get("/plans")
    async def plans(admin: Admin = need["plan.manage"]) -> list[dict[str, Any]]:
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT code, name, duration_days, device_limit, companion_device_limit, is_trial, "
                "price_minor, currency, is_active, features, sort_order, updated_at "
                "FROM license_plans ORDER BY sort_order, code"
            )
            return await cur.fetchall()

    @router.patch("/plans/{code}")
    async def update_plan(
        code: str, body: PlanUpdate, request: Request, admin: Admin = need["plan.manage"]
    ) -> dict[str, Any]:
        changes = body.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(status_code=422, detail="Değişiklik yok")
        if "features" in changes:
            changes["features"] = Jsonb(changes["features"])
        assignments = ", ".join(f"{name} = %s" for name in changes)
        async with ctx.db.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "SELECT code, price_minor, currency, is_active FROM license_plans WHERE code = %s "
                "FOR UPDATE",
                (code,),
            )
            before = await cur.fetchone()
            if before is None:
                raise HTTPException(status_code=404, detail="Paket bulunamadı")
            try:
                cur = await conn.execute(
                    f"UPDATE license_plans SET {assignments} WHERE code = %s "  # noqa: S608 - sütun adları modelden
                    f""
                    "RETURNING code, name, price_minor, currency, is_active, sort_order",
                    (*changes.values(), code),
                )
            except pg_errors.CheckViolation as exc:
                message = (
                    "Fiyatı girilmemiş paket satışa açılamaz"
                    if "has_price" in (exc.diag.constraint_name or "")
                    else str(exc.diag.message_primary)
                )
                raise HTTPException(status_code=409, detail=message) from exc
            after = await cur.fetchone()
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.plan_updated",
                target_type="plan", target_id=code,
                details={
                    "before": {k: before[k] for k in ("price_minor", "currency", "is_active")},
                    "changes": body.model_dump(exclude_unset=True),
                },
            )  # fmt: skip
        return dict(after or {})

    # --- İndirim kuponları -------------------------------------------------------------------

    coupon_columns = (
        "c.code, c.percent_off, c.amount_off_minor, c.currency, c.plan_codes, c.max_redemptions, "
        "c.valid_from, c.valid_until, c.is_active, c.note, c.created_at, "
        "(SELECT count(*) FROM orders o WHERE o.coupon_code = c.code "
        " AND o.status IN ('paid', 'fulfilled'))::int AS redemptions, "
        "(SELECT COALESCE(sum(o.discount_minor), 0) FROM orders o WHERE o.coupon_code = c.code "
        " AND o.status IN ('paid', 'fulfilled'))::bigint AS discount_total_minor"
    )

    @router.get("/coupons")
    async def coupons(admin: Admin = need["coupon.manage"]) -> list[dict[str, Any]]:
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                f"SELECT {coupon_columns} FROM coupons c ORDER BY c.created_at DESC LIMIT 500"  # noqa: S608
            )
            return await cur.fetchall()

    @router.post("/coupons")
    async def create_coupon(
        body: CouponCreate, request: Request, admin: Admin = need["coupon.manage"]
    ) -> dict[str, Any]:
        if (body.percent_off is None) == (body.amount_off_minor is None):
            raise HTTPException(
                status_code=422, detail="Yüzde ya da tutar indiriminden birini girin"
            )
        if body.amount_off_minor is not None and body.currency is None:
            raise HTTPException(status_code=422, detail="Tutar indirimi için para birimi gerekli")
        if body.valid_from and body.valid_until and body.valid_until <= body.valid_from:
            raise HTTPException(status_code=422, detail="Bitiş tarihi başlangıçtan sonra olmalı")
        code = body.code.upper()
        async with ctx.db.connection() as conn, conn.transaction():
            if body.plan_codes:
                cur = await conn.execute(
                    "SELECT array_agg(code) AS found FROM license_plans WHERE code = ANY(%s)",
                    (body.plan_codes,),
                )
                found = set((await cur.fetchone() or {}).get("found") or [])
                missing = sorted(set(body.plan_codes) - found)
                if missing:
                    raise HTTPException(
                        status_code=422, detail=f"Paket bulunamadı: {', '.join(missing)}"
                    )
            try:
                await conn.execute(
                    "INSERT INTO coupons (code, percent_off, amount_off_minor, currency, "
                    "plan_codes, max_redemptions, valid_from, valid_until, note, created_by) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        code, body.percent_off, body.amount_off_minor,
                        body.currency if body.amount_off_minor is not None else None,
                        sorted(set(body.plan_codes)), body.max_redemptions, body.valid_from,
                        body.valid_until, body.note.strip(), admin.id,
                    ),
                )  # fmt: skip
            except pg_errors.UniqueViolation as exc:
                raise HTTPException(status_code=409, detail="Bu kod zaten var") from exc
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.coupon_created",
                target_type="coupon", target_id=code,
                details=body.model_dump(mode="json", exclude={"code"}),
            )  # fmt: skip
            cur = await conn.execute(
                f"SELECT {coupon_columns} FROM coupons c WHERE c.code = %s",  # noqa: S608
                (code,),
            )
            return dict(await cur.fetchone() or {})

    @router.patch("/coupons/{code}")
    async def update_coupon(
        code: str, body: CouponUpdate, request: Request, admin: Admin = need["coupon.manage"]
    ) -> dict[str, Any]:
        changes = body.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(status_code=422, detail="Değişiklik yok")
        assignments = ", ".join(f"{name} = %s" for name in changes)
        async with ctx.db.connection() as conn, conn.transaction():
            try:
                cur = await conn.execute(
                    f"UPDATE coupons SET {assignments} WHERE code = %s RETURNING code",  # noqa: S608 - sütun adları modelden
                    (*changes.values(), code.upper()),
                )
            except pg_errors.CheckViolation as exc:
                raise HTTPException(status_code=409, detail=str(exc.diag.message_primary)) from exc
            if await cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Kupon bulunamadı")
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.coupon_updated",
                target_type="coupon", target_id=code.upper(),
                details=body.model_dump(mode="json", exclude_unset=True),
            )  # fmt: skip
            cur = await conn.execute(
                f"SELECT {coupon_columns} FROM coupons c WHERE c.code = %s",  # noqa: S608
                (code.upper(),),
            )
            return dict(await cur.fetchone() or {})

    # --- Lisanslar -------------------------------------------------------------------------

    @router.get("/licenses")
    async def list_licenses(
        admin: Admin = need["license.read"],
        q: Annotated[str | None, Query(max_length=120)] = None,
        status: Annotated[str | None, Query(pattern=r"^[a-z_]+$")] = None,
        plan: Annotated[str | None, Query(max_length=40)] = None,
        limit: Limit = 50,
        offset: Offset = 0,
    ) -> dict[str, Any]:
        where = ["true"]
        params: list[Any] = []
        if q:
            text = q.strip()
            try:
                digest = licensing().hasher.digest(text)
                where.append("l.key_hash = %s")
                params.append(digest)
            except (InvalidLicenseKey, HTTPException):
                if text.isdigit():
                    where.append("l.serial = %s")
                    params.append(int(text))
                else:
                    where.append("(c.email ILIKE %s OR l.key_hint ILIKE %s)")
                    params.extend([f"%{text}%", f"%{text.upper()}"])
        if status:
            where.append("l.status::text = %s")
            params.append(status)
        if plan:
            where.append("l.plan_code = %s")
            params.append(plan)
        clause = " AND ".join(where)
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT l.id::text, l.serial, l.key_hint, l.plan_code, l.status::text, "  # noqa: S608
                ""
                "l.expires_at, l.sold_at, l.activated_at, c.email AS customer_email, "
                "(SELECT count(*) FROM license_activations a WHERE a.license_id = l.id "
                " AND a.deactivated_at IS NULL)::int AS active_devices, l.device_limit "
                "FROM licenses l LEFT JOIN customers c ON c.id = l.customer_id "
                f"WHERE {clause} ORDER BY l.serial DESC LIMIT %s OFFSET %s",
                (*params, limit, offset),
            )
            items = await cur.fetchall()
            cur = await conn.execute(
                "SELECT count(*)::int AS n FROM licenses l "  # noqa: S608
                f"LEFT JOIN customers c ON c.id = l.customer_id WHERE {clause}",
                tuple(params),
            )
            total = await cur.fetchone()
        return {"items": items, "total": total["n"] if total else 0}

    @router.get("/licenses/{license_id}")
    async def license_detail(
        license_id: str, admin: Admin = need["license.read"]
    ) -> dict[str, Any]:
        lic = _uuid(license_id, "Lisans")
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT l.id::text, l.serial, l.key_hint, l.plan_code, l.status::text, "
                "l.duration_days, l.device_limit, l.companion_device_limit, l.sold_at, "
                "l.activated_at, l.expires_at, l.frozen_reason, l.cancel_reason, l.created_at, "
                "c.id::text AS customer_id, c.email AS customer_email "
                "FROM licenses l LEFT JOIN customers c ON c.id = l.customer_id WHERE l.id = %s",
                (lic,),
            )
            row = await cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Lisans bulunamadı")
            cur = await conn.execute(
                "SELECT from_status::text, to_status::text, actor_type::text, actor_id, details, "
                "occurred_at FROM license_events WHERE license_id = %s ORDER BY id DESC LIMIT 100",
                (lic,),
            )
            events = await cur.fetchall()
            cur = await conn.execute(
                "SELECT d.id::text AS device_id, d.display_name, d.platform::text, a.activated_at, "
                "a.last_validated_at, a.deactivated_at, a.deactivated_by::text "
                "FROM license_activations a JOIN devices d ON d.id = a.device_id "
                "WHERE a.license_id = %s ORDER BY a.activated_at DESC",
                (lic,),
            )
            activations = await cur.fetchall()
        return {**row, "events": events, "activations": activations}

    @router.post("/licenses")
    async def generate(
        body: GenerateRequest, request: Request, admin: Admin = need["license.generate"]
    ) -> dict[str, str]:
        service = licensing()
        async with ctx.db.connection() as conn:
            customer_id = None
            if body.customer_email:
                cur = await conn.execute(
                    "SELECT id FROM customers WHERE email = %s AND status = 'active'",
                    (str(body.customer_email).lower(),),
                )
                row = await cur.fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail="Etkin müşteri bulunamadı")
                customer_id = row["id"]
            await ctx.act_as(conn, admin)
            try:
                license_id, key = await service.issue(
                    conn, plan_code=body.plan_code, customer_id=customer_id
                )
            except LicenseError as exc:
                raise HTTPException(status_code=exc.status, detail=exc.message) from exc
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.license_generated",
                target_type="license", target_id=license_id,
                details={
                    "plan": body.plan_code,
                    "customer": str(customer_id) if customer_id else None,
                },
            )  # fmt: skip
        return {"id": license_id, "key": key}

    @router.post("/licenses/batch")
    async def generate_batch(
        body: BatchRequest, request: Request, admin: Admin = need["license.bulk_generate"]
    ) -> dict[str, Any]:
        service = licensing()
        keys: list[dict[str, str]] = []
        async with ctx.db.connection() as conn, conn.transaction():
            await ctx.act_as(conn, admin)
            try:
                cur = await conn.execute(
                    "INSERT INTO license_batches (plan_code, quantity, purpose, note, "
                    "created_by_admin) VALUES (%s, %s, %s, %s, %s) RETURNING id::text",
                    (body.plan_code, body.quantity, body.purpose, body.note, admin.id),
                )
            except pg_errors.ForeignKeyViolation as exc:
                raise HTTPException(status_code=404, detail="Paket bulunamadı") from exc
            batch = await cur.fetchone()
            if batch is None:
                raise HTTPException(status_code=500, detail="Parti oluşturulamadı")
            for _ in range(body.quantity):
                license_id, key = await service.issue(
                    conn, plan_code=body.plan_code, batch_id=batch["id"]
                )
                keys.append({"id": license_id, "key": key})
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.license_batch_generated",
                target_type="license_batch", target_id=batch["id"],
                details={
                    "plan": body.plan_code, "quantity": body.quantity, "purpose": body.purpose,
                },
            )  # fmt: skip
        return {"batch_id": batch["id"], "licenses": keys}

    @router.post("/licenses/{license_id}/assign")
    async def assign(
        license_id: str,
        body: AssignRequest,
        request: Request,
        admin: Admin = need["license.generate"],
    ) -> dict[str, Any]:
        """Satış havuzundaki (müşterisiz) lisansı bir müşteriye elle satar/teslim eder.

        Ödeme teslimindeki gibi paket koşulları satış anında güncellenir; yalnızca henüz kimseye
        ait olmayan (``generated``/``ready_for_sale``) lisans atanabilir.
        """
        async with ctx.db.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "SELECT id FROM customers WHERE email = %s AND status = 'active'",
                (str(body.customer_email).lower(),),
            )
            customer = await cur.fetchone()
            if customer is None:
                raise HTTPException(status_code=404, detail="Etkin müşteri bulunamadı")
            return await change_license(
                conn, admin, request, license_id,
                "UPDATE licenses l SET status = 'sold', customer_id = %s, sold_at = now(), "
                "duration_days = p.duration_days, device_limit = p.device_limit, "
                "companion_device_limit = p.companion_device_limit FROM license_plans p "
                "WHERE p.code = l.plan_code AND l.id = %s "
                "AND l.status IN ('generated', 'ready_for_sale') "
                "RETURNING l.status::text AS status",
                (customer["id"],), "admin.license_assigned", {"customer": str(customer["id"])},
            )  # fmt: skip

    @router.post("/licenses/{license_id}/freeze")
    async def freeze(
        license_id: str,
        body: Reason,
        request: Request,
        admin: Admin = need["license.freeze"],
    ) -> dict[str, Any]:
        async with ctx.db.connection() as conn, conn.transaction():
            return await change_license(
                conn, admin, request, license_id,
                "UPDATE licenses SET status = 'frozen', frozen_reason = %s WHERE id = %s "
                "AND status IN ('ready_for_sale', 'sold', 'active', 'expired') RETURNING "
                "status::text",
                (body.reason,), "admin.license_frozen", {"reason": body.reason},
            )  # fmt: skip

    @router.post("/licenses/{license_id}/unfreeze")
    async def unfreeze(
        license_id: str, request: Request, admin: Admin = need["license.freeze"]
    ) -> dict[str, Any]:
        async with ctx.db.connection() as conn, conn.transaction():
            return await change_license(
                conn, admin, request, license_id,
                "UPDATE licenses SET status = status_before_freeze WHERE id = %s "
                "AND status = 'frozen' RETURNING status::text",
                (), "admin.license_unfrozen", {},
            )  # fmt: skip

    @router.post("/licenses/{license_id}/cancel")
    async def cancel(
        license_id: str,
        body: Reason,
        request: Request,
        admin: Admin = need["license.cancel"],
    ) -> dict[str, Any]:
        async with ctx.db.connection() as conn, conn.transaction():
            return await change_license(
                conn, admin, request, license_id,
                "UPDATE licenses SET status = 'cancelled', cancel_reason = %s WHERE id = %s "
                "AND status <> 'cancelled' RETURNING status::text",
                (body.reason,), "admin.license_cancelled", {"reason": body.reason},
            )  # fmt: skip

    @router.post("/licenses/{license_id}/extend")
    async def extend(
        license_id: str,
        body: ExtendRequest,
        request: Request,
        admin: Admin = need["license.extend"],
    ) -> dict[str, Any]:
        lic = _uuid(license_id, "Lisans")
        async with ctx.db.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "SELECT status::text, expires_at, duration_days FROM licenses WHERE id = %s FOR "
                "UPDATE",
                (lic,),
            )
            row = await cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Lisans bulunamadı")
            if row["duration_days"] is None and row["expires_at"] is None:
                raise HTTPException(status_code=409, detail="Süresiz lisans uzatılamaz")
            if row["status"] in ("cancelled", "frozen"):
                raise HTTPException(
                    status_code=409, detail="İptal edilmiş veya dondurulmuş lisans uzatılamaz"
                )
            await ctx.act_as(conn, admin)
            if row["expires_at"] is None:  # henüz etkinleştirilmedi: süre etkinleştirmede başlar
                sql = (
                    "UPDATE licenses SET duration_days = duration_days + %s WHERE id = %s "
                    "RETURNING status::text"
                )
            else:
                sql = (
                    "UPDATE licenses SET expires_at = expires_at + make_interval(days => %s), "
                    "status = CASE WHEN status = 'expired' AND expires_at + make_interval(days => "
                    "%s) "
                    "> now() THEN 'active'::license_status ELSE status END "
                    "WHERE id = %s RETURNING status::text"
                )
            params: tuple[Any, ...] = (
                (body.days,) if row["expires_at"] is None else (body.days, body.days)
            )
            return await change_license(
                conn, admin, request, license_id, sql, params, "admin.license_extended",
                {"days": body.days, "reason": body.reason},
            )  # fmt: skip

    @router.post("/licenses/{license_id}/reveal")
    async def reveal(
        license_id: str,
        body: StepUpCode,
        request: Request,
        admin: Admin = need["license.reveal_key"],
    ) -> dict[str, str]:
        lic = _uuid(license_id, "Lisans")
        service = licensing()
        async with ctx.db.connection() as conn, conn.transaction():
            await ctx.step_up(conn, admin, body.code)
            cur = await conn.execute(
                "SELECT key_hash, key_ciphertext FROM licenses WHERE id = %s", (lic,)
            )
            row = await cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Lisans bulunamadı")
            key = service.cipher.decrypt(bytes(row["key_ciphertext"]), bytes(row["key_hash"]))
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.license_key_revealed",
                target_type="license", target_id=lic,
            )  # fmt: skip
        return {"key": key}

    # --- Müşteriler ve cihazlar ----------------------------------------------------------------

    @router.get("/customers")
    async def list_customers(
        admin: Admin = need["customer.read"],
        q: Annotated[str | None, Query(max_length=120)] = None,
        status: Annotated[Literal["active", "blocked"] | None, Query()] = None,
        limit: Limit = 50,
        offset: Offset = 0,
    ) -> dict[str, Any]:
        where = ["c.status <> 'deleted'"]
        params: list[Any] = []
        if q:
            where.append("(c.email ILIKE %s OR c.full_name ILIKE %s)")
            params.extend([f"%{q.strip()}%"] * 2)
        if status:
            where.append("c.status::text = %s")
            params.append(status)
        clause = " AND ".join(where)
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT c.id::text, c.email, c.full_name, c.status::text, c.created_at, "  # noqa: S608
                ""
                "c.last_login_at, c.email_verified_at IS NOT NULL AS email_verified, "
                "(SELECT count(*) FROM licenses l WHERE l.customer_id = c.id)::int AS licenses "
                f"FROM customers c WHERE {clause} ORDER BY c.created_at DESC LIMIT %s OFFSET %s",
                (*params, limit, offset),
            )
            items = await cur.fetchall()
            cur = await conn.execute(
                f"SELECT count(*)::int AS n FROM customers c WHERE {clause}",  # noqa: S608
                tuple(params),
            )
            total = await cur.fetchone()
        return {"items": items, "total": total["n"] if total else 0}

    @router.get("/customers/{customer_id}")
    async def customer_detail(
        customer_id: str, admin: Admin = need["customer.read"]
    ) -> dict[str, Any]:
        cid = _uuid(customer_id, "Müşteri")
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT id::text, email, full_name, status::text, blocked_reason, blocked_at, "
                "created_at, last_login_at, email_verified_at, marketing_consent "
                "FROM customers WHERE id = %s",
                (cid,),
            )
            row = await cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Müşteri bulunamadı")
            cur = await conn.execute(
                "SELECT id::text, serial, key_hint, plan_code, status::text, expires_at "
                "FROM licenses WHERE customer_id = %s ORDER BY serial DESC",
                (cid,),
            )
            licenses = await cur.fetchall()
            cur = await conn.execute(
                "SELECT id::text, display_name, platform::text, first_seen_at, last_seen_at, "
                "revoked_at FROM devices WHERE customer_id = %s ORDER BY last_seen_at DESC",
                (cid,),
            )
            devices = await cur.fetchall()
        return {**row, "licenses": licenses, "devices": devices}

    @router.post("/customers/{customer_id}/block")
    async def block_customer(
        customer_id: str,
        body: Reason,
        request: Request,
        admin: Admin = need["customer.block"],
    ) -> dict[str, str]:
        cid = _uuid(customer_id, "Müşteri")
        async with ctx.db.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "UPDATE customers SET status = 'blocked', blocked_at = now(), blocked_reason = %s "
                "WHERE id = %s AND status = 'active' RETURNING id",
                (body.reason, cid),
            )
            if await cur.fetchone() is None:
                raise HTTPException(status_code=409, detail="Müşteri etkin değil veya bulunamadı")
            await conn.execute(
                "UPDATE customer_sessions SET revoked_at = now() WHERE customer_id = %s "
                "AND revoked_at IS NULL",
                (cid,),
            )
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.customer_blocked",
                target_type="customer", target_id=cid, details={"reason": body.reason},
            )  # fmt: skip
        return {"status": "blocked"}

    @router.post("/customers/{customer_id}/unblock")
    async def unblock_customer(
        customer_id: str, request: Request, admin: Admin = need["customer.block"]
    ) -> dict[str, str]:
        cid = _uuid(customer_id, "Müşteri")
        async with ctx.db.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "UPDATE customers SET status = 'active', blocked_at = NULL, blocked_reason = NULL "
                "WHERE id = %s AND status = 'blocked' RETURNING id",
                (cid,),
            )
            if await cur.fetchone() is None:
                raise HTTPException(status_code=409, detail="Müşteri engelli değil veya bulunamadı")
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.customer_unblocked",
                target_type="customer", target_id=cid,
            )  # fmt: skip
        return {"status": "active"}

    @router.post("/customers/{customer_id}/delete")
    async def delete_customer(
        customer_id: str,
        body: DeleteCustomer,
        request: Request,
        admin: Admin = need["customer.delete"],
    ) -> dict[str, Any]:
        """Müşteriyi siler (KVKK: kişisel veriler anonimleştirilir, kayıt geri alınamaz).

        * E-posta, ad, parola ve 2FA silinir; aynı e-postayla yeniden kayıt olunabilir.
        * Lisansları iptal edilir (bilgisayardaki uygulama bir sonraki yenilemede kapanır),
          cihazları ve oturumları kapatılır, bekleyen e-postaları silinir.
        * Siparişler ve ödemeler yasal saklama süresi boyunca korunur (müşteri kimliğiyle,
          kişisel veri olmadan); denetim kaydına e-posta yazılmaz.
        """
        cid = _uuid(customer_id, "Müşteri")
        anon = f"silindi-{cid}@silindi.invalid"
        async with ctx.db.connection() as conn, conn.transaction():
            await ctx.step_up(conn, admin, body.code)
            cur = await conn.execute(
                "SELECT email::text AS email FROM customers WHERE id = %s AND status <> 'deleted' "
                "FOR UPDATE",
                (cid,),
            )
            row = await cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Müşteri bulunamadı")
            email = str(row["email"])
            if body.confirm_email.strip().lower() != email.lower():
                raise HTTPException(
                    status_code=422, detail="Yazılan e-posta adresi müşteriyle eşleşmiyor"
                )
            cur = await conn.execute(
                "UPDATE licenses SET status = 'cancelled', cancel_reason = %s "
                "WHERE customer_id = %s AND status NOT IN ('cancelled', 'expired') RETURNING id",
                ("Müşteri silindi", cid),
            )
            licenses = len(await cur.fetchall())
            cur = await conn.execute(
                "UPDATE devices SET revoked_at = now() WHERE customer_id = %s "
                "AND revoked_at IS NULL RETURNING id",
                (cid,),
            )
            devices = len(await cur.fetchall())
            await conn.execute(
                "UPDATE customer_sessions SET revoked_at = now() WHERE customer_id = %s "
                "AND revoked_at IS NULL",
                (cid,),
            )
            await conn.execute("DELETE FROM customer_tokens WHERE customer_id = %s", (cid,))
            await conn.execute(
                "DELETE FROM customer_login_challenges WHERE customer_id = %s", (cid,)
            )
            await conn.execute(
                "DELETE FROM email_outbox WHERE to_email = %s AND status <> 'sent'", (email,)
            )
            await conn.execute(
                "UPDATE email_outbox SET to_email = %s WHERE to_email = %s", (anon, email)
            )
            await conn.execute(
                "UPDATE contact_messages SET name = 'Silinmiş müşteri', email = %s "
                "WHERE customer_id = %s OR email = %s",
                (anon, cid, email),
            )
            await conn.execute(
                "UPDATE customers SET status = 'deleted', deleted_at = now(), email = %s, "
                "full_name = NULL, password_hash = NULL, mfa_totp_secret_enc = NULL, "
                "mfa_enabled_at = NULL, mfa_pending_enc = NULL, mfa_last_counter = NULL, "
                "mfa_recovery_hashes = '{}', "
                "marketing_consent = false, country_code = NULL, blocked_at = NULL, "
                "blocked_reason = NULL WHERE id = %s",
                (anon, cid),
            )
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.customer_deleted",
                target_type="customer", target_id=cid,
                details={"reason": body.reason, "licenses_cancelled": licenses,
                         "devices_revoked": devices},
            )  # fmt: skip
        return {"status": "deleted", "licenses_cancelled": licenses, "devices_revoked": devices}

    @router.get("/devices")
    async def list_devices(
        admin: Admin = need["device.read"],
        q: Annotated[str | None, Query(max_length=120)] = None,
        limit: Limit = 50,
        offset: Offset = 0,
    ) -> list[dict[str, Any]]:
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT d.id::text, d.display_name, d.platform::text, d.app_version, d.os_version, "
                "d.first_seen_at, d.last_seen_at, d.revoked_at, c.email AS customer_email, "
                "(SELECT count(*) FROM license_activations a WHERE a.device_id = d.id "
                " AND a.deactivated_at IS NULL)::int AS active_licenses "
                "FROM devices d JOIN customers c ON c.id = d.customer_id "
                "WHERE (%s::text IS NULL OR c.email ILIKE %s OR d.display_name ILIKE %s) "
                "ORDER BY d.last_seen_at DESC LIMIT %s OFFSET %s",
                (q, f"%{q}%", f"%{q}%", limit, offset),
            )
            return await cur.fetchall()

    @router.post("/devices/{device_id}/revoke")
    async def revoke_device(
        device_id: str, body: Reason, request: Request, admin: Admin = need["device.revoke"]
    ) -> dict[str, Any]:
        did = _uuid(device_id, "Cihaz")
        async with ctx.db.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "UPDATE devices SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL "
                "RETURNING id",
                (did,),
            )
            if await cur.fetchone() is None:
                raise HTTPException(
                    status_code=409, detail="Cihaz zaten kaldırılmış veya bulunamadı"
                )
            cur = await conn.execute(
                "UPDATE license_activations SET deactivated_at = now(), deactivated_by = 'admin', "
                "deactivation_reason = %s WHERE device_id = %s AND deactivated_at IS NULL "
                "RETURNING id",
                (f"admin: {body.reason}"[:300], did),
            )
            released = len(await cur.fetchall())
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.device_revoked",
                target_type="device", target_id=did,
                details={"reason": body.reason, "activations": released},
            )  # fmt: skip
        return {"revoked": True, "released_activations": released}

    # --- Siparişler ve ödemeler (ayrıntı, iade, mutabakat: ati_cloud.payments.api) ---------------

    @router.get("/orders")
    async def orders(
        admin: Admin = need["order.read"],
        limit: Limit = 50,
        offset: Offset = 0,
        status: Annotated[str | None, Query(pattern=r"^[a-z_]{3,20}$")] = None,
        review: bool = False,
        q: Annotated[str | None, Query(max_length=120)] = None,
    ) -> list[dict[str, Any]]:
        where: list[str] = ["true"]
        params: list[Any] = []
        if status:
            where.append("o.status::text = %s")
            params.append(status)
        if review:
            where.append("o.review_reason IS NOT NULL")
        if q:
            if q.isdigit():
                where.append("o.order_no = %s")
                params.append(int(q))
            else:
                where.append("c.email ILIKE %s")
                params.append(f"%{q.strip()}%")
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT o.id::text, o.order_no, o.status::text, o.currency, "  # noqa: S608
                "o.total_minor, o.payment_provider, o.review_reason, o.created_at, o.paid_at, "
                "c.email AS customer_email, (SELECT p.name FROM order_items i "
                "JOIN license_plans p ON p.code = i.plan_code WHERE i.order_id = o.id LIMIT 1) "
                "AS plan_name FROM orders o JOIN customers c ON c.id = o.customer_id "
                f"WHERE {' AND '.join(where)} "  # koşullar yalnızca sabit ifadeler
                "ORDER BY o.created_at DESC LIMIT %s OFFSET %s",
                (*params, limit, offset),
            )
            return await cur.fetchall()

    @router.get("/payments")
    async def payments(
        admin: Admin = need["payment.read"], limit: Limit = 50, offset: Offset = 0
    ) -> list[dict[str, Any]]:
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT p.id::text, p.order_id::text, p.status::text, p.amount_minor, p.currency, "
                "p.provider, p.created_at FROM payments p ORDER BY p.created_at DESC "
                "LIMIT %s OFFSET %s",
                (limit, offset),
            )
            return await cur.fetchall()

    # --- İletişim mesajları -------------------------------------------------------------------

    @router.get("/messages")
    async def messages(
        admin: Admin = need["customer.read"],
        status: Annotated[Literal["new", "in_progress", "closed", "spam"] | None, Query()] = None,
        limit: Limit = 50,
        offset: Offset = 0,
    ) -> list[dict[str, Any]]:
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT id, name, email, topic, message, status, created_at, handled_at, "
                "customer_id::text FROM contact_messages WHERE (%s::text IS NULL OR status = %s) "
                "ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (status, status, limit, offset),
            )
            return await cur.fetchall()

    @router.post("/messages/{message_id}/status")
    async def message_status(
        message_id: int,
        body: MessageStatus,
        request: Request,
        admin: Admin = need["customer.update"],
    ) -> dict[str, str]:
        async with ctx.db.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "UPDATE contact_messages SET status = %s, handled_by = %s, handled_at = now() "
                "WHERE id = %s RETURNING id",
                (body.status, admin.id, message_id),
            )
            if await cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Mesaj bulunamadı")
            await ctx.audit(
                conn, request, actor_id=admin.id, action="admin.message_status",
                target_type="contact_message", target_id=message_id,
                details={"status": body.status},
            )  # fmt: skip
        return {"status": body.status}

    # --- Raporlar ------------------------------------------------------------------------------

    @router.get("/reports/sales")
    async def sales(
        admin: Admin = need["report.sales"], days: Annotated[int, Query(ge=1, le=730)] = 30
    ) -> list[dict[str, Any]]:
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT day, currency, order_count::int, revenue_minor FROM admin_sales_daily "
                "WHERE day > now() - make_interval(days => %s) ORDER BY day",
                (days,),
            )
            return await cur.fetchall()

    @router.get("/reports/payments")
    async def payments_report(
        admin: Admin = need["report.payments"], days: Annotated[int, Query(ge=1, le=730)] = 30
    ) -> list[dict[str, Any]]:
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT provider, status::text, currency, count(*)::int AS count, "
                "sum(amount_minor)::bigint AS amount_minor, "
                "sum(refunded_minor)::bigint AS refunded_minor FROM payments "
                "WHERE created_at > now() - make_interval(days => %s) "
                "GROUP BY provider, status, currency ORDER BY provider, status",
                (days,),
            )
            return await cur.fetchall()

    @router.get("/reports/usage")
    async def usage(admin: Admin = need["report.usage"]) -> dict[str, Any]:
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT plan_code, status::text, license_count::int FROM admin_license_stats "
                "ORDER BY plan_code, status"
            )
            by_plan = await cur.fetchall()
            cur = await conn.execute(
                "SELECT platform::text, active_devices::int, active_customers::int FROM "
                "admin_active_usage"
            )
            active = await cur.fetchall()
        return {"licenses": by_plan, "active": active}

    # --- Denetim kaydı -------------------------------------------------------------------------

    @router.get("/audit")
    async def audit_log(
        admin: Admin = need["audit.read"],
        action: Annotated[str | None, Query(max_length=80, pattern=r"^[a-z_.]+$")] = None,
        actor_type: Annotated[str | None, Query(pattern=r"^[a-z_]+$")] = None,
        limit: Limit = 100,
        offset: Offset = 0,
    ) -> list[dict[str, Any]]:
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT id, occurred_at, actor_type::text, actor_id, action, target_type, "
                "target_id, "
                "host(ip) AS ip, details FROM audit_log "
                "WHERE (%s::text IS NULL OR action LIKE %s || '%%') "
                "AND (%s::text IS NULL OR actor_type::text = %s) "
                "ORDER BY id DESC LIMIT %s OFFSET %s",
                (action, action, actor_type, actor_type, limit, offset),
            )
            return await cur.fetchall()

    @router.get("/audit/verify")
    async def audit_verify(admin: Admin = need["audit.read"]) -> dict[str, Any]:
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT audit_log_verify() AS broken, count(*)::int AS total FROM audit_log"
            )
            row = await cur.fetchone()
        broken = row["broken"] if row else None
        return {
            "intact": broken is None,
            "first_broken_id": broken,
            "entries": row["total"] if row else 0,
        }

    return router
