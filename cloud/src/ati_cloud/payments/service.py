"""Ödeme ve lisans teslimi (Aşama 17).

Akış (docs/04 §1.4):

1. Müşteri paketi seçer; ön bilgilendirme formu, mesafeli satış sözleşmesi ve anında teslim
   onayı alınır → ``pending`` sipariş → sağlayıcının ödeme sayfası.
2. Sağlayıcı sonucu **imzalı** bildirimle (PayTR, simülatör) ya da imzalı sunucu isteğiyle
   sorgulanan sonuçla (iyzico) bildirir. İmzası doğrulanamayan istek hiçbir şeyi değiştirmez.
3. Olay ``payment_webhook_events``'e (sağlayıcı, olay kimliği) tekil olarak yazılır; aynı olay
   ikinci kez işlenmez. Sipariş satırı kilitlenir; ödeme kaydı → lisans (havuzdan
   ``SKIP LOCKED`` ya da yeni) → e-posta kuyruğu (yalnızca lisans kimliği) → fatura kaydı →
   ``fulfilled``. Tamamı tek işlemde; yarıda kalırsa hiçbiri yazılmaz ve sağlayıcı yeniden dener.
4. Tutar/para birimi uyuşmazlığı, aynı siparişe ikinci tahsilat ya da sağlayıcı uyuşmazlığında
   otomatik teslim yapılmaz; sipariş yönetici incelemesine düşer (``review_reason``).

Canlı ödeme iki kilitlidir (G3): dağıtım ayarı ``ATI_PAYMENTS_LIVE_ALLOWED`` ve paneldeki canlı mod.
Üretim ortamında test modunda satış açılmaz (test kartıyla gerçek lisans alınamasın diye).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import psycopg
from psycopg import errors as pg_errors
from psycopg.types.json import Jsonb

from ati_cloud.accounts import Database
from ati_cloud.admin.security import SecretBox
from ati_cloud.admin.settings_api import load_payment_secrets
from ati_cloud.config import CloudSettings
from ati_cloud.licensing.service import Licensing
from ati_cloud.payments import campaign
from ati_cloud.payments.providers import (
    Buyer,
    CheckoutRequest,
    InvalidSignature,
    IyzicoProvider,
    LemonSqueezyProvider,
    PaymentEvent,
    PaytrProvider,
    Provider,
    ProviderError,
    SimulatorProvider,
    WebhookReply,
)

log = logging.getLogger(__name__)
Conn = psycopg.AsyncConnection[dict[str, Any]]

# Yasal metinlerin sürümü: kabul kaydıyla birlikte siparişte saklanır.
LEGAL_VERSION = "2026-11-taslak-1"
CLOSED_MESSAGE = "Çevrim içi ödeme şu anda kapalı. Lütfen daha sonra tekrar deneyin."
WEBHOOK_PROVIDERS = ("paytr", "lemonsqueezy", "simulator")
PROVIDER_LABELS = {
    "paytr": "PayTR",
    "iyzico": "iyzico",
    "lemonsqueezy": "Lemon Squeezy",
    "simulator": "Test simülatörü",
}
PENDING_TRIAL_WINDOW_H = 2
# Kupon kullanımı sayılırken ödemesi bekleyen siparişlerin hak tükettiği süre.
PENDING_COUPON_WINDOW_H = 2
COUPON_CODE = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,31}$")
COUPON_INVALID = "Kupon kodu geçersiz veya süresi dolmuş."


class PaymentError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PaymentConfig:
    provider: str = "none"
    mode: str = "test"
    public: dict[str, str] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BillingDetails:
    full_name: str
    phone: str
    address: str
    city: str
    country: str
    tax_id: str | None = None
    company: str | None = None
    tax_office: str | None = None


@dataclass(frozen=True)
class AppliedCoupon:
    code: str
    discount_minor: int
    total_minor: int


def normalize_coupon(raw: str) -> str:
    """Kullanıcının yazdığı kod: boşluklar atılır, büyük harfe çevrilir (İ/ı gibi harfler dahil)."""
    return "".join(raw.split()).upper().replace("İ", "I")


def coupon_discount(coupon: dict[str, Any], price_minor: int, currency: str) -> int:
    """Kuponun bu fiyata indirimi (kuruş). Yüzde aşağı yuvarlanır; indirim fiyatı aşamaz."""
    if coupon["percent_off"] is not None:
        return price_minor * int(coupon["percent_off"]) // 100
    if coupon["currency"] != currency:
        raise PaymentError(
            409, "coupon_currency", "Bu kupon bu paketin para biriminde geçerli değil."
        )
    return min(int(coupon["amount_off_minor"]), price_minor)


def invoice_number(order_no: int, when: datetime) -> str:
    """Kayıt numarası (16 karakter, e-Arşiv biçimine uygun: 3 harf + yıl + 9 hane)."""
    return f"ATI{when.year}{order_no:09d}"


def _order_ref_clause(ref: str) -> tuple[str, Any]:
    match = re.fullmatch(r"ATI(\d{6,12})", ref)
    if match:
        return "order_no = %s", int(match.group(1))
    try:
        return "id = %s", uuid.UUID(ref)
    except ValueError:
        return "false AND id = %s", uuid.UUID(int=0)


async def _audit(
    conn: Conn,
    *,
    actor_type: str,
    actor_id: Any,
    action: str,
    target_id: Any,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
    target_type: str = "order",
) -> None:
    await conn.execute(
        "INSERT INTO audit_log (actor_type, actor_id, action, target_type, target_id, ip, details) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            actor_type,
            None if actor_id is None else str(actor_id),
            action,
            target_type,
            None if target_id is None else str(target_id),
            ip,
            Jsonb(details or {}),
        ),
    )


def _one(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        raise RuntimeError("Beklenen satır dönmedi")
    return row


async def _act_as(conn: Conn, actor_type: str, actor_id: str) -> None:
    await conn.execute("SELECT set_config('ati.actor_type', %s, true)", (actor_type,))
    await conn.execute("SELECT set_config('ati.actor_id', %s, true)", (actor_id,))


@dataclass
class Payments:
    settings: CloudSettings
    db: Database
    licensing: Licensing | None
    box: SecretBox | None
    simulator: SimulatorProvider
    # Testlerde sağlayıcı HTTP isteklerini yakalamak için (ör. httpx.MockTransport).
    transports: dict[str, httpx.AsyncBaseTransport] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        settings: CloudSettings,
        db: Database,
        licensing: Licensing | None,
        box: SecretBox | None,
    ) -> Payments:
        # Simülatör imza anahtarı: birden çok süreç aynı anahtarı üretsin diye KEK'ten türetilir.
        base = (
            settings.admin_secret_kek.get_secret_value().encode()
            if settings.admin_secret_kek is not None
            else secrets.token_bytes(32)
        )
        sim_secret = hmac.new(base, b"ati-payment-simulator-v1", hashlib.sha256).digest()
        return cls(
            settings=settings,
            db=db,
            licensing=licensing,
            box=box,
            simulator=SimulatorProvider(sim_secret, settings.public_web_url.rstrip("/")),
        )

    # --- Yapılandırma -----------------------------------------------------------------------

    @property
    def production_like(self) -> bool:
        return self.settings.environment in ("staging", "production")

    async def load_config(self, conn: Conn) -> PaymentConfig:
        if self.box is None:
            return PaymentConfig()
        data = await load_payment_secrets(conn, self.box)
        return PaymentConfig(
            provider=data["provider"],
            mode=data["mode"],
            public=dict(data["public"]),
            secrets=dict(data["secrets"]),
        )

    def provider(self, cfg: PaymentConfig) -> Provider:
        """Yapılandırmadan sağlayıcı. Eksik anahtar ya da izin verilmeyen durumda ödeme kapalı."""
        name = cfg.provider
        if name == "simulator" and not self.production_like:
            return self.simulator
        test_mode = cfg.mode != "live"
        if name == "paytr":
            merchant_id = cfg.public.get("merchant_id", "")
            key, salt = cfg.secrets.get("merchant_key"), cfg.secrets.get("merchant_salt")
            if merchant_id and key and salt:
                return PaytrProvider(
                    merchant_id=merchant_id,
                    merchant_key=key,
                    merchant_salt=salt,
                    test_mode=test_mode,
                    transport=self.transports.get("paytr"),
                )
        if name == "iyzico":
            api_key, secret_key = cfg.secrets.get("api_key"), cfg.secrets.get("secret_key")
            if api_key and secret_key:
                return IyzicoProvider(
                    api_key=api_key,
                    secret_key=secret_key,
                    test_mode=test_mode,
                    transport=self.transports.get("iyzico"),
                )
        if name == "lemonsqueezy":
            api_key, signing = cfg.secrets.get("api_key"), cfg.secrets.get("signing_secret")
            store_id, variant_id = cfg.public.get("store_id", ""), cfg.public.get("variant_id", "")
            if api_key and signing and store_id.isdigit() and variant_id.isdigit():
                return LemonSqueezyProvider(
                    api_key=api_key,
                    signing_secret=signing,
                    store_id=store_id,
                    variant_id=variant_id,
                    test_mode=test_mode,
                    transport=self.transports.get("lemonsqueezy"),
                )
        raise PaymentError(503, "payments_closed", CLOSED_MESSAGE)

    def sales_open(self, cfg: PaymentConfig) -> bool:
        if cfg.provider == "none" or self.licensing is None:
            return False
        if cfg.mode == "live" and not self.settings.payments_live_allowed:
            return False  # panelde canlı görünse de dağıtım kilidi (G3) kapalı
        if self.settings.environment == "production" and cfg.mode != "live":
            return False  # üretimde test modunda satış yok
        try:
            self.provider(cfg)
        except PaymentError:
            return False
        return True

    async def status(self) -> dict[str, Any]:
        async with self.db.connection() as conn:
            cfg = await self.load_config(conn)
        open_ = self.sales_open(cfg)
        return {
            "open": open_,
            "test_mode": open_ and cfg.mode != "live",
            "provider": PROVIDER_LABELS.get(cfg.provider) if open_ else None,
            "legal_version": LEGAL_VERSION,
        }

    # --- Ödeme başlatma ----------------------------------------------------------------------

    async def apply_coupon(
        self, conn: Conn, raw_code: str, plan: dict[str, Any], customer_id: Any, *, lock: bool
    ) -> AppliedCoupon:
        """Kuponu pakete uygular; uygun değilse açıklayıcı ``PaymentError``.

        ``lock`` ile (ödeme başlatırken) aynı koda eşzamanlı başvurular sıralanır; böylece kullanım
        sınırı aşılamaz.
        """
        code = normalize_coupon(raw_code)
        if not COUPON_CODE.fullmatch(code):
            raise PaymentError(404, "coupon_invalid", COUPON_INVALID)
        if lock:
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext('ati.coupon:' || %s))", (code,)
            )
        cur = await conn.execute(
            "SELECT code, percent_off, amount_off_minor, currency, plan_codes, max_redemptions "
            "FROM coupons WHERE code = %s AND is_active "
            "AND (valid_from IS NULL OR valid_from <= now()) "
            "AND (valid_until IS NULL OR valid_until > now())",
            (code,),
        )
        coupon = await cur.fetchone()
        if coupon is None:
            raise PaymentError(404, "coupon_invalid", COUPON_INVALID)
        price = int(plan["price_minor"])
        if plan["is_trial"] or price == 0:
            raise PaymentError(
                409, "coupon_not_applicable", "Kupon ücretsiz paketlerde kullanılamaz."
            )
        if coupon["plan_codes"] and plan["code"] not in coupon["plan_codes"]:
            raise PaymentError(
                409, "coupon_not_applicable", "Bu kupon seçtiğiniz pakette geçerli değil."
            )
        cur = await conn.execute(
            "SELECT count(*) FILTER (WHERE customer_id = %s)::int AS mine, count(*)::int AS total "
            "FROM orders WHERE coupon_code = %s AND (status IN ('paid', 'fulfilled') "
            "OR (status = 'pending' AND created_at > now() - make_interval(hours => %s)))",
            (customer_id, code, PENDING_COUPON_WINDOW_H),
        )
        used = _one(await cur.fetchone())
        if used["mine"]:
            raise PaymentError(409, "coupon_used", "Bu kuponu daha önce kullandınız.")
        if coupon["max_redemptions"] is not None and used["total"] >= coupon["max_redemptions"]:
            raise PaymentError(409, "coupon_exhausted", "Bu kuponun kullanım sınırı doldu.")
        discount = coupon_discount(coupon, price, str(plan["currency"]))
        return AppliedCoupon(code=code, discount_minor=discount, total_minor=price - discount)

    async def quote(self, customer: dict[str, Any], plan_code: str, coupon: str) -> dict[str, Any]:
        """Ödeme sayfasında kupon önizlemesi (sipariş açmaz)."""
        async with self.db.connection() as conn:
            plan = await self._plan(conn, plan_code)
            applied = await self.apply_coupon(conn, coupon, plan, customer["id"], lock=False)
        return {
            "code": applied.code,
            "list_price_minor": plan["list_price_minor"],
            "campaign_percent": plan["campaign_percent"],
            "subtotal_minor": int(plan["price_minor"]),
            "discount_minor": applied.discount_minor,
            "total_minor": applied.total_minor,
            "currency": plan["currency"],
        }

    @staticmethod
    async def _plan(conn: Conn, plan_code: str) -> dict[str, Any]:
        cur = await conn.execute(
            "SELECT code, name, price_minor, currency, is_trial, duration_days, device_limit "
            "FROM license_plans WHERE code = %s AND is_active FOR SHARE",
            (plan_code,),
        )
        plan = await cur.fetchone()
        if plan is None:
            raise PaymentError(404, "plan_unavailable", "Bu paket şu anda satışta değil.")
        # Genel indirim kampanyası (varsa) paket fiyatına uygulanır; kupon bunun üzerine gelir.
        return campaign.apply_to_plan(plan, await campaign.active(conn))

    async def checkout(
        self,
        customer: dict[str, Any],
        plan_code: str,
        billing: BillingDetails,
        ip: str,
        coupon: str | None = None,
    ) -> dict[str, Any]:
        if customer.get("email_verified_at") is None:
            raise PaymentError(
                403, "email_unverified", "Satın almadan önce e-posta adresinizi doğrulayın."
            )
        customer_id = customer["id"]
        async with self.db.connection() as conn:
            cfg = await self.load_config(conn)
            plan = await self._plan(conn, plan_code)
            price = int(plan["price_minor"])
            applied = (
                await self.apply_coupon(conn, coupon, plan, customer_id, lock=True)
                if coupon
                else None
            )
            total = applied.total_minor if applied else price
            # %100 kupon ya da ücretsiz paket: sağlayıcıya gidilmez, hemen teslim edilir.
            free = total == 0
            if self.licensing is None or (not free and not self.sales_open(cfg)):
                raise PaymentError(503, "payments_closed", CLOSED_MESSAGE)
            provider = None if free else self.provider(cfg)
            if plan["is_trial"]:
                await self._check_trial(conn, customer_id)
            snapshot = {
                "billing": {k: v for k, v in billing.__dict__.items() if v},
                "email": customer["email"],
                "plan": {
                    "code": plan["code"],
                    "name": plan["name"],
                    "duration_days": plan["duration_days"],
                    "device_limit": plan["device_limit"],
                },
                "legal": {
                    "version": LEGAL_VERSION,
                    "preinfo_accepted": True,
                    "contract_accepted": True,
                    "immediate_delivery_accepted": True,
                    "accepted_at": datetime.now(UTC).isoformat(),
                    "ip": ip,
                },
                "mode": "free" if free else cfg.mode,
            }
            if plan["campaign_percent"]:
                snapshot["campaign"] = {
                    "percent": plan["campaign_percent"],
                    "label": plan["campaign_label"],
                    "list_price_minor": plan["list_price_minor"],
                }
            if applied:
                snapshot["coupon"] = {
                    "code": applied.code,
                    "discount_minor": applied.discount_minor,
                }
            cur = await conn.execute(
                "INSERT INTO orders (customer_id, currency, subtotal_minor, discount_minor, "
                "total_minor, payment_provider, billing_snapshot, coupon_code, campaign_percent) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "RETURNING id, order_no, customer_id, total_minor, currency",
                (
                    customer_id,
                    plan["currency"],
                    price,
                    applied.discount_minor if applied else 0,
                    total,
                    "free" if free else cfg.provider,
                    Jsonb(snapshot),
                    applied.code if applied else None,
                    plan["campaign_percent"],
                ),
            )
            order = _one(await cur.fetchone())
            await conn.execute(
                "INSERT INTO order_items (order_id, plan_code, quantity, unit_price_minor, "
                "line_total_minor) VALUES (%s, %s, 1, %s, %s)",
                (order["id"], plan["code"], plan["price_minor"], plan["price_minor"]),
            )
            await _audit(
                conn, actor_type="customer", actor_id=customer_id, action="order.created",
                target_id=order["id"], ip=ip,
                details={"order_no": order["order_no"], "plan": plan["code"],
                         "total_minor": total, "currency": plan["currency"],
                         "coupon": applied.code if applied else None,
                         "provider": "free" if free else cfg.provider, "mode": snapshot["mode"]},
            )  # fmt: skip
            if free:
                await _act_as(conn, "customer", str(customer_id))
                await conn.execute(
                    "UPDATE orders SET status = 'paid', paid_at = now() WHERE id = %s",
                    (order["id"],),
                )
                await self._fulfill(conn, order, actor=("customer", customer_id))
        result_url = self.result_url(order["order_no"])
        if provider is None:
            return {"order_no": order["order_no"], "redirect_url": result_url}

        request = CheckoutRequest(
            order_id=str(order["id"]),
            order_no=int(order["order_no"]),
            amount_minor=int(order["total_minor"]),
            currency=str(order["currency"]),
            item_name=str(plan["name"]),
            plan_code=str(plan["code"]),
            buyer=Buyer(
                customer_id=str(customer_id),
                email=str(customer["email"]),
                full_name=billing.full_name,
                phone=billing.phone,
                address=billing.address,
                city=billing.city,
                country=billing.country,
                ip=ip,
                tax_id=billing.tax_id,
            ),
            success_url=result_url,
            fail_url=result_url,
            callback_url=f"{self.settings.public_api_url.rstrip('/')}/v1/payments/return/{cfg.provider}",
        )
        try:
            session = await provider.create_checkout(request)
        except ProviderError as exc:
            log.warning("Ödeme oturumu açılamadı (sipariş %s): %s", order["order_no"], exc)
            async with self.db.connection() as conn:
                await conn.execute(
                    "UPDATE orders SET status = 'failed' WHERE id = %s AND status = 'pending'",
                    (order["id"],),
                )
                await _audit(
                    conn, actor_type="system", actor_id=None, action="payment.checkout_failed",
                    target_id=order["id"], details={"provider": cfg.provider, "error": str(exc)},
                )  # fmt: skip
            raise PaymentError(
                502, "provider_error", "Ödeme sayfası açılamadı. Biraz sonra tekrar deneyin."
            ) from exc
        async with self.db.connection() as conn:
            await conn.execute(
                "UPDATE orders SET provider_checkout_id = %s, checkout_url = %s WHERE id = %s",
                (session.provider_ref, session.redirect_url, order["id"]),
            )
        return {"order_no": order["order_no"], "redirect_url": session.redirect_url}

    def result_url(self, order_no: int) -> str:
        return f"{self.settings.public_web_url.rstrip('/')}/odeme/sonuc?siparis={order_no}"

    @staticmethod
    async def _check_trial(conn: Conn, customer_id: Any) -> None:
        """Deneme paketi müşteri başına bir kez (eşzamanlı iki istek de aşamaz)."""
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext('ati.trial:' || %s::text))", (customer_id,)
        )
        cur = await conn.execute(
            "SELECT 1 FROM licenses l JOIN license_plans p ON p.code = l.plan_code "
            "WHERE l.customer_id = %s AND p.is_trial "
            "UNION ALL "
            "SELECT 1 FROM orders o JOIN order_items i ON i.order_id = o.id "
            "JOIN license_plans p ON p.code = i.plan_code WHERE o.customer_id = %s AND p.is_trial "
            "AND (o.status IN ('paid', 'fulfilled') OR (o.status = 'pending' "
            "AND o.created_at > now() - make_interval(hours => %s))) LIMIT 1",
            (customer_id, customer_id, PENDING_TRIAL_WINDOW_H),
        )
        if await cur.fetchone():
            raise PaymentError(
                409, "trial_used", "Deneme paketi her hesap için bir kez alınabilir."
            )

    # --- Sağlayıcı bildirimleri ----------------------------------------------------------------

    async def handle_webhook(
        self, provider_name: str, headers: dict[str, str], body: bytes, ip: str
    ) -> WebhookReply:
        if provider_name not in WEBHOOK_PROVIDERS or (
            provider_name == "simulator" and self.production_like
        ):
            raise PaymentError(404, "not_found", "Bulunamadı")
        if provider_name == "simulator":
            parser: Any = self.simulator
        else:
            async with self.db.connection() as conn:
                cfg = await self.load_config(conn)
            try:
                parser = self.provider(cfg) if cfg.provider == provider_name else None
            except PaymentError:
                parser = None
        try:
            if parser is None:
                raise InvalidSignature("Sağlayıcı yapılandırılmamış; imza doğrulanamaz")
            event: PaymentEvent = parser.parse_webhook(headers, body)
        except (InvalidSignature, ValueError, KeyError, TypeError) as exc:
            await self._record_invalid(provider_name, body, ip, str(exc))
            return WebhookReply(status=400, body="invalid notification")
        if event.event_type == "ignored":
            return WebhookReply()  # imzası doğru ama bizi ilgilendirmeyen olay
        await self.process(provider_name, event)
        return WebhookReply()

    async def _record_invalid(self, provider_name: str, body: bytes, ip: str, error: str) -> None:
        digest = hashlib.sha256(body).hexdigest()
        async with self.db.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO payment_webhook_events (provider, provider_event_id, event_type, "
                "signature_valid, payload, last_error) VALUES (%s, %s, 'invalid', false, %s, %s) "
                "ON CONFLICT (provider, provider_event_id) DO UPDATE "
                "SET attempts = payment_webhook_events.attempts + 1 RETURNING attempts",
                (
                    provider_name,
                    f"invalid:{digest[:40]}",
                    Jsonb({"sha256": digest, "size": len(body), "ip": ip}),
                    error[:300],
                ),
            )
            row = await cur.fetchone()
            if row is not None and row["attempts"] == 0:
                await _audit(
                    conn, actor_type="payment_webhook", actor_id=provider_name,
                    action="payment.webhook_rejected", target_type="webhook", target_id=None,
                    ip=ip, details={"sha256": digest, "reason": error[:200]},
                )  # fmt: skip

    async def process(self, provider_name: str, event: PaymentEvent) -> dict[str, Any]:
        """Doğrulanmış olayı idempotent olarak uygular."""
        async with self.db.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO payment_webhook_events (provider, provider_event_id, event_type, "
                "signature_valid, payload) VALUES (%s, %s, %s, true, %s) "
                "ON CONFLICT (provider, provider_event_id) DO UPDATE "
                "SET attempts = payment_webhook_events.attempts + 1 "
                "RETURNING id, processed_at",
                (
                    provider_name,
                    event.event_id,
                    event.event_type,
                    Jsonb({**event.raw, "order_ref": event.order_ref}),
                ),
            )
            row = _one(await cur.fetchone())
        if row["processed_at"] is not None:
            return {"result": "duplicate"}
        try:
            async with self.db.connection() as conn:
                await _act_as(conn, "payment_webhook", f"{provider_name}:{event.event_id}"[:200])
                result = await self._apply(conn, provider_name, event)
                await conn.execute(
                    "UPDATE payment_webhook_events SET processed_at = now(), last_error = NULL "
                    "WHERE id = %s",
                    (row["id"],),
                )
        except Exception as exc:
            async with self.db.connection() as conn:
                await conn.execute(
                    "UPDATE payment_webhook_events SET last_error = %s WHERE id = %s",
                    (f"{type(exc).__name__}: {exc}"[:500], row["id"]),
                )
            raise
        return result

    async def _apply(self, conn: Conn, provider_name: str, event: PaymentEvent) -> dict[str, Any]:
        clause, value = _order_ref_clause(event.order_ref)
        cur = await conn.execute(
            "SELECT o.id, o.order_no, o.status::text AS status, o.customer_id, "  # noqa: S608
            "o.total_minor, o.currency, o.payment_provider, o.review_reason "
            f"FROM orders o WHERE {clause} FOR UPDATE",  # clause yalnızca sabit ifadelerden
            (value,),
        )
        order = await cur.fetchone()
        actor = ("payment_webhook", f"{provider_name}:{event.event_id}"[:200])
        if order is None:
            await _audit(
                conn, actor_type=actor[0], actor_id=actor[1], action="payment.unknown_order",
                target_id=None, details={"order_ref": event.order_ref[:100]},
            )  # fmt: skip
            return {"result": "unknown_order"}

        if event.event_type != "payment_succeeded":
            await conn.execute(
                "INSERT INTO payments (order_id, provider, provider_payment_id, status, "
                "amount_minor, currency) VALUES (%s, %s, %s, 'failed', %s, %s) "
                "ON CONFLICT (provider, provider_payment_id) DO NOTHING",
                (
                    order["id"],
                    provider_name,
                    event.provider_payment_id,
                    max(event.amount_minor, 0),
                    event.currency or order["currency"],
                ),
            )
            await conn.execute(
                "UPDATE orders SET status = 'failed' WHERE id = %s AND status = 'pending'",
                (order["id"],),
            )
            await _audit(
                conn, actor_type=actor[0], actor_id=actor[1], action="payment.failed",
                target_id=order["id"], details={"order_no": order["order_no"]},
            )  # fmt: skip
            return {"result": "failed", "order_no": order["order_no"]}

        if order["status"] in ("fulfilled", "refunded", "partially_refunded"):
            return {"result": "already_fulfilled", "order_no": order["order_no"]}

        review: str | None = None
        try:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO payments (order_id, provider, provider_payment_id, status, "
                    "amount_minor, currency, succeeded_at) "
                    "VALUES (%s, %s, %s, 'succeeded', %s, %s, now()) "
                    "ON CONFLICT (provider, provider_payment_id) DO UPDATE "
                    "SET status = 'succeeded', amount_minor = excluded.amount_minor, "
                    "succeeded_at = now() WHERE payments.status IN ('pending', 'failed')",
                    (
                        order["id"],
                        provider_name,
                        event.provider_payment_id,
                        event.amount_minor,
                        event.currency,
                    ),
                )
        except pg_errors.UniqueViolation:
            review = "duplicate_payment"  # siparişin zaten başarılı başka bir ödemesi var
        except pg_errors.CheckViolation:
            review = "amount_mismatch"  # geçersiz para birimi/tutar
        if review is None and (
            event.amount_minor != order["total_minor"] or event.currency != order["currency"]
        ):
            review = "amount_mismatch"
        if review is None and order["payment_provider"] != provider_name:
            review = "provider_mismatch"

        await conn.execute(
            "UPDATE orders SET status = 'paid', paid_at = COALESCE(paid_at, now()), "
            "review_reason = COALESCE(%s, review_reason) WHERE id = %s",
            (review, order["id"]),
        )
        details = {
            "order_no": order["order_no"],
            "amount_minor": event.amount_minor,
            "currency": event.currency,
            "provider_payment_id": event.provider_payment_id[:100],
        }
        if review is not None or order["review_reason"] is not None:
            await _audit(
                conn, actor_type=actor[0], actor_id=actor[1], action="payment.needs_review",
                target_id=order["id"],
                details={**details, "reason": review or order["review_reason"],
                         "expected_minor": order["total_minor"],
                         "expected_currency": order["currency"]},
            )  # fmt: skip
            return {"result": "needs_review", "order_no": order["order_no"]}
        await _audit(
            conn, actor_type=actor[0], actor_id=actor[1], action="payment.succeeded",
            target_id=order["id"], details=details,
        )  # fmt: skip
        licenses = await self._fulfill(conn, order, actor=actor)
        return {"result": "fulfilled", "order_no": order["order_no"], "licenses": licenses}

    async def _fulfill(
        self, conn: Conn, order: dict[str, Any], *, actor: tuple[str, Any]
    ) -> list[str]:
        """Her sipariş birimine bir lisans (havuzdan ya da yeni); tekrar çağrıda aynıları döner."""
        cur = await conn.execute(
            "SELECT id, plan_code, quantity FROM order_items WHERE order_id = %s ORDER BY id",
            (order["id"],),
        )
        items = await cur.fetchall()
        license_ids: list[str] = []
        for item in items:
            for unit in range(1, int(item["quantity"]) + 1):
                cur = await conn.execute(
                    "SELECT id::text FROM licenses "
                    "WHERE order_item_id = %s AND order_item_unit = %s",
                    (item["id"], unit),
                )
                row = await cur.fetchone()
                if row is None:
                    cur = await conn.execute(
                        "UPDATE licenses l SET status = 'sold', customer_id = %s, "
                        "order_item_id = %s, order_item_unit = %s, sold_at = now(), "
                        "duration_days = p.duration_days, device_limit = p.device_limit, "
                        "companion_device_limit = p.companion_device_limit "
                        "FROM license_plans p WHERE p.code = l.plan_code AND l.id = ("
                        "SELECT id FROM licenses "
                        "WHERE plan_code = %s AND status = 'ready_for_sale' "
                        "ORDER BY serial LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING l.id::text",
                        (order["customer_id"], item["id"], unit, item["plan_code"]),
                    )
                    row = await cur.fetchone()
                if row is None:
                    if self.licensing is None:
                        raise PaymentError(503, "licensing_unavailable", "Lisans servisi kapalı")
                    license_id, _key = await self.licensing.issue(
                        conn,
                        plan_code=item["plan_code"],
                        customer_id=order["customer_id"],
                        order_item=(item["id"], unit),
                    )
                    row = {"id": license_id}
                license_ids.append(str(row["id"]))

        cur = await conn.execute(
            "SELECT email, locale FROM customers WHERE id = %s", (order["customer_id"],)
        )
        customer = _one(await cur.fetchone())
        # Anahtar e-postaya yazılmaz; gönderici lisans kimliğiyle gönderim anında çözer.
        await conn.execute(
            "INSERT INTO email_outbox (dedupe_key, to_email, template, payload) "
            "VALUES (%s, %s, 'license_delivery', %s) ON CONFLICT (dedupe_key) DO NOTHING",
            (
                f"license-delivery:{order['id']}",
                customer["email"],
                Jsonb(
                    {
                        "order_no": order["order_no"],
                        "license_ids": license_ids,
                        "locale": customer["locale"],
                        "panel_url": f"{self.settings.public_web_url.rstrip('/')}/panel",
                    }
                ),
            ),
        )
        cur = await conn.execute(
            "SELECT billing_snapshot, paid_at FROM orders WHERE id = %s", (order["id"],)
        )
        snap = _one(await cur.fetchone())
        await conn.execute(
            "INSERT INTO invoices (order_id, invoice_no, billing) VALUES (%s, %s, %s) "
            "ON CONFLICT (order_id) DO NOTHING",
            (
                order["id"],
                invoice_number(int(order["order_no"]), snap["paid_at"]),
                Jsonb(snap["billing_snapshot"].get("billing", {})),
            ),
        )
        await conn.execute(
            "UPDATE orders SET status = 'fulfilled', fulfilled_at = now() WHERE id = %s",
            (order["id"],),
        )
        await _audit(
            conn, actor_type=actor[0], actor_id=actor[1], action="order.fulfilled",
            target_id=order["id"],
            details={"order_no": order["order_no"], "licenses": license_ids},
        )  # fmt: skip
        return license_ids

    # --- Tarayıcı dönüşü (iyzico) ve mutabakat --------------------------------------------------

    async def iyzico_return(self, token: str) -> str:
        """iyzico tarayıcıyı ``callbackUrl``'e belirteçle gönderir; sonuç imzalı sunucu isteğiyle
        sağlayıcıdan alınır (tarayıcının söylediğine güvenilmez)."""
        async with self.db.connection() as conn:
            cur = await conn.execute(
                "SELECT id, order_no FROM orders WHERE payment_provider = 'iyzico' "
                "AND provider_checkout_id = %s",
                (token[:200],),
            )
            order = await cur.fetchone()
        if order is None:
            return f"{self.settings.public_web_url.rstrip('/')}/odeme/sonuc"
        await self.reconcile(order["id"])
        return self.result_url(int(order["order_no"]))

    async def reconcile(self, order_id: Any) -> dict[str, Any]:
        """Bekleyen siparişin sonucunu sağlayıcıdan sorgular (iyzico). PayTR sonucu bildirimle
        (sağlayıcı yeniden dener) gelir; orada sorgulanacak bir şey yoktur."""
        async with self.db.connection() as conn:
            cur = await conn.execute(
                "SELECT id, order_no, status::text AS status, payment_provider, "
                "provider_checkout_id FROM orders WHERE id = %s",
                (order_id,),
            )
            order = await cur.fetchone()
            cfg = await self.load_config(conn)
        if order is None:
            raise PaymentError(404, "not_found", "Sipariş bulunamadı")
        if order["status"] not in ("pending", "failed"):
            return {"result": "settled", "status": order["status"]}
        if order["payment_provider"] != "iyzico" or not order["provider_checkout_id"]:
            return {"result": "awaiting_notification", "status": order["status"]}
        if cfg.provider != "iyzico":
            raise PaymentError(409, "provider_changed", "Ödeme sağlayıcısı değişmiş")
        provider = self.provider(cfg)
        if not isinstance(provider, IyzicoProvider):
            raise PaymentError(409, "provider_changed", "Ödeme sağlayıcısı değişmiş")
        try:
            event = await provider.retrieve(order["provider_checkout_id"])
        except (InvalidSignature, ProviderError) as exc:
            log.warning("iyzico sonucu alınamadı (sipariş %s): %s", order["order_no"], exc)
            return {"result": "unavailable", "status": order["status"]}
        if event.order_ref != str(order["id"]):
            await self._record_invalid("iyzico", order["provider_checkout_id"].encode(), "", "ref")
            return {"result": "mismatch", "status": order["status"]}
        return await self.process("iyzico", event)

    # --- Simülatör (yalnızca geliştirme/test) ---------------------------------------------------

    async def simulator_order(self, customer_id: Any, token: str) -> dict[str, Any]:
        if self.production_like:
            raise PaymentError(404, "not_found", "Bulunamadı")
        try:
            order_id = self.simulator.open_session(token)
        except InvalidSignature as exc:
            raise PaymentError(400, "invalid_session", "Test ödeme oturumu geçersiz") from exc
        async with self.db.connection() as conn:
            cur = await conn.execute(
                "SELECT o.id, o.order_no, o.status::text AS status, o.total_minor, o.currency, "
                "p.name AS plan_name FROM orders o JOIN order_items i ON i.order_id = o.id "
                "JOIN license_plans p ON p.code = i.plan_code "
                "WHERE o.id = %s AND o.customer_id = %s AND o.payment_provider = 'simulator'",
                (order_id, customer_id),
            )
            order = await cur.fetchone()
        if order is None:
            raise PaymentError(404, "not_found", "Sipariş bulunamadı")
        return order

    async def simulate(self, customer_id: Any, token: str, outcome: str, ip: str) -> int:
        order = await self.simulator_order(customer_id, token)
        body = self.simulator.build_webhook(
            order_id=str(order["id"]),
            outcome=outcome,
            amount_minor=int(order["total_minor"]),
            currency=str(order["currency"]),
        )
        headers = {"x-simulator-signature": self.simulator.sign(body)}
        await self.handle_webhook("simulator", headers, body, ip)
        return int(order["order_no"])

    # --- İade (yönetici) ----------------------------------------------------------------------

    async def refund(
        self,
        *,
        admin_id: Any,
        order_id: Any,
        amount_minor: int | None,
        reason: str,
        license_action: str,
        ip: str,
    ) -> dict[str, Any]:
        async with self.db.connection() as conn:
            cur = await conn.execute(
                "SELECT p.id, p.provider, p.provider_payment_id, p.amount_minor, "
                "p.refunded_minor, p.currency, o.id AS order_id, o.order_no "
                "FROM payments p JOIN orders o ON o.id = p.order_id WHERE p.order_id = %s "
                "AND p.status IN ('succeeded', 'partially_refunded') FOR UPDATE OF p",
                (order_id,),
            )
            pay = await cur.fetchone()
            if pay is None:
                raise PaymentError(409, "not_refundable", "Bu siparişte iade edilebilir ödeme yok")
            cur = await conn.execute(
                "SELECT COALESCE(sum(amount_minor), 0) AS s FROM refunds "
                "WHERE payment_id = %s AND status = 'pending'",
                (pay["id"],),
            )
            pending = int((await cur.fetchone() or {"s": 0})["s"])
            refundable = int(pay["amount_minor"]) - int(pay["refunded_minor"]) - pending
            amount = refundable if amount_minor is None else amount_minor
            if amount <= 0 or amount > refundable:
                raise PaymentError(
                    409, "invalid_amount", f"İade tutarı 0 ile {refundable} (kuruş) arasında olmalı"
                )
            cfg = await self.load_config(conn)
            if cfg.provider != pay["provider"] and pay["provider"] != "simulator":
                raise PaymentError(
                    409,
                    "provider_changed",
                    "Ödeme sağlayıcısı değişmiş; bu iadeyi sağlayıcının panelinden yapın.",
                )
            provider: Provider = (
                self.simulator if pay["provider"] == "simulator" else self.provider(cfg)
            )
            if pay["provider"] == "simulator" and self.production_like:
                raise PaymentError(409, "provider_changed", "Simülatör ödemesi iade edilemez")
            cur = await conn.execute(
                "INSERT INTO refunds (payment_id, provider_refund_id, amount_minor, reason, "
                "status, license_action, requested_by) "
                "VALUES (%s, %s, %s, %s, 'pending', %s, %s) RETURNING id",
                (
                    pay["id"],
                    f"pending:{uuid.uuid4()}",
                    amount,
                    reason,
                    license_action,
                    admin_id,
                ),
            )
            refund_row = _one(await cur.fetchone())
            refund_id = refund_row["id"]
            await _audit(
                conn, actor_type="admin", actor_id=admin_id, action="payment.refund_requested",
                target_id=pay["order_id"], ip=ip,
                details={"order_no": pay["order_no"], "amount_minor": amount,
                         "license_action": license_action, "reason": reason},
            )  # fmt: skip

        try:
            provider_refund_id = await provider.refund(
                provider_payment_id=pay["provider_payment_id"],
                amount_minor=amount,
                currency=pay["currency"],
                order_ref=str(pay["order_id"]),
            )
        except ProviderError as exc:
            async with self.db.connection() as conn:
                await conn.execute(
                    "UPDATE refunds SET status = 'failed', provider_refund_id = %s, "
                    "last_error = %s, completed_at = now() WHERE id = %s",
                    (f"failed:{refund_id}", str(exc)[:300], refund_id),
                )
                await _audit(
                    conn, actor_type="admin", actor_id=admin_id, action="payment.refund_failed",
                    target_id=pay["order_id"], ip=ip,
                    details={"order_no": pay["order_no"], "error": str(exc)[:200]},
                )  # fmt: skip
            raise PaymentError(502, "refund_failed", f"İade yapılamadı: {exc}") from exc

        async with self.db.connection() as conn:
            await _act_as(conn, "admin", str(admin_id))
            await conn.execute(
                "UPDATE refunds SET status = 'succeeded', provider_refund_id = %s, "
                "completed_at = now() WHERE id = %s",
                (provider_refund_id[:200], refund_id),
            )
            cur = await conn.execute(
                "UPDATE payments SET refunded_minor = refunded_minor + %s, status = CASE "
                "WHEN refunded_minor + %s >= amount_minor THEN 'refunded'::payment_status "
                "ELSE 'partially_refunded'::payment_status END WHERE id = %s "
                "RETURNING status::text AS status",
                (amount, amount, pay["id"]),
            )
            pay_status = (await cur.fetchone() or {"status": "refunded"})["status"]
            await conn.execute(
                "UPDATE orders SET status = %s::order_status WHERE id = %s",
                (pay_status, pay["order_id"]),
            )
            cancelled: list[str] = []
            if license_action == "cancel":
                cur = await conn.execute(
                    "UPDATE licenses SET status = 'cancelled', cancel_reason = %s "
                    "WHERE order_item_id IN (SELECT id FROM order_items WHERE order_id = %s) "
                    "AND status <> 'cancelled' RETURNING id::text",
                    (f"İade: {reason}"[:200], pay["order_id"]),
                )
                cancelled = [r["id"] for r in await cur.fetchall()]
            await _audit(
                conn, actor_type="admin", actor_id=admin_id, action="payment.refunded",
                target_id=pay["order_id"], ip=ip,
                details={"order_no": pay["order_no"], "amount_minor": amount,
                         "payment_status": pay_status, "license_action": license_action,
                         "cancelled_licenses": cancelled},
            )  # fmt: skip
        return {
            "refund_id": str(refund_id),
            "amount_minor": amount,
            "payment_status": pay_status,
            "cancelled_licenses": cancelled,
        }

    # --- Bakım ---------------------------------------------------------------------------------

    async def reconcile_pending(self, older_than_minutes: int, limit: int = 100) -> int:
        """Tarayıcısı geri dönmemiş (ör. sekmeyi kapatan müşteri) iyzico ödemelerini sorgular."""
        async with self.db.connection() as conn:
            cur = await conn.execute(
                "SELECT id FROM orders WHERE status = 'pending' AND payment_provider = 'iyzico' "
                "AND provider_checkout_id IS NOT NULL "
                "AND created_at < now() - make_interval(mins => %s) "
                "AND created_at > now() - interval '2 days' ORDER BY created_at LIMIT %s",
                (older_than_minutes, limit),
            )
            ids = [r["id"] for r in await cur.fetchall()]
        settled = 0
        for order_id in ids:
            result = await self.reconcile(order_id)
            settled += result.get("result") in ("fulfilled", "failed", "needs_review")
        return settled

    async def expire_pending(self, hours: int) -> int:
        """Süresi geçmiş ödenmemiş siparişleri iptal eder (geç gelen başarılı ödeme işlenir)."""
        async with self.db.connection() as conn:
            cur = await conn.execute(
                "UPDATE orders SET status = 'cancelled', cancelled_at = now() "
                "WHERE status IN ('pending', 'failed') "
                "AND created_at < now() - make_interval(hours => %s) RETURNING id",
                (hours,),
            )
            return len(await cur.fetchall())
