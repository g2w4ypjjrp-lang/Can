"""Lisans yöneticisi: etkinleştirme, kira yenileme, cihaz bırakma ve işlem kapısı.

Durumlar:

* ``not_configured`` — Bu sürümde güvenilir kira anahtarı yok (lisans sunucusu yayında değil, G5).
* ``unlicensed`` — Bu bilgisayarda lisans etkin değil.
* ``active`` — Kira geçerli.
* ``offline_grace`` — Kira yenilenemedi (ağ yok) ama çevrim dışı tolerans süresi içinde.
* ``lease_expired`` — Çevrim dışı tolerans doldu; sunucuya bağlanıp yenilemek gerekir.
* ``license_expired`` — Lisans süresi bitti.
* ``revoked`` — Sunucu reddetti (iptal, dondurma, cihaz kaldırıldı...).
* ``clock_error`` — Bilgisayar saati geri alınmış görünüyor; çevrim içi yenileme gerekir.

``enforce`` açıkken ``license.valid`` hazırlık koşulu yalnızca ``active`` ve ``offline_grace``
durumlarında doğrudur. Koşul yanlışken motor güvenli moda iner: **yeni işlem açılmaz**,
açık pozisyonlar ve stoplar yönetilmeye devam eder.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import platform
import secrets
import time
from collections.abc import Callable
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ati_engine import __version__
from ati_engine.config import LicenseSettings
from ati_engine.licensing.device import device_fingerprint
from ati_engine.licensing.keys import format_key, key_hint, normalize
from ati_engine.licensing.lease import Lease, LeaseError, verify_lease
from ati_engine.safety.coordinator import SafetyCoordinator
from ati_engine.security.vault import SecretVault
from ati_engine.storage.database import Database

logger = logging.getLogger(__name__)

CONDITION = "license.valid"
CLOCK_ROLLBACK_TOLERANCE_MS = 10 * 60 * 1000
# Sunucunun bu kodları kalıcıdır: yerel kira silinir. "bad_signature": aynı bilgisayara başka bir
# kurulum etkinleştirilmiş (cihaz anahtarı değişmiş).
TERMINAL = frozenset(
    {
        "not_found",
        "cancelled",
        "frozen",
        "expired",
        "not_activated",
        "device_revoked",
        "bad_signature",
    }
)
VALID_STATES = frozenset({"active", "offline_grace"})

MESSAGES = {
    "not_configured": "Bu sürümde lisans sunucusu henüz yapılandırılmadı.",
    "unlicensed": "Bu bilgisayarda lisans etkin değil. Lisans anahtarınızı girin.",
    "active": "Lisans etkin.",
    "offline_grace": "Lisans sunucusuna ulaşılamıyor; çevrim dışı tolerans süresi içindesiniz.",
    "lease_expired": "Çevrim dışı tolerans süresi doldu. İnternete bağlanıp lisansı yenileyin.",
    "license_expired": "Lisansın süresi doldu. Yenilemek için paketlere göz atın.",
    "revoked": "Lisans bu bilgisayarda geçersiz.",
    "clock_error": "Bilgisayar saati geri alınmış görünüyor. Saati düzeltip lisansı yenileyin.",
}


class LicenseUnavailable(RuntimeError):
    """Sunucuya ulaşılamadı veya lisans sistemi yapılandırılmadı (geçici durum)."""


class LicenseRejected(RuntimeError):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class LicenseManager:
    def __init__(
        self,
        *,
        settings: LicenseSettings,
        db: Database,
        vault: SecretVault,
        safety: SafetyCoordinator | None = None,
        clock: Callable[[], int] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        fingerprint_override: str | None = None,
        device_name: str | None = None,
    ) -> None:
        self.settings = settings
        self.db = db
        self.vault = vault
        self.safety = safety
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._transport = transport
        self._fingerprint_override = fingerprint_override
        self.device_name = (device_name or platform.node() or "Bilgisayar")[:100]
        self.trusted = {kid: base64.b64decode(pub) for kid, pub in settings.trusted_keys.items()}
        self._key: Ed25519PrivateKey | None = None
        self.fingerprint = b""
        self.lease: Lease | None = None
        self.key_hint: str | None = None
        self.offset_ms = 0
        self.max_seen_ms = 0
        self.last_renewed_ms: int | None = None
        self.last_error: str | None = None
        self.revoked: tuple[str, str] | None = None
        self._last_ts = 0
        self._lock = asyncio.Lock()
        self._registered = False
        self._persisted_max_ms = 0

    # --- Açılış ve kalıcılık -----------------------------------------------------------------

    async def load(self) -> None:
        stored = await self.vault.get("license.device_key")
        if stored is None:
            self._key = Ed25519PrivateKey.generate()
            raw = self._key.private_bytes_raw()
            await self.vault.put("license.device_key", base64.b64encode(raw).decode())
        else:
            self._key = Ed25519PrivateKey.from_private_bytes(
                base64.b64decode(stored.get_secret_value())
            )
        self.fingerprint = await device_fingerprint(self.vault, override=self._fingerprint_override)
        row = await self.db.fetchone(
            "SELECT lease_json, key_hint, server_offset_ms, max_seen_ms, last_renewed_ms, "
            "last_error, revoked_code, revoked_message FROM license_state WHERE id = 1"
        )
        if row is not None:
            lease_json, hint, offset, max_seen, renewed, error, code, message = row
            self.key_hint, self.offset_ms, self.max_seen_ms = hint, int(offset), int(max_seen)
            self._persisted_max_ms = self.max_seen_ms
            self.last_renewed_ms, self.last_error = renewed, error
            self.revoked = (code, message) if code else None
            if lease_json:
                try:
                    self.lease = verify_lease(
                        json.loads(lease_json),
                        self.trusted,
                        device_key=self.device_public_key,
                        fingerprint=self.fingerprint,
                    )
                except LeaseError as exc:
                    logger.warning("Kayıtlı kira geçersiz", extra={"code": exc.code})
                    self.lease = None
                    self.last_error = exc.message
        if self.settings.enforce and self.safety is not None and not self._registered:
            self.safety.register_condition(CONDITION, ready=False, detail="lisans denetleniyor")
            self._registered = True
        await self._update_readiness()

    async def _save(self) -> None:
        self._persisted_max_ms = self.max_seen_ms
        await self.db.execute(
            "INSERT INTO license_state (id, lease_json, key_hint, server_offset_ms, max_seen_ms, "
            "last_renewed_ms, last_error, revoked_code, revoked_message, updated_at) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "lease_json = excluded.lease_json, key_hint = excluded.key_hint, "
            "server_offset_ms = excluded.server_offset_ms, max_seen_ms = excluded.max_seen_ms, "
            "last_renewed_ms = excluded.last_renewed_ms, last_error = excluded.last_error, "
            "revoked_code = excluded.revoked_code, revoked_message = excluded.revoked_message, "
            "updated_at = excluded.updated_at",
            (
                canonical(self.lease.signed) if self.lease else None,
                self.key_hint,
                self.offset_ms,
                self.max_seen_ms,
                self.last_renewed_ms,
                self.last_error,
                self.revoked[0] if self.revoked else None,
                self.revoked[1] if self.revoked else None,
                self._clock(),
            ),
        )

    @property
    def device_public_key(self) -> bytes:
        if self._key is None:
            raise RuntimeError("Lisans yöneticisi yüklenmedi")
        return self._key.public_key().public_bytes_raw()

    # --- Durum -------------------------------------------------------------------------------

    def server_now(self) -> int:
        return self._clock() + self.offset_ms

    def state(self) -> str:
        now = self.server_now()
        if self.lease is None:
            if self.revoked:
                return "revoked"
            return "unlicensed" if self.trusted else "not_configured"
        if now < self.max_seen_ms - CLOCK_ROLLBACK_TOLERANCE_MS:
            return "clock_error"
        expires = self.lease.license_expires_at
        if expires is not None and now >= expires:
            return "license_expired"
        if now < self.lease.valid_until:
            return "active"
        if now < self.lease.offline_until:
            return "offline_grace"
        return "lease_expired"

    @property
    def valid(self) -> bool:
        return self.state() in VALID_STATES

    def companion_limit(self) -> int | None:
        """Eşleştirilebilecek telefon sayısı (lisans zorunluyken); zorunlu değilse sınırsız."""
        if not self.settings.enforce:
            return None
        return self.lease.companion_device_limit if self.lease and self.valid else 0

    def status(self) -> dict[str, Any]:
        state = self.state()
        data = self.lease.data if self.lease else {}
        message = MESSAGES[state]
        if state == "revoked" and self.revoked:
            message = self.revoked[1]
        return {
            "state": state,
            "valid": state in VALID_STATES,
            "enforced": self.settings.enforce,
            "configured": bool(self.trusted),
            "message": message,
            "key_hint": self.key_hint,
            "license_id": data.get("license_id"),
            "serial": data.get("serial"),
            "plan_code": data.get("plan_code"),
            "plan_name": data.get("plan_name"),
            "device_limit": data.get("device_limit"),
            "companion_device_limit": data.get("companion_device_limit"),
            "license_expires_at": data.get("license_expires_at"),
            "valid_until": data.get("valid_until"),
            "offline_until": data.get("offline_until"),
            "last_renewed_at": self.last_renewed_ms,
            "last_error": self.last_error,
            "server_url": self.settings.server_url,
        }

    async def _update_readiness(self) -> None:
        now = self.server_now()
        if self.lease is not None and now > self.max_seen_ms:
            self.max_seen_ms = now
            # Saat geri alma tespiti yeniden başlatmadan sonra da çalışsın diye düzenli kaydedilir.
            if self.max_seen_ms - self._persisted_max_ms > 5 * 60 * 1000:
                await self._save()
        if self._registered and self.safety is not None:
            state = self.state()
            await self.safety.set_ready(CONDITION, state in VALID_STATES, MESSAGES[state])

    # --- Sunucu istekleri ------------------------------------------------------------------

    def _sign(self, payload: dict[str, Any]) -> dict[str, str]:
        if self._key is None:
            raise RuntimeError("Lisans yöneticisi yüklenmedi")
        self._last_ts = max(self._last_ts + 1, self.server_now())
        body = {**payload, "v": 1, "ts_ms": self._last_ts, "nonce": secrets.token_hex(8)}
        text = canonical(body)
        signature = self._key.sign(text.encode("utf-8"))
        return {"p": text, "s": base64.b64encode(signature).decode()}

    async def _post(self, path: str, message: dict[str, str]) -> dict[str, Any]:
        if not self.trusted:
            raise LicenseUnavailable(MESSAGES["not_configured"])
        try:
            async with httpx.AsyncClient(
                base_url=self.settings.server_url,
                timeout=self.settings.request_timeout_s,
                transport=self._transport,
                headers={"User-Agent": f"ati-engine/{__version__}"},
            ) as client:
                response = await client.post(path, json=message)
        except httpx.HTTPError as exc:
            raise LicenseUnavailable("Lisans sunucusuna ulaşılamadı") from exc
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code == 200 and isinstance(body, dict):
            return body
        detail = body.get("detail") if isinstance(body, dict) else None
        if isinstance(detail, dict) and "code" in detail:
            raise LicenseRejected(response.status_code, str(detail["code"]), str(detail["message"]))
        if response.status_code == 429:
            raise LicenseUnavailable("Çok fazla deneme; biraz sonra tekrar deneyin")
        raise LicenseUnavailable(f"Lisans sunucusu yanıt vermedi (HTTP {response.status_code})")

    def _accept(self, body: dict[str, Any], received_local_ms: int) -> None:
        lease = verify_lease(
            body.get("lease"),
            self.trusted,
            device_key=self.device_public_key,
            fingerprint=self.fingerprint,
        )
        server_time = body.get("server_time_ms")
        if isinstance(server_time, int):
            self.offset_ms = server_time - received_local_ms
        self.lease = lease
        self.max_seen_ms = max(lease.issued_at, self.server_now())
        self.last_renewed_ms = lease.issued_at
        self.last_error = None
        self.revoked = None

    # --- İşlemler ----------------------------------------------------------------------------

    async def activate(self, key: str) -> dict[str, Any]:
        body_key = format_key(normalize(key))  # yazım hatası sunucuya gitmeden yakalanır
        async with self._lock:
            message = self._sign(
                {
                    "type": "activate",
                    "license_key": body_key,
                    "device_key": base64.b64encode(self.device_public_key).decode(),
                    "fingerprint": self.fingerprint.hex(),
                    "name": self.device_name,
                    "platform": "windows",
                    "app_version": __version__,
                    "os_version": f"{platform.system()} {platform.release()}"[:80],
                }
            )
            body = await self._post("/v1/licenses/activate", message)
            self._accept(body, self._clock())
            self.key_hint = key_hint(body_key)
            await self._save()
            await self._update_readiness()
            logger.info("Lisans etkinleştirildi", extra={"license_id": self.lease_id})
            return self.status()

    @property
    def lease_id(self) -> str | None:
        return self.lease.license_id if self.lease else None

    async def refresh(self) -> dict[str, Any]:
        """Kirayı yeniler. Ağ hatasında mevcut kira korunur (çevrim dışı tolerans)."""
        async with self._lock:
            if self.lease is None:
                await self._update_readiness()
                return self.status()
            message = self._sign(
                {
                    "type": "renew",
                    "license_id": self.lease.license_id,
                    "device_id": self.lease.device_id,
                }
            )
            try:
                body = await self._post("/v1/licenses/renew", message)
                self._accept(body, self._clock())
            except LicenseRejected as exc:
                if exc.code in TERMINAL:
                    self.lease = None
                    self.revoked = (exc.code, exc.message)
                self.last_error = exc.message
            except (LicenseUnavailable, LeaseError) as exc:
                self.last_error = str(exc)
            await self._save()
            await self._update_readiness()
            return self.status()

    async def deactivate(self) -> dict[str, Any]:
        """Bu bilgisayarı lisanstan çıkarır (bilgisayar değişikliği). Sunucuya ulaşılamazsa yerel
        kira silinmez: yer sunucuda dolu kalacağı için müşteri panelinden kaldırılmalıdır."""
        async with self._lock:
            if self.lease is None:
                return self.status()
            message = self._sign(
                {
                    "type": "deactivate",
                    "license_id": self.lease.license_id,
                    "device_id": self.lease.device_id,
                }
            )
            try:
                await self._post("/v1/licenses/deactivate", message)
            except LicenseRejected as exc:
                if exc.code not in TERMINAL:
                    raise
            self.lease = None
            self.key_hint = None
            self.revoked = None
            self.last_error = None
            await self._save()
            await self._update_readiness()
            return self.status()

    # --- Arka plan döngüsü -----------------------------------------------------------------

    async def run(self) -> None:
        """Kirayı düzenli yeniler (etkinken 6 saatte bir, değilse sık aralıkla); aralarda süreye
        bağlı durum değişikliklerini (ör. tolerans bitimi) hazırlık koşuluna yansıtır."""
        while True:
            if self.lease is not None:
                with contextlib.suppress(Exception):
                    await self.refresh()
            healthy = self.state() == "active" and self.last_error is None
            wait = self.settings.renew_interval_s if healthy else self.settings.retry_interval_s
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline:
                await asyncio.sleep(min(60.0, max(0.0, deadline - time.monotonic())))
                await self._update_readiness()
                if healthy and self.lease is not None and self.state() != "active":
                    break  # kira yenileme zamanı geldi veya saat sorunu: hemen dene
