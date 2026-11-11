"""Lisans işlemleri: üretim, aktivasyon, kira yenileme, cihaz bırakma, müşteri cihaz yönetimi.

Kurallar veritabanında da zorlanır (durum makinesi, cihaz limiti tetikleyicisi, tek satış);
buradaki kod bunları anlaşılır hata kodlarına çevirir. Motor isteklerinde sıra:

1. Biçim ve sürüm → 2. imza (cihaz anahtarı) → 3. zaman farkı → 4. tekrar oynatma (aktivasyon
başına artan zaman damgası) → 5. lisans durumu.

İmza, tekrar oynatma kaydından **önce** denetlenir: sahte bir istek sayacı ilerletemez.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg import errors as pg_errors

from ati_cloud.config import CloudSettings
from ati_cloud.licensing.keys import InvalidLicenseKey, KeyCipher, KeyHasher, generate_key, key_hint
from ati_cloud.licensing.lease import (
    BadRequestSignature,
    LeaseSigner,
    LeaseTerms,
    lease_payload,
    open_device_request,
)

Conn = psycopg.AsyncConnection[dict[str, Any]]


class LicenseError(Exception):
    """İstemciye kodu ve Türkçe açıklamasıyla dönen lisans hatası."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


# Motorun yerel kirayı silmesini gerektiren (kalıcı) hatalar. Ağ/sunucu hatalarında kira korunur.
UNASSIGNED_MESSAGE = (
    "Bu lisans henüz bir müşteri hesabına atanmadı (satış havuzunda). Yönetim panelinde "
    "Lisanslar → Ayrıntı → Müşteriye ata ile atanması gerekir."
)

TERMINAL_CODES = frozenset(
    {"not_found", "cancelled", "frozen", "expired", "not_activated", "device_revoked"}
)


@asynccontextmanager
async def _tx(conn: Conn) -> AsyncIterator[None]:
    """İşlem bloğu. ``LicenseError`` yalnızca yazma yapılmadan önce ya da imzası doğrulanmış
    istekte (ör. süresi dolan lisansı ``expired`` yapma) atılır; bu yüzden o noktaya kadarki
    değişiklikler işlenir, sonra hata istemciye iletilir. Diğer hatalarda geri alınır."""
    error: LicenseError | None = None
    async with conn.transaction():
        try:
            yield
        except LicenseError as exc:
            error = exc
    if error is not None:
        raise error


def _ms(value: datetime | None) -> int | None:
    return None if value is None else int(value.timestamp() * 1000)


def _b64_secret(value: Any, name: str, size: int | None = None) -> bytes:
    raw = base64.b64decode(value.get_secret_value(), validate=True)
    if size is not None and len(raw) != size:
        raise ValueError(f"{name} {size} bayt olmalı")
    return raw


@dataclass
class Licensing:
    hasher: KeyHasher
    cipher: KeyCipher
    signer: LeaseSigner
    ttl_s: int
    offline_s: int
    resets_per_30d: int
    skew_s: int

    @classmethod
    def from_settings(cls, settings: CloudSettings) -> Licensing | None:
        if not settings.licensing_configured:
            return None
        pepper, kek, signing = (
            settings.license_pepper,
            settings.license_kek,
            settings.lease_signing_key,
        )
        if pepper is None or kek is None or signing is None:
            return None
        return cls(
            hasher=KeyHasher(_b64_secret(pepper, "ATI_LICENSE_PEPPER")),
            cipher=KeyCipher(_b64_secret(kek, "ATI_LICENSE_KEK", 32), settings.license_kek_id),
            signer=LeaseSigner(_b64_secret(signing, "ATI_LEASE_SIGNING_KEY", 32)),
            ttl_s=settings.lease_ttl_s,
            offline_s=settings.lease_offline_s,
            resets_per_30d=settings.device_resets_per_30d,
            skew_s=settings.max_request_skew_s,
        )

    # --- Üretim ---------------------------------------------------------------------------

    async def issue(
        self,
        conn: Conn,
        *,
        plan_code: str,
        customer_id: Any | None = None,
        batch_id: Any | None = None,
        order_item: tuple[Any, int] | None = None,
    ) -> tuple[str, str]:
        """Yeni lisans üretir; anahtarın kendisi yalnızca burada, bir kez döner.

        Müşteri verilirse lisans doğrudan ``sold`` (elle satış / teslim), verilmezse satış
        havuzuna (``ready_for_sale``) girer. ``order_item`` (kalem, birim) satın alma teslimidir;
        ``UNIQUE (order_item_id, order_item_unit)`` aynı birime ikinci lisansı engeller.
        """
        if order_item is not None and customer_id is None:
            raise ValueError("Sipariş teslimi müşteri gerektirir")
        item_id, unit = order_item if order_item is not None else (None, None)
        for _ in range(3):  # 2^75 uzayda çakışma pratikte yok; yine de tekil kısıt yakalar
            key = generate_key()
            digest = self.hasher.digest(key)
            try:
                async with conn.transaction():
                    cur = await conn.execute(
                        "INSERT INTO licenses (key_hash, key_ciphertext, key_hint, plan_code, "
                        "batch_id, status, customer_id, sold_at, order_item_id, order_item_unit, "
                        "duration_days, device_limit, companion_device_limit) "
                        "SELECT %s, %s, %s, code, %s, %s, %s, "
                        "CASE WHEN %s::uuid IS NULL THEN NULL ELSE now() END, %s, %s, "
                        "duration_days, device_limit, companion_device_limit "
                        "FROM license_plans WHERE code = %s RETURNING id::text",
                        (
                            digest,
                            self.cipher.encrypt(key, digest),
                            key_hint(key),
                            batch_id,
                            "sold" if customer_id else "ready_for_sale",
                            customer_id,
                            customer_id,
                            item_id,
                            unit,
                            plan_code,
                        ),
                    )
                    row = await cur.fetchone()
            except pg_errors.UniqueViolation as exc:
                if exc.diag.constraint_name != "licenses_key_hash_key":
                    raise  # ör. aynı sipariş birimine ikinci lisans: tekrar denenmez
                continue
            if row is None:
                raise LicenseError(404, "unknown_plan", f"Paket bulunamadı: {plan_code}")
            return row["id"], key
        raise RuntimeError("Lisans anahtarı üretilemedi")

    # --- Motor istekleri ------------------------------------------------------------------

    def _check_time(self, payload: dict[str, Any], now_ms: int) -> int:
        ts = payload.get("ts_ms")
        if not isinstance(ts, int) or abs(now_ms - ts) > self.skew_s * 1000:
            raise LicenseError(
                400,
                "stale",
                "Bilgisayarınızın saati yanlış görünüyor. Saati otomatik ayarlayıp tekrar deneyin.",
            )
        return ts

    def _lease(self, row: dict[str, Any], now_ms: int) -> dict[str, Any]:
        terms = LeaseTerms(
            license_id=str(row["license_id"]),
            serial=int(row["serial"]),
            plan_code=row["plan_code"],
            plan_name=row["plan_name"],
            status=row["status"],
            license_expires_at_ms=_ms(row["expires_at"]),
            device_limit=int(row["device_limit"]),
            companion_device_limit=int(row["companion_device_limit"]),
            device_id=str(row["device_id"]),
            device_key=bytes(row["public_key"]),
            fingerprint=bytes(row["fingerprint_hash"]),
        )
        payload = lease_payload(terms, now_ms=now_ms, ttl_s=self.ttl_s, offline_s=self.offline_s)
        return {"lease": self.signer.sign(payload), "server_time_ms": now_ms}

    @staticmethod
    def _usable(row: dict[str, Any], now_ms: int) -> None:
        status = row["status"]
        if status in ("generated", "ready_for_sale"):
            # Satış havuzundaki anahtar: henüz kimseye ait değil. Anahtar 75 bit rastgele olduğu
            # için ayrı ileti tahminle bilgi sızdırmaz; yöneticiye ne yapılacağını söyler.
            raise LicenseError(404, "not_found", UNASSIGNED_MESSAGE)
        if status == "frozen":
            raise LicenseError(
                403, "frozen", "Lisans dondurulmuş. Ayrıntı için destek ile iletişime geçin."
            )
        if status == "cancelled":
            raise LicenseError(403, "cancelled", "Lisans iptal edilmiş")
        expires = _ms(row["expires_at"])
        if status == "expired" or (expires is not None and expires <= now_ms):
            raise LicenseError(
                403, "expired", "Lisansın süresi dolmuş. Yenilemek için paketlere bakın."
            )

    @staticmethod
    async def _actor(conn: Conn, actor_id: str) -> None:
        await conn.execute("SELECT set_config('ati.actor_type', 'engine', true)")
        await conn.execute("SELECT set_config('ati.actor_id', %s, true)", (actor_id,))

    @staticmethod
    async def _expire_if_due(conn: Conn, row: dict[str, Any], now_ms: int) -> None:
        expires = _ms(row["expires_at"])
        if row["status"] == "active" and expires is not None and expires <= now_ms:
            await conn.execute(
                "UPDATE licenses SET status = 'expired' WHERE id = %s AND status = 'active'",
                (row["license_id"],),
            )

    async def activate(self, conn: Conn, message: Any, *, ip: str) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        try:
            payload = open_device_request(message)
        except BadRequestSignature as exc:
            raise LicenseError(401, "bad_signature", str(exc)) from exc
        if payload.get("type") != "activate" or payload.get("platform", "windows") != "windows":
            raise LicenseError(400, "malformed", "İstek türü hatalı")
        ts = self._check_time(payload, now_ms)
        try:
            digest = self.hasher.digest(str(payload.get("license_key", "")))
            fingerprint = bytes.fromhex(str(payload.get("fingerprint", "")))
        except (InvalidLicenseKey, ValueError) as exc:
            raise LicenseError(400, "invalid_key", str(exc)) from exc
        if len(fingerprint) != 32:
            raise LicenseError(400, "malformed", "Cihaz parmak izi geçersiz")
        device_key = base64.b64decode(str(payload["device_key"]))
        name = str(payload.get("name") or "Bilgisayar")[:100].strip() or "Bilgisayar"
        app_version = str(payload.get("app_version") or "")[:40] or None
        os_version = str(payload.get("os_version") or "")[:80] or None

        try:
            async with _tx(conn):
                cur = await conn.execute(
                    "SELECT l.id AS license_id, l.serial, l.plan_code, p.name AS plan_name, "
                    "l.status::text AS status, l.customer_id, l.duration_days, l.expires_at, "
                    "l.device_limit, l.companion_device_limit "
                    "FROM licenses l JOIN license_plans p ON p.code = l.plan_code "
                    "WHERE l.key_hash = %s FOR UPDATE OF l",
                    (digest,),
                )
                lic = await cur.fetchone()
                if lic is None:
                    raise LicenseError(404, "not_found", "Lisans anahtarı geçersiz")
                await self._actor(conn, f"activation:{fingerprint.hex()[:16]}")
                await self._expire_if_due(conn, lic, now_ms)
                self._usable(lic, now_ms)

                cur = await conn.execute(
                    "SELECT id, revoked_at FROM devices WHERE customer_id = %s "
                    "AND platform = 'windows' AND fingerprint_hash = %s",
                    (lic["customer_id"], fingerprint),
                )
                device = await cur.fetchone()
                if device is not None and device["revoked_at"] is not None:
                    raise LicenseError(
                        403, "device_revoked", "Bu bilgisayar hesabınızdan kaldırılmış"
                    )
                if device is None:
                    cur = await conn.execute(
                        "INSERT INTO devices (customer_id, platform, fingerprint_hash, "
                        "display_name, public_key, app_version, os_version) "
                        "VALUES (%s, 'windows', %s, %s, %s, %s, %s) RETURNING id",
                        (
                            lic["customer_id"],
                            fingerprint,
                            name,
                            device_key,
                            app_version,
                            os_version,
                        ),
                    )
                    device = await cur.fetchone()
                    if device is None:
                        raise RuntimeError("cihaz kaydı oluşturulamadı")
                else:
                    # Aynı bilgisayara yeniden kurulum: anahtar sahibi cihaz anahtarını yeniler.
                    await conn.execute(
                        "UPDATE devices SET public_key = %s, display_name = %s, app_version = %s, "
                        "os_version = %s, last_seen_at = now() WHERE id = %s",
                        (device_key, name, app_version, os_version, device["id"]),
                    )
                cur = await conn.execute(
                    "SELECT id FROM license_activations WHERE license_id = %s AND device_id = %s "
                    "AND deactivated_at IS NULL",
                    (lic["license_id"], device["id"]),
                )
                if await cur.fetchone() is None:
                    await conn.execute(
                        "INSERT INTO license_activations (license_id, device_id) VALUES (%s, %s)",
                        (lic["license_id"], device["id"]),
                    )
                if lic["status"] == "sold":
                    # Süre ilk aktivasyonla başlar.
                    await conn.execute(
                        "UPDATE licenses SET status = 'active', activated_at = now(), "
                        "expires_at = CASE WHEN duration_days IS NULL THEN NULL "
                        "ELSE now() + make_interval(days => duration_days) END WHERE id = %s",
                        (lic["license_id"],),
                    )
                await conn.execute(
                    "UPDATE license_activations SET last_validated_at = now(), "
                    "last_request_ms = %s WHERE license_id = %s AND device_id = %s "
                    "AND deactivated_at IS NULL",
                    (ts, lic["license_id"], device["id"]),
                )
                await self._audit(
                    conn,
                    "license.activated",
                    str(lic["license_id"]),
                    ip,
                    {"device_id": str(device["id"]), "app_version": app_version},
                )
                row = await self._lease_row(conn, lic["license_id"], device["id"])
        except pg_errors.CheckViolation as exc:
            if exc.diag.message_hint == "device_limit_exceeded":
                raise LicenseError(
                    409,
                    "device_limit",
                    "Bu lisans için bilgisayar sınırına ulaşıldı. Müşteri panelinden "
                    "kullanmadığınız bir bilgisayarı kaldırıp tekrar deneyin.",
                ) from exc
            raise
        return self._lease(row, now_ms)

    async def _lease_row(self, conn: Conn, license_id: Any, device_id: Any) -> dict[str, Any]:
        cur = await conn.execute(
            "SELECT l.id AS license_id, l.serial, l.plan_code, p.name AS plan_name, "
            "l.status::text AS status, l.expires_at, l.device_limit, l.companion_device_limit, "
            "d.id AS device_id, d.public_key, d.fingerprint_hash "
            "FROM licenses l JOIN license_plans p ON p.code = l.plan_code, devices d "
            "WHERE l.id = %s AND d.id = %s",
            (license_id, device_id),
        )
        row = await cur.fetchone()
        if row is None:
            raise RuntimeError("lisans veya cihaz satırı bulunamadı")
        return row

    async def _device_request(
        self, conn: Conn, message: Any, kind: str, now_ms: int
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Yenileme/bırakma isteğini doğrular; aktivasyon satırını kilitler."""
        if not isinstance(message, dict) or not isinstance(message.get("p"), str):
            raise LicenseError(400, "malformed", "İstek biçimi hatalı")
        try:
            claimed = json.loads(message["p"])
            license_id = uuid.UUID(str(claimed.get("license_id")))
            device_id = uuid.UUID(str(claimed.get("device_id")))
        except (ValueError, TypeError, AttributeError) as exc:
            raise LicenseError(400, "malformed", "İstek biçimi hatalı") from exc
        cur = await conn.execute(
            "SELECT a.id AS activation_id, a.last_request_ms, d.public_key, d.revoked_at, "
            "l.id AS license_id, l.status::text AS status, l.expires_at "
            "FROM license_activations a JOIN licenses l ON l.id = a.license_id "
            "JOIN devices d ON d.id = a.device_id "
            "WHERE a.license_id = %s AND a.device_id = %s AND a.deactivated_at IS NULL "
            "FOR UPDATE OF a, l",
            (license_id, device_id),
        )
        row = await cur.fetchone()
        if row is None or row["public_key"] is None:
            raise LicenseError(
                403, "not_activated", "Bu bilgisayarda lisans etkin değil; yeniden etkinleştirin"
            )
        try:
            payload = open_device_request(message, bytes(row["public_key"]))
        except BadRequestSignature as exc:
            raise LicenseError(401, "bad_signature", str(exc)) from exc
        if payload.get("type") != kind:
            raise LicenseError(400, "malformed", "İstek türü hatalı")
        ts = self._check_time(payload, now_ms)
        if row["last_request_ms"] is not None and ts <= row["last_request_ms"]:
            raise LicenseError(409, "replay", "Bu istek daha önce kullanıldı")
        if row["revoked_at"] is not None:
            raise LicenseError(403, "device_revoked", "Bu bilgisayar hesabınızdan kaldırılmış")
        await conn.execute(
            "UPDATE license_activations SET last_request_ms = %s WHERE id = %s",
            (ts, row["activation_id"]),
        )
        return row, {"license_id": license_id, "device_id": device_id}

    async def renew(self, conn: Conn, message: Any, *, ip: str) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        async with _tx(conn):
            row, ids = await self._device_request(conn, message, "renew", now_ms)
            await self._actor(conn, f"device:{ids['device_id']}")
            await self._expire_if_due(conn, row, now_ms)
            self._usable(row, now_ms)
            await conn.execute(
                "UPDATE license_activations SET last_validated_at = now() WHERE id = %s",
                (row["activation_id"],),
            )
            await conn.execute(
                "UPDATE devices SET last_seen_at = now() WHERE id = %s", (ids["device_id"],)
            )
            lease_row = await self._lease_row(conn, ids["license_id"], ids["device_id"])
        return self._lease(lease_row, now_ms)

    async def release(self, conn: Conn, message: Any, *, ip: str) -> None:
        """Motorun kendi isteğiyle cihazı bırakması (bilgisayar değişikliği)."""
        now_ms = int(time.time() * 1000)
        async with _tx(conn):
            row, ids = await self._device_request(conn, message, "deactivate", now_ms)
            await self._actor(conn, f"device:{ids['device_id']}")
            await conn.execute(
                "UPDATE license_activations SET deactivated_at = now(), deactivated_by = 'engine', "
                "deactivation_reason = 'device_request' WHERE id = %s",
                (row["activation_id"],),
            )
            await self._audit(
                conn, "license.device_released", str(ids["license_id"]), ip,
                {"device_id": str(ids["device_id"])},
            )  # fmt: skip

    # --- Müşteri paneli ----------------------------------------------------------------------

    async def customer_release(
        self, conn: Conn, *, customer_id: Any, license_id: str, device_id: str, ip: str
    ) -> int:
        """Müşteri panelinden cihaz kaldırma; 30 günde ``resets_per_30d`` ile sınırlı.
        Kalan hakkı döner."""
        try:
            lic_uuid, dev_uuid = uuid.UUID(license_id), uuid.UUID(device_id)
        except ValueError as exc:
            raise LicenseError(404, "not_found", "Lisans veya cihaz bulunamadı") from exc
        async with conn.transaction():
            cur = await conn.execute(
                "SELECT id FROM licenses WHERE id = %s AND customer_id = %s FOR UPDATE",
                (lic_uuid, customer_id),
            )
            if await cur.fetchone() is None:
                raise LicenseError(404, "not_found", "Lisans veya cihaz bulunamadı")
            used = await self.resets_used(conn, lic_uuid)
            if used >= self.resets_per_30d:
                raise LicenseError(
                    429,
                    "reset_limit",
                    f"Son 30 günde en fazla {self.resets_per_30d} bilgisayar kaldırabilirsiniz. "
                    "Daha fazlası için destek ile iletişime geçin.",
                )
            await conn.execute("SELECT set_config('ati.actor_type', 'customer', true)")
            await conn.execute("SELECT set_config('ati.actor_id', %s, true)", (str(customer_id),))
            cur = await conn.execute(
                "UPDATE license_activations SET deactivated_at = now(), "
                "deactivated_by = 'customer', deactivation_reason = 'customer_panel' "
                "WHERE license_id = %s AND device_id = %s AND deactivated_at IS NULL RETURNING id",
                (lic_uuid, dev_uuid),
            )
            if await cur.fetchone() is None:
                raise LicenseError(404, "not_found", "Lisans veya cihaz bulunamadı")
            await self._audit(
                conn, "license.device_removed", str(lic_uuid), ip,
                {"device_id": str(dev_uuid)}, actor_type="customer", actor_id=str(customer_id),
            )  # fmt: skip
        return self.resets_per_30d - used - 1

    @staticmethod
    async def resets_used(conn: Conn, license_id: Any) -> int:
        cur = await conn.execute(
            "SELECT count(*)::int AS n FROM license_activations WHERE license_id = %s "
            "AND deactivated_by = 'customer' AND deactivated_at > now() - interval '30 days'",
            (license_id,),
        )
        row = await cur.fetchone()
        return int(row["n"]) if row else 0

    async def reveal(self, conn: Conn, *, customer_id: Any, license_id: str, ip: str) -> str:
        try:
            lic_uuid = uuid.UUID(license_id)
        except ValueError as exc:
            raise LicenseError(404, "not_found", "Lisans bulunamadı") from exc
        cur = await conn.execute(
            "SELECT key_hash, key_ciphertext FROM licenses WHERE id = %s AND customer_id = %s",
            (lic_uuid, customer_id),
        )
        row = await cur.fetchone()
        if row is None:
            raise LicenseError(404, "not_found", "Lisans bulunamadı")
        key = self.cipher.decrypt(bytes(row["key_ciphertext"]), bytes(row["key_hash"]))
        await self._audit(
            conn, "license.key_revealed", str(lic_uuid), ip, {},
            actor_type="customer", actor_id=str(customer_id),
        )  # fmt: skip
        return key

    @staticmethod
    async def _audit(
        conn: Conn,
        action: str,
        license_id: str,
        ip: str,
        details: dict[str, Any],
        *,
        actor_type: str = "engine",
        actor_id: str | None = None,
    ) -> None:
        from psycopg.types.json import Jsonb

        await conn.execute(
            "INSERT INTO audit_log (actor_type, actor_id, action, target_type, target_id, ip, "
            "details) VALUES (%s, %s, %s, 'license', %s, %s, %s)",
            (actor_type, actor_id, action, license_id, ip, Jsonb(details)),
        )
