"""Ödeme sağlayıcı soyutlaması ve uyarlayıcılar.

Her sağlayıcı üç şey yapar: ödeme oturumu açar (müşteri sağlayıcının sayfasına yönlendirilir),
sağlayıcıdan gelen bildirimi **imzasını doğrulayarak** olaya çevirir ve iade başlatır. Sipariş,
lisans teslimi ve idempotentlik sağlayıcıdan bağımsızdır (``service.py``).

* **PayTR** (iFrame API): oturum belirteci ``paytr_token`` HMAC-SHA256 ile; bildirim (callback)
  ``hash`` alanı HMAC-SHA256(merchant_key, merchant_oid + merchant_salt + status + total_amount).
  Bildirime düz metin ``OK`` ile yanıt verilir.
* **iyzico** (Ödeme Formu): istekler ``IYZWSv2`` imzalı; tarayıcı geri dönüşündeki belirteçle
  sonuç, kimliği doğrulanmış sunucu isteğiyle (``checkoutform/auth/ecom/detail``) alınır —
  doğrulama sağlayıcıya yapılan imzalı istekle sağlanır.
* **Lemon Squeezy** (satıcı adına satış / Merchant of Record): ödeme sayfası Lemon Squeezy'de
  açılır (kart, 3D Secure, fatura ve KDV onlarda). Oturum ``POST /v1/checkouts`` ile; bildirim
  ``X-Signature`` = HMAC-SHA256(imza sırrı, ham gövde), onaltılık. Sipariş kimliğimiz
  ``checkout_data.custom.order_id`` ile gider, bildirimde ``meta.custom_data`` olarak döner.
* **Simülatör** (yalnızca geliştirme/test): sağlayıcı sayfası yerine sitedeki test sayfası;
  bildirim HMAC-SHA256 ile imzalanır. Uçtan uca testler gerçek bildirim hattından geçer.

Not: PayTR ve iyzico istek/imza biçimleri sağlayıcıların belgelerine göre yazıldı ve birim
testleriyle doğrulanıyor; sağlayıcıların test ortamında uçtan uca deneme, test hesabı
bilgileri girildiğinde yapılacak (docs/05, Aşama 17).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol
from urllib.parse import parse_qs

import httpx


class InvalidSignature(Exception):
    """Bildirim imzası doğrulanamadı (sahte veya bozuk istek)."""


class ProviderError(Exception):
    """Sağlayıcı isteği başarısız (ağ, yanıt, yapılandırma)."""


@dataclass(frozen=True)
class Buyer:
    customer_id: str
    email: str
    full_name: str
    phone: str
    address: str
    city: str
    country: str
    ip: str
    tax_id: str | None = None


@dataclass(frozen=True)
class CheckoutRequest:
    order_id: str
    order_no: int
    amount_minor: int
    currency: str
    item_name: str
    plan_code: str
    buyer: Buyer
    success_url: str
    fail_url: str
    callback_url: str


@dataclass(frozen=True)
class CheckoutSession:
    provider_ref: str
    redirect_url: str


@dataclass(frozen=True)
class PaymentEvent:
    """Sağlayıcıdan bağımsız olay. ``order_ref`` bizim sipariş kimliğimizdir (UUID)."""

    event_id: str
    event_type: str  # payment_succeeded | payment_failed
    order_ref: str
    provider_payment_id: str
    amount_minor: int
    currency: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebhookReply:
    status: int = 200
    body: str = "OK"
    media_type: str = "text/plain"


def minor_to_decimal(minor: int) -> str:
    return f"{Decimal(minor) / 100:.2f}"


def decimal_to_minor(text: str) -> int:
    return int((Decimal(str(text)) * 100).to_integral_value())


class Provider(Protocol):
    name: str
    test_mode: bool

    async def create_checkout(self, req: CheckoutRequest) -> CheckoutSession: ...

    async def refund(
        self, *, provider_payment_id: str, amount_minor: int, currency: str, order_ref: str
    ) -> str: ...


# --- Simülatör (yalnızca geliştirme / test) -----------------------------------------------------


class SimulatorProvider:
    """Test ödeme sağlayıcısı. Üretimde kullanılamaz (``service.provider_for`` reddeder)."""

    name = "simulator"
    test_mode = True

    def __init__(self, secret: bytes, web_url: str) -> None:
        self.secret = secret
        self.web_url = web_url

    def session_token(self, order_id: str) -> str:
        mac = hmac.new(self.secret, f"session|{order_id}".encode(), hashlib.sha256).hexdigest()[:32]
        return f"{order_id}.{mac}"

    def open_session(self, token: str) -> str:
        order_id, _, mac = token.partition(".")
        expected = self.session_token(order_id).partition(".")[2]
        if not mac or not hmac.compare_digest(mac, expected):
            raise InvalidSignature("Test ödeme oturumu geçersiz")
        return order_id

    async def create_checkout(self, req: CheckoutRequest) -> CheckoutSession:
        token = self.session_token(req.order_id)
        return CheckoutSession(
            provider_ref=token, redirect_url=f"{self.web_url}/odeme/test?oturum={token}"
        )

    def sign(self, body: bytes) -> str:
        return hmac.new(self.secret, body, hashlib.sha256).hexdigest()

    def build_webhook(
        self, *, order_id: str, outcome: str, amount_minor: int, currency: str
    ) -> bytes:
        payload = {
            "id": f"sim_evt_{secrets.token_hex(8)}",
            "type": "payment_succeeded" if outcome == "success" else "payment_failed",
            "order_id": order_id,
            "payment_id": f"sim_pay_{secrets.token_hex(8)}",
            "amount_minor": amount_minor,
            "currency": currency,
        }
        return json.dumps(payload, separators=(",", ":")).encode()

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> PaymentEvent:
        signature = headers.get("x-simulator-signature", "")
        if not hmac.compare_digest(signature, self.sign(body)):
            raise InvalidSignature("Test ödeme bildirimi imzası geçersiz")
        data = json.loads(body)
        return PaymentEvent(
            event_id=str(data["id"]),
            event_type=str(data["type"]),
            order_ref=str(data["order_id"]),
            provider_payment_id=str(data["payment_id"]),
            amount_minor=int(data["amount_minor"]),
            currency=str(data["currency"]),
            raw=data,
        )

    async def refund(
        self, *, provider_payment_id: str, amount_minor: int, currency: str, order_ref: str
    ) -> str:
        return f"sim_ref_{secrets.token_hex(8)}"


# --- PayTR ------------------------------------------------------------------------------------


class PaytrProvider:
    """PayTR iFrame API. ``merchant_oid`` yalnızca harf/rakam olabilir: ``ATI<sipariş no>``."""

    name = "paytr"
    API = "https://www.paytr.com"

    def __init__(
        self,
        *,
        merchant_id: str,
        merchant_key: str,
        merchant_salt: str,
        test_mode: bool,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.merchant_id = merchant_id
        self.merchant_key = merchant_key.encode()
        self.merchant_salt = merchant_salt
        self.test_mode = test_mode
        self._transport = transport

    def _hmac_b64(self, text: str) -> str:
        return base64.b64encode(
            hmac.new(self.merchant_key, text.encode(), hashlib.sha256).digest()
        ).decode()

    @staticmethod
    def merchant_oid(order_no: int) -> str:
        return f"ATI{order_no}"

    def token_fields(self, req: CheckoutRequest) -> dict[str, str]:
        basket = base64.b64encode(
            json.dumps(
                [[req.item_name, minor_to_decimal(req.amount_minor), 1]], ensure_ascii=False
            ).encode()
        ).decode()
        fields = {
            "merchant_id": self.merchant_id,
            "user_ip": req.buyer.ip,
            "merchant_oid": self.merchant_oid(req.order_no),
            "email": req.buyer.email,
            "payment_amount": str(req.amount_minor),
            "user_basket": basket,
            "no_installment": "1",
            "max_installment": "0",
            "currency": "TL" if req.currency == "TRY" else req.currency,
            "test_mode": "1" if self.test_mode else "0",
        }
        hash_str = "".join(
            fields[k]
            for k in (
                "merchant_id", "user_ip", "merchant_oid", "email", "payment_amount",
                "user_basket", "no_installment", "max_installment", "currency", "test_mode",
            )
        )  # fmt: skip
        fields["paytr_token"] = self._hmac_b64(hash_str + self.merchant_salt)
        fields.update(
            {
                "debug_on": "0",
                "merchant_ok_url": req.success_url,
                "merchant_fail_url": req.fail_url,
                "user_name": req.buyer.full_name[:60],
                "user_address": req.buyer.address[:400],
                "user_phone": req.buyer.phone[:20],
                "timeout_limit": "30",
                "lang": "tr",
            }
        )
        return fields

    async def create_checkout(self, req: CheckoutRequest) -> CheckoutSession:
        try:
            async with httpx.AsyncClient(
                base_url=self.API, timeout=20, transport=self._transport
            ) as client:
                response = await client.post("/odeme/api/get-token", data=self.token_fields(req))
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError("PayTR'ye ulaşılamadı") from exc
        if body.get("status") != "success" or not body.get("token"):
            raise ProviderError(
                f"PayTR ödeme oturumu açılamadı: {str(body.get('reason', ''))[:200]}"
            )
        token = str(body["token"])
        return CheckoutSession(provider_ref=token, redirect_url=f"{self.API}/odeme/guvenli/{token}")

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> PaymentEvent:
        form = {k: v[0] for k, v in parse_qs(body.decode(), keep_blank_values=True).items()}
        oid, status, total = (
            form.get("merchant_oid", ""),
            form.get("status", ""),
            form.get("total_amount", ""),
        )
        expected = self._hmac_b64(oid + self.merchant_salt + status + total)
        if not form.get("hash") or not hmac.compare_digest(form["hash"], expected):
            raise InvalidSignature("PayTR bildirimi imzası geçersiz")
        # Taksit farkı total_amount'a eklenebilir; sipariş tutarı payment_amount'tadır.
        amount = form.get("payment_amount") or total
        return PaymentEvent(
            event_id=f"{oid}:{status}",
            event_type="payment_succeeded" if status == "success" else "payment_failed",
            order_ref=oid,
            provider_payment_id=oid,
            amount_minor=int(amount or 0),
            currency="TRY"
            if form.get("currency", "TL") in ("TL", "TRY")
            else form.get("currency", ""),
            raw={k: v for k, v in form.items() if k != "hash"},
        )

    async def refund(
        self, *, provider_payment_id: str, amount_minor: int, currency: str, order_ref: str
    ) -> str:
        amount = minor_to_decimal(amount_minor)
        token = self._hmac_b64(self.merchant_id + provider_payment_id + amount + self.merchant_salt)
        data = {
            "merchant_id": self.merchant_id,
            "merchant_oid": provider_payment_id,
            "return_amount": amount,
            "paytr_token": token,
        }
        try:
            async with httpx.AsyncClient(
                base_url=self.API, timeout=20, transport=self._transport
            ) as client:
                body = (await client.post("/odeme/iade", data=data)).json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError("PayTR'ye ulaşılamadı") from exc
        if body.get("status") != "success":
            raise ProviderError(f"PayTR iadesi başarısız: {str(body.get('err_msg', ''))[:200]}")
        return f"{provider_payment_id}:refund:{amount}:{int(time.time())}"


# --- iyzico ------------------------------------------------------------------------------------


class IyzicoProvider:
    name = "iyzico"
    LIVE = "https://api.iyzipay.com"
    SANDBOX = "https://sandbox-api.iyzipay.com"
    INIT = "/payment/iyzipos/checkoutform/initialize/auth/ecom"
    DETAIL = "/payment/iyzipos/checkoutform/auth/ecom/detail"
    REFUND = "/v2/payment/refund"

    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        test_mode: bool,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.secret_key = secret_key.encode()
        self.test_mode = test_mode
        self.base_url = self.SANDBOX if test_mode else self.LIVE
        self._transport = transport

    def auth_headers(
        self, uri_path: str, body: str, random_key: str | None = None
    ) -> dict[str, str]:
        """IYZWSv2: HMAC-SHA256(secret, randomKey + uri_path + gövde), onaltılık."""
        rnd = random_key or f"{int(time.time() * 1000)}{secrets.randbelow(10**9):09d}"
        signature = hmac.new(
            self.secret_key, (rnd + uri_path + body).encode(), hashlib.sha256
        ).hexdigest()
        auth = f"apiKey:{self.api_key}&randomKey:{rnd}&signature:{signature}"
        return {
            "Authorization": "IYZWSv2 " + base64.b64encode(auth.encode()).decode(),
            "x-iyzi-rnd": rnd,
            "Content-Type": "application/json",
        }

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=20, transport=self._transport
            ) as client:
                response = await client.post(
                    path, content=body.encode(), headers=self.auth_headers(path, body)
                )
            data: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError("iyzico'ya ulaşılamadı") from exc
        return data

    async def create_checkout(self, req: CheckoutRequest) -> CheckoutSession:
        name, _, surname = req.buyer.full_name.strip().partition(" ")
        price = minor_to_decimal(req.amount_minor)
        address = {
            "contactName": req.buyer.full_name[:100],
            "city": req.buyer.city[:50],
            "country": req.buyer.country[:50],
            "address": req.buyer.address[:400],
        }
        payload = {
            "locale": "tr",
            "conversationId": req.order_id,
            "price": price,
            "paidPrice": price,
            "currency": req.currency,
            "basketId": req.order_id,
            "paymentGroup": "PRODUCT",
            "callbackUrl": req.callback_url,
            "enabledInstallments": [1],
            "buyer": {
                "id": req.buyer.customer_id,
                "name": name or req.buyer.full_name,
                "surname": surname or "-",
                "gsmNumber": req.buyer.phone,
                "email": req.buyer.email,
                "identityNumber": req.buyer.tax_id or "11111111111",
                "registrationAddress": req.buyer.address[:400],
                "ip": req.buyer.ip,
                "city": req.buyer.city[:50],
                "country": req.buyer.country[:50],
            },
            "billingAddress": address,
            "basketItems": [
                {
                    "id": req.plan_code,
                    "name": req.item_name[:100],
                    "category1": "Yazılım lisansı",
                    "itemType": "VIRTUAL",
                    "price": price,
                }
            ],
        }
        data = await self._post(self.INIT, payload)
        if data.get("status") != "success" or not data.get("paymentPageUrl"):
            raise ProviderError(
                f"iyzico ödeme oturumu açılamadı: {str(data.get('errorMessage', ''))[:200]}"
            )
        return CheckoutSession(
            provider_ref=str(data["token"]), redirect_url=str(data["paymentPageUrl"])
        )

    async def retrieve(self, token: str) -> PaymentEvent:
        """Tarayıcı geri dönüşündeki belirteçle sonucu sağlayıcıdan (imzalı istekle) alır."""
        data = await self._post(self.DETAIL, {"locale": "tr", "token": token})
        if data.get("status") != "success":
            raise InvalidSignature("iyzico ödeme sonucu doğrulanamadı")
        succeeded = data.get("paymentStatus") == "SUCCESS"
        return PaymentEvent(
            event_id=f"checkout:{token}",
            event_type="payment_succeeded" if succeeded else "payment_failed",
            order_ref=str(data.get("basketId") or data.get("conversationId") or ""),
            provider_payment_id=str(data.get("paymentId") or token),
            amount_minor=decimal_to_minor(str(data.get("paidPrice") or "0")),
            currency=str(data.get("currency") or ""),
            raw={
                k: data.get(k)
                for k in ("paymentId", "paymentStatus", "paidPrice", "currency", "basketId")
            },
        )

    async def refund(
        self, *, provider_payment_id: str, amount_minor: int, currency: str, order_ref: str
    ) -> str:
        data = await self._post(
            self.REFUND,
            {
                "locale": "tr",
                "conversationId": order_ref,
                "paymentId": provider_payment_id,
                "price": minor_to_decimal(amount_minor),
                "currency": currency,
            },
        )
        if data.get("status") != "success":
            raise ProviderError(
                f"iyzico iadesi başarısız: {str(data.get('errorMessage', ''))[:200]}"
            )
        return (
            str(data.get("paymentTransactionId") or data.get("paymentId") or provider_payment_id)
            + ":refund"
        )


# --- Lemon Squeezy -------------------------------------------------------------------------------


class LemonSqueezyProvider:
    """Lemon Squeezy (Merchant of Record). Satış Lemon Squeezy'nin şirketi üzerinden yapılır;
    ödeme sayfası, 3D Secure, fatura ve KDV onlarda. Mağazada tek bir "yazılım lisansı" ürünü
    (varyant) açılır; tutar her siparişte ``custom_price`` ile gönderilir.

    Mağazanın para birimi paket para birimiyle aynı olmalıdır; değilse bildirimdeki tutar/para
    birimi siparişle eşleşmez ve sipariş otomatik teslim yerine incelemeye düşer.
    """

    name = "lemonsqueezy"
    API = "https://api.lemonsqueezy.com"
    JSONAPI = "application/vnd.api+json"
    HANDLED = frozenset({"order_created", "order_refunded"})

    def __init__(
        self,
        *,
        api_key: str,
        signing_secret: str,
        store_id: str,
        variant_id: str,
        test_mode: bool,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.signing_secret = signing_secret.encode()
        self.store_id = store_id
        self.variant_id = variant_id
        self.test_mode = test_mode
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": self.JSONAPI,
            "Content-Type": self.JSONAPI,
        }

    async def _request(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self.API, timeout=20, transport=self._transport
            ) as client:
                response = await client.request(
                    method, path, content=json.dumps(payload).encode(), headers=self._headers()
                )
            data: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError("Lemon Squeezy'ye ulaşılamadı") from exc
        if response.status_code >= 400:
            errors = data.get("errors") or [{}]
            detail = str(errors[0].get("detail") or errors[0].get("title") or response.status_code)
            raise ProviderError(f"Lemon Squeezy isteği reddetti: {detail[:200]}")
        return data

    def checkout_payload(self, req: CheckoutRequest) -> dict[str, Any]:
        return {
            "data": {
                "type": "checkouts",
                "attributes": {
                    "custom_price": req.amount_minor,
                    "product_options": {
                        "name": req.item_name[:100],
                        "redirect_url": req.success_url,
                        "enabled_variants": [int(self.variant_id)],
                    },
                    "checkout_options": {"embed": False},
                    "checkout_data": {
                        "email": req.buyer.email,
                        "name": req.buyer.full_name[:100],
                        "custom": {"order_id": req.order_id, "order_no": str(req.order_no)},
                    },
                    "test_mode": self.test_mode,
                },
                "relationships": {
                    "store": {"data": {"type": "stores", "id": str(self.store_id)}},
                    "variant": {"data": {"type": "variants", "id": str(self.variant_id)}},
                },
            }
        }

    async def create_checkout(self, req: CheckoutRequest) -> CheckoutSession:
        data = await self._request("POST", "/v1/checkouts", self.checkout_payload(req))
        node = data.get("data") or {}
        url = (node.get("attributes") or {}).get("url")
        if not url or not node.get("id"):
            raise ProviderError("Lemon Squeezy ödeme sayfası adresi dönmedi")
        return CheckoutSession(provider_ref=str(node["id"]), redirect_url=str(url))

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> PaymentEvent:
        signature = headers.get("x-signature", "")
        expected = hmac.new(self.signing_secret, body, hashlib.sha256).hexdigest()
        if not signature or not hmac.compare_digest(signature, expected):
            raise InvalidSignature("Lemon Squeezy bildirimi imzası geçersiz")
        payload = json.loads(body)
        meta = payload.get("meta") or {}
        event_name = str(meta.get("event_name") or "")
        node = payload.get("data") or {}
        attrs = node.get("attributes") or {}
        order_ref = str((meta.get("custom_data") or {}).get("order_id") or "")
        if attrs.get("test_mode") and not self.test_mode:
            # Canlı modda test ödemesi asla lisans vermez.
            raise InvalidSignature("Canlı modda test ödemesi bildirimi kabul edilmez")
        if event_name not in self.HANDLED or node.get("type") != "orders" or not order_ref:
            # Başka olaylar (abonelik vb.) ve bizim başlatmadığımız siparişler yok sayılır.
            return PaymentEvent(
                event_id=f"{event_name}:{node.get('id')}",
                event_type="ignored",
                order_ref=order_ref,
                provider_payment_id=str(node.get("id") or ""),
                amount_minor=0,
                currency="",
                raw={"event_name": event_name},
            )
        status = str(attrs.get("status") or "")
        if event_name == "order_refunded":
            # İade panelden başlatılır ve orada kaydedilir; bildirim yalnızca bilgi içindir.
            event_type = "ignored"
        elif status == "paid":
            event_type = "payment_succeeded"
        elif status == "failed":
            event_type = "payment_failed"
        else:
            event_type = "ignored"  # bekleyen ödeme: sonuç ayrı bildirimle gelir
        return PaymentEvent(
            event_id=f"{event_name}:{node.get('id')}:{status}",
            event_type=event_type,
            order_ref=order_ref,
            provider_payment_id=str(node.get("id") or ""),
            amount_minor=int(attrs.get("total") or 0),
            currency=str(attrs.get("currency") or "").upper(),
            raw={
                "event_name": event_name,
                "status": status,
                "identifier": attrs.get("identifier"),
                "test_mode": bool(attrs.get("test_mode")),
            },
        )

    async def refund(
        self, *, provider_payment_id: str, amount_minor: int, currency: str, order_ref: str
    ) -> str:
        payload = {
            "data": {
                "type": "orders",
                "id": str(provider_payment_id),
                "attributes": {"amount": amount_minor},
            }
        }
        data = await self._request("POST", f"/v1/orders/{provider_payment_id}/refund", payload)
        status = str(((data.get("data") or {}).get("attributes") or {}).get("status") or "")
        return f"{provider_payment_id}:refund:{amount_minor}:{status or 'requested'}"
