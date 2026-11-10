"""Ödeme uç noktaları (Aşama 17).

Müşteri (çerezli, köken denetimli):
    GET  /v1/payments/status            satış açık mı, test modu mu (herkese açık)
    GET  /v1/legal/seller               satıcı bilgileri (yasal metinler için, herkese açık)
    POST /v1/checkout                   sipariş + sağlayıcı ödeme sayfası (isteğe bağlı kupon)
    POST /v1/coupons/check              kupon önizlemesi (sipariş açmaz)
    GET  /v1/me/orders                  siparişlerim
    GET  /v1/me/orders/{order_no}       sipariş durumu (sonuç sayfası)

Sağlayıcı (çerez yok, imza ile):
    POST /v1/payments/webhooks/{provider}   bildirim (PayTR, simülatör)
    POST /v1/payments/return/iyzico         tarayıcı dönüşü → sonuç sağlayıcıdan sorgulanır

Yalnızca geliştirme/test:
    GET  /v1/payments/simulator/session, POST /v1/payments/simulator/complete

Yönetici:
    GET  /admin/v1/orders/{order_id}            (order.read)
    POST /admin/v1/orders/{order_id}/refund     (payment.refund, güncel TOTP)
    POST /admin/v1/orders/{order_id}/reconcile  (payment.read)
"""

from __future__ import annotations

import uuid
from typing import Any, Literal
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field

from ati_cloud.accounts import (
    SlidingWindowLimiter,
    check_origin,
    client_ip,
    customer_dependency,
    limited,
)
from ati_cloud.admin.context import Admin, AdminContext
from ati_cloud.payments.service import BillingDetails, PaymentError, Payments

MAX_WEBHOOK_BYTES = 64 * 1024


def _http(exc: PaymentError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


class Billing(BaseModel):
    full_name: str = Field(min_length=3, max_length=120)
    phone: str = Field(pattern=r"^\+?[0-9 ()-]{10,20}$")
    address: str = Field(min_length=10, max_length=400)
    city: str = Field(min_length=2, max_length=50)
    country: str = Field(default="Türkiye", min_length=2, max_length=50)
    tax_id: str | None = Field(default=None, pattern=r"^(\d{10,11})?$")  # TCKN / VKN
    company: str | None = Field(default=None, max_length=200)
    tax_office: str | None = Field(default=None, max_length=120)


class CheckoutBody(BaseModel):
    plan_code: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    billing: Billing
    accept_preinfo: bool  # ön bilgilendirme formu
    accept_contract: bool  # mesafeli satış sözleşmesi
    accept_immediate_delivery: bool  # dijital içerik anında teslim → cayma hakkı istisnası
    coupon: str | None = Field(default=None, max_length=40)


class CouponCheck(BaseModel):
    plan_code: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    code: str = Field(min_length=1, max_length=40)


class SimulateBody(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    outcome: Literal["success", "failure"]


class RefundBody(BaseModel):
    amount_minor: int | None = Field(default=None, gt=0)  # boş = kalan tutarın tamamı
    reason: str = Field(min_length=3, max_length=300)
    license_action: Literal["cancel", "keep", "manual_review"] = "cancel"
    code: str | None = Field(default=None, max_length=10)


def _order_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Sipariş bulunamadı") from exc


ORDER_COLUMNS = (
    "o.order_no, o.status::text AS status, o.total_minor, o.discount_minor, o.coupon_code, "
    "o.currency, o.created_at, o.paid_at, "
    "o.fulfilled_at, o.review_reason IS NOT NULL AS under_review, "
    "CASE WHEN o.status = 'pending' THEN o.checkout_url END AS checkout_url, "
    "(SELECT p.name FROM order_items i JOIN license_plans p ON p.code = i.plan_code "
    " WHERE i.order_id = o.id LIMIT 1) AS plan_name, "
    "COALESCE((SELECT json_agg(l.key_hint ORDER BY l.serial) FROM licenses l "
    " JOIN order_items i ON i.id = l.order_item_id WHERE i.order_id = o.id), '[]') AS licenses, "
    "(SELECT invoice_no FROM invoices v WHERE v.order_id = o.id) AS invoice_no"
)


def create_payments_router(payments: Payments) -> APIRouter:
    settings, db = payments.settings, payments.db
    router = APIRouter(prefix="/v1")
    current_customer = customer_dependency(db)
    customer_dep = Depends(current_customer)
    checkout_limit = SlidingWindowLimiter(10, 3600)
    # Kupon kodu tahminini zorlaştırmak için müşteri ve IP başına sınır.
    coupon_customer = SlidingWindowLimiter(20, 3600)
    coupon_ip = SlidingWindowLimiter(60, 3600)
    simulate_limit = SlidingWindowLimiter(30, 3600)
    invalid_webhook_ip = SlidingWindowLimiter(60, 60)

    @router.get("/payments/status")
    async def status() -> dict[str, Any]:
        return await payments.status()

    @router.get("/legal/seller")
    async def seller() -> dict[str, Any]:
        """Satıcı bilgileri (ön bilgilendirme formu ve sözleşmede yasal olarak yer alır)."""
        async with db.connection() as conn:
            cur = await conn.execute("SELECT value FROM system_settings WHERE key = 'company'")
            row = await cur.fetchone()
        info = dict(row["value"]) if row else {}
        keys = ("legal_name", "address", "tax_office", "tax_number", "mersis", "kep", "email",
                "phone")  # fmt: skip
        return {k: str(info.get(k, "")) for k in keys}

    @router.post("/checkout")
    async def checkout(
        body: CheckoutBody, request: Request, customer: dict[str, Any] = customer_dep
    ) -> dict[str, Any]:
        check_origin(settings, request)
        limited(checkout_limit, str(customer["id"]))
        if not (body.accept_preinfo and body.accept_contract and body.accept_immediate_delivery):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "legal_required",
                    "message": "Devam etmek için ön bilgilendirme formunu, mesafeli satış "
                    "sözleşmesini ve anında teslim onayını kabul edin.",
                },
            )
        billing = BillingDetails(**body.billing.model_dump())
        try:
            return await payments.checkout(
                customer, body.plan_code, billing, client_ip(request), coupon=body.coupon or None
            )
        except PaymentError as exc:
            raise _http(exc) from exc

    @router.post("/coupons/check")
    async def check_coupon(
        body: CouponCheck, request: Request, customer: dict[str, Any] = customer_dep
    ) -> dict[str, Any]:
        check_origin(settings, request)
        limited(coupon_customer, str(customer["id"]))
        limited(coupon_ip, client_ip(request))
        try:
            return await payments.quote(customer, body.plan_code, body.code)
        except PaymentError as exc:
            raise _http(exc) from exc

    @router.get("/me/orders")
    async def my_orders(customer: dict[str, Any] = customer_dep) -> list[dict[str, Any]]:
        async with db.connection() as conn:
            cur = await conn.execute(
                f"SELECT {ORDER_COLUMNS} FROM orders o WHERE o.customer_id = %s "  # noqa: S608
                "ORDER BY o.created_at DESC LIMIT 50",
                (customer["id"],),
            )
            return await cur.fetchall()

    @router.get("/me/orders/{order_no}")
    async def my_order(order_no: int, customer: dict[str, Any] = customer_dep) -> dict[str, Any]:
        async with db.connection() as conn:
            cur = await conn.execute(
                f"SELECT {ORDER_COLUMNS} FROM orders o "  # noqa: S608
                "WHERE o.order_no = %s AND o.customer_id = %s",
                (order_no, customer["id"]),
            )
            row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Sipariş bulunamadı")
        return row

    @router.post("/payments/webhooks/{provider}")
    async def webhook(provider: str, request: Request) -> Response:
        ip = client_ip(request)
        body = await request.body()
        if len(body) > MAX_WEBHOOK_BYTES:
            return Response(status_code=413, content="too large", media_type="text/plain")
        if not invalid_webhook_ip.allow(ip):
            return Response(status_code=429, content="slow down", media_type="text/plain")
        headers = {k.lower(): v for k, v in request.headers.items()}
        try:
            reply = await payments.handle_webhook(provider, headers, body, ip)
        except PaymentError as exc:
            raise _http(exc) from exc
        return Response(status_code=reply.status, content=reply.body, media_type=reply.media_type)

    @router.post("/payments/return/iyzico")
    async def iyzico_return(request: Request) -> RedirectResponse:
        """iyzico tarayıcıyı ``token`` alanlı form gönderimiyle döndürür."""
        fallback = f"{settings.public_web_url.rstrip('/')}/odeme/sonuc"
        body = await request.body()
        token = parse_qs(body[:4096].decode("utf-8", "replace")).get("token", [""])[0]
        if not 10 <= len(token) <= 200:
            return RedirectResponse(fallback, status_code=303)
        try:
            target = await payments.iyzico_return(token)
        except PaymentError:
            target = fallback
        return RedirectResponse(target, status_code=303)

    @router.get("/payments/simulator/session")
    async def simulator_session(
        token: str, customer: dict[str, Any] = customer_dep
    ) -> dict[str, Any]:
        try:
            order = await payments.simulator_order(customer["id"], token)
        except PaymentError as exc:
            raise _http(exc) from exc
        return {k: v for k, v in order.items() if k != "id"}

    @router.post("/payments/simulator/complete")
    async def simulator_complete(
        body: SimulateBody, request: Request, customer: dict[str, Any] = customer_dep
    ) -> dict[str, Any]:
        check_origin(settings, request)
        limited(simulate_limit, str(customer["id"]))
        try:
            order_no = await payments.simulate(
                customer["id"], body.token, body.outcome, client_ip(request)
            )
        except PaymentError as exc:
            raise _http(exc) from exc
        return {"order_no": order_no, "redirect_url": payments.result_url(order_no)}

    return router


def create_admin_payments_router(ctx: AdminContext, payments: Payments) -> APIRouter:
    router = APIRouter(prefix="/admin/v1")
    order_read = ctx.depends("order.read")
    payment_read = ctx.depends("payment.read")
    payment_refund = ctx.depends("payment.refund")

    @router.get("/orders/{order_id}")
    async def order_detail(order_id: str, admin: Admin = order_read) -> dict[str, Any]:
        oid = _order_uuid(order_id)
        async with ctx.db.connection() as conn:
            cur = await conn.execute(
                "SELECT o.id::text, o.order_no, o.status::text AS status, o.currency, "
                "o.subtotal_minor, o.discount_minor, o.tax_minor, o.total_minor, "
                "o.payment_provider, o.review_reason, o.billing_snapshot, o.created_at, "
                "o.paid_at, o.fulfilled_at, o.cancelled_at, c.id::text AS customer_id, "
                "c.email AS customer_email FROM orders o JOIN customers c ON c.id = o.customer_id "
                "WHERE o.id = %s",
                (oid,),
            )
            order = await cur.fetchone()
            if order is None:
                raise HTTPException(status_code=404, detail="Sipariş bulunamadı")
            cur = await conn.execute(
                "SELECT i.plan_code, p.name AS plan_name, i.quantity, i.unit_price_minor, "
                "i.line_total_minor FROM order_items i "
                "JOIN license_plans p ON p.code = i.plan_code WHERE i.order_id = %s",
                (oid,),
            )
            order["items"] = await cur.fetchall()
            cur = await conn.execute(
                "SELECT id::text, provider, provider_payment_id, status::text AS status, "
                "amount_minor, refunded_minor, currency, created_at, succeeded_at "
                "FROM payments WHERE order_id = %s ORDER BY created_at",
                (oid,),
            )
            order["payments"] = await cur.fetchall()
            cur = await conn.execute(
                "SELECT r.id::text, r.amount_minor, r.reason, r.status, r.license_action, "
                "r.created_at, r.completed_at, r.last_error, a.email AS requested_by "
                "FROM refunds r JOIN payments p ON p.id = r.payment_id "
                "LEFT JOIN admin_users a ON a.id = r.requested_by WHERE p.order_id = %s "
                "ORDER BY r.created_at",
                (oid,),
            )
            order["refunds"] = await cur.fetchall()
            cur = await conn.execute(
                "SELECT l.id::text, l.key_hint, l.status::text AS status, l.expires_at "
                "FROM licenses l JOIN order_items i ON i.id = l.order_item_id "
                "WHERE i.order_id = %s ORDER BY l.serial",
                (oid,),
            )
            order["licenses"] = await cur.fetchall()
            cur = await conn.execute(
                "SELECT invoice_no, issued_at, provider, external_id FROM invoices "
                "WHERE order_id = %s",
                (oid,),
            )
            order["invoice"] = await cur.fetchone()
        return order

    @router.post("/orders/{order_id}/refund")
    async def refund(
        order_id: str, body: RefundBody, request: Request, admin: Admin = payment_refund
    ) -> dict[str, Any]:
        oid = _order_uuid(order_id)
        async with ctx.db.connection() as conn:
            await ctx.step_up(conn, admin, body.code)
        try:
            return await payments.refund(
                admin_id=admin.id,
                order_id=oid,
                amount_minor=body.amount_minor,
                reason=body.reason,
                license_action=body.license_action,
                ip=client_ip(request),
            )
        except PaymentError as exc:
            raise _http(exc) from exc

    @router.post("/orders/{order_id}/reconcile")
    async def reconcile(order_id: str, admin: Admin = payment_read) -> dict[str, Any]:
        try:
            return await payments.reconcile(_order_uuid(order_id))
        except PaymentError as exc:
            raise _http(exc) from exc

    return router
